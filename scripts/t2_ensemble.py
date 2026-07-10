#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t2_ensemble.py — T+2 NAV Forecast Engine (Ensemble ARIMA + XGBoost)
T2-005

Kết hợp dự báo mới nhất của `arima-v1` + `xgb-v1` (phải cùng predicted_for_date
— nếu lệch ngày thì bỏ qua quỹ đó, coi như 1 trong 2 model chưa chạy xong hôm
đó) bằng weighted average, ghi vào nav_predictions với model_version='ensemble-v1'.

CI = predicted_nav ± 1.5 × rolling_std(error_pct, 30 ngày) của chính ensemble-v1
     (ưu tiên per-fund nếu đủ ≥5 mẫu đã chấm điểm, fallback toàn cục nếu không
     đủ, fallback cứng FALLBACK_CI_PCT nếu ensemble-v1 chưa có lịch sử chấm điểm
     nào — luôn đúng cho vài tuần đầu tiên sau khi bật ensemble).

Weights (khởi tạo tĩnh — T2-008 sẽ làm adaptive theo MAPE 30 ngày gần nhất
giữa 2 model con, ghi đè W_ARIMA/W_XGB qua config thay vì hardcode):
  W_ARIMA = 0.3
  W_XGB   = 0.7

Modes:
  --predict            Ensemble cho tất cả quỹ có đủ cả 2 dự báo cùng ngày
  --predict --code X   Chỉ 1 quỹ
  --status             So sánh MAPE ensemble-v1 vs arima-v1 vs xgb-v1

Yêu cầu: DATABASE_URL env var. Chạy SAU cả t2_arima.py --predict và
t2_xgboost.py --predict trong cùng 1 lần cron (~18:31, ngay sau harvest 18:30):
  python3 scripts/t2_arima.py --predict
  python3 scripts/t2_xgboost.py --predict
  python3 scripts/t2_ensemble.py --predict
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from t2_arima import _db_url, _get_conn  # noqa: E402

MODEL_VERSION  = "ensemble-v1"
W_ARIMA        = 0.3
W_XGB          = 0.7
FALLBACK_CI_PCT = 2.0   # dùng khi chưa đủ lịch sử chấm điểm ensemble-v1 (rolling std = None)


def _latest_pred(conn, fund_code: str, model_version: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT predicted_for_date, predicted_nav
            FROM nav_predictions
            WHERE fund_code = %s AND model_version = %s
            ORDER BY predicted_for_date DESC, created_at DESC
            LIMIT 1
        """, (fund_code.upper(), model_version))
        row = cur.fetchone()
    if not row:
        return {}
    return {"predicted_for_date": row[0], "predicted_nav": row[1]}


def cmd_predict(only_code: str = None):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db

    conn = _get_conn()
    with conn.cursor() as cur:
        if only_code:
            cur.execute(
                "SELECT DISTINCT fund_code FROM nav_predictions WHERE fund_code = %s",
                (only_code.upper(),)
            )
        else:
            cur.execute("""
                SELECT DISTINCT fund_code FROM nav_predictions
                WHERE model_version IN ('arima-v1', 'xgb-v1')
                ORDER BY fund_code
            """)
        codes = [r[0] for r in cur.fetchall()]

    print(f"Ensemble T+2 cho {len(codes)} quỹ (W_ARIMA={W_ARIMA}, W_XGB={W_XGB})...")
    ok = skipped = errors = 0

    for code in codes:
        arima = _latest_pred(conn, code, "arima-v1")
        xgb_p = _latest_pred(conn, code, "xgb-v1")
        if not arima or not xgb_p:
            skipped += 1
            continue
        if arima["predicted_for_date"] != xgb_p["predicted_for_date"]:
            print(f"  {code}: date mismatch arima={arima['predicted_for_date']} "
                  f"xgb={xgb_p['predicted_for_date']} — skip (1 model chưa chạy hôm nay)")
            skipped += 1
            continue

        ens_nav = W_ARIMA * arima["predicted_nav"] + W_XGB * xgb_p["predicted_nav"]

        std = db.get_rolling_error_std(MODEL_VERSION, fund_code=code, window_days=30)
        ci_pct = 1.5 * std if std is not None else FALLBACK_CI_PCT
        ci_low  = ens_nav * (1 - ci_pct / 100)
        ci_high = ens_nav * (1 + ci_pct / 100)

        try:
            pred_id = db.save_prediction(
                fund_code           = code,
                predicted_for_date  = arima["predicted_for_date"],
                predicted_nav       = ens_nav,
                model_version       = MODEL_VERSION,
                ci_low              = ci_low,
                ci_high             = ci_high,
            )
            print(f"  {code}: T+2={arima['predicted_for_date']} nav={ens_nav:.4f} "
                  f"CI=[{ci_low:.4f}, {ci_high:.4f}] (±{ci_pct:.2f}%) id={pred_id}")
            ok += 1
        except Exception as e:
            print(f"  {code}: DB error: {e}", file=sys.stderr)
            errors += 1

    conn.close()
    print(f"\nEnsemble xong: {ok} OK, {skipped} skip (thiếu 1 trong 2 model), {errors} lỗi")


def cmd_status():
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT np.model_version,
                   ROUND(AVG(ABS(pa.error_pct))::numeric, 2) AS mape,
                   COUNT(*) AS n
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            WHERE np.model_version IN ('arima-v1', 'xgb-v1', 'ensemble-v1')
            GROUP BY np.model_version
            ORDER BY mape
        """)
        rows = cur.fetchall()
    conn.close()

    if not rows:
        print("Chưa có dữ liệu chấm điểm cho arima-v1/xgb-v1/ensemble-v1.")
        return
    print("MAPE so sánh (thấp hơn = tốt hơn):")
    for model_version, mape, n in rows:
        print(f"  {model_version}: MAPE={mape}% (n={n})")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _db_url():
        print("ERROR: DATABASE_URL chưa được set", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="T+2 Ensemble Forecast Engine (ARIMA + XGBoost)")
    parser.add_argument("--predict", action="store_true", help="Ensemble dự báo T+2 cho tất cả quỹ")
    parser.add_argument("--status",  action="store_true", help="So sánh MAPE ensemble vs 2 model con")
    parser.add_argument("--code",    type=str,             help="Chỉ xử lý 1 mã quỹ")
    args = parser.parse_args()

    if args.predict:
        cmd_predict(args.code)
    elif args.status:
        cmd_status()
    else:
        parser.print_help()
