#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t2_ensemble.py — T+2 NAV Forecast Engine (Ensemble ARIMA + XGBoost + Naive)
T2-005 / T2-012

Kết hợp dự báo mới nhất của `arima-v1` + `xgb-vN` + `naive-v1` (phải cùng
predicted_for_date — nếu lệch ngày hoặc thiếu 1 trong 3 thì bỏ qua quỹ đó,
coi như chưa chạy đủ hôm đó) bằng weighted average, ghi vào nav_predictions
với model_version='ensemble-v1'.

T2-012 (2026-07-14): thêm naive-v1 (persistence — dự báo "NAV không đổi")
làm thành phần thứ 3. Lý do: backtest walk-forward trên dữ liệu thật (xem
BACKLOG.md) cho thấy naive đánh bại ARIMA(2,1,2) ở CẢ 8/8 quỹ test, và ARIMA
thỉnh thoảng dự báo lệch cực đoan (1 quỹ ra MAPE 716%). Đưa naive vào ensemble
để trọng số tự điều chỉnh công bằng theo MAPE thật, thay vì ensemble luôn bị
kéo lệch bởi 2 model phức tạp hơn nhưng chưa chắc chính xác hơn.

CI = predicted_nav ± 1.5 × rolling_std(error_pct, 30 ngày) của chính ensemble-v1
     (ưu tiên per-fund nếu đủ ≥5 mẫu đã chấm điểm, fallback toàn cục nếu không
     đủ, fallback cứng FALLBACK_CI_PCT nếu ensemble-v1 chưa có lịch sử chấm điểm
     nào — luôn đúng cho vài tuần đầu tiên sau khi bật ensemble).

Weights (T2-008/T2-012 — adaptive, inverse-MAPE 3 chiều): khởi tạo tĩnh
W_ARIMA=0.2/W_XGB=0.3/W_NAIVE=0.5 (nghiêng về naive theo bằng chứng backtest
ban đầu). `--reweight` tính lại mỗi 30 ngày dựa trên MAPE 30 ngày gần nhất
của cả 3 model — trọng số tỷ lệ nghịch với MAPE (model sai ít hơn được trọng
số cao hơn), chuẩn hoá để tổng = 1:
  w_i = (1/mape_i) / sum(1/mape_j for j in {arima, xgb, naive})
Lưu vào DATA_DIR/models/ensemble_weights.json; --predict tự load file này
nếu có, fallback về weights tĩnh nếu chưa từng --reweight hoặc chưa đủ dữ
liệu chấm điểm (< MIN_SAMPLES_REWEIGHT mỗi model trong 30 ngày).

Modes:
  --predict            Ensemble cho tất cả quỹ có đủ cả 3 dự báo cùng ngày
  --predict --code X   Chỉ 1 quỹ
  --reweight           T2-008: tính lại trọng số theo MAPE 30 ngày qua (3 model)
  --status             So sánh MAPE ensemble-v1 vs arima-v1 vs xgb-vN vs naive-v1 + trọng số hiện tại

Yêu cầu: DATABASE_URL env var. Chạy SAU cả 3 model con trong cùng 1 lần cron
(~18:31, ngay sau harvest 18:30):
  python3 scripts/t2_arima.py --predict
  python3 scripts/t2_xgboost.py --predict
  python3 scripts/t2_naive.py --predict
  python3 scripts/t2_ensemble.py --predict

Reweight định kỳ (mỗi 30 ngày, cron riêng trong bot.py — job_t2_reweight):
  python3 scripts/t2_ensemble.py --reweight
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from t2_arima import _db_url, _get_conn  # noqa: E402

MODEL_VERSION  = "ensemble-v1"
NAIVE_VERSION  = "naive-v1"

# Weights tĩnh mặc định — nghiêng về naive theo bằng chứng backtest walk-forward
# ban đầu (naive thắng ARIMA ở 8/8 quỹ test, xem BACKLOG.md T2-011/T2-012).
# --reweight sẽ tự điều chỉnh lại theo MAPE thật ngay khi đủ dữ liệu.
W_ARIMA = 0.2
W_XGB   = 0.3
W_NAIVE = 0.5

FALLBACK_CI_PCT = 2.0   # dùng khi chưa đủ lịch sử chấm điểm ensemble-v1 (rolling std = None)

# GOV-007 (2026-07-14): dùng DATA_DIR bền vững (Railway volume /data), không
# lưu trong scripts/models nữa — xem lý do trong t2_xgboost.py.
_DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "telegram-bot"))
WEIGHTS_PATH = os.path.join(_DATA_DIR, "models", "ensemble_weights.json")
REWEIGHT_WINDOW_DAYS  = 30
MIN_SAMPLES_REWEIGHT  = 10   # mỗi model cần ≥10 mẫu đã chấm điểm trong window mới tin cậy để reweight


def _load_weights() -> tuple:
    """Đọc trọng số adaptive đã lưu (nếu có), fallback về weights tĩnh 3 chiều.
    File cũ (trước T2-012) chỉ có w_arima/w_xgb (2 chiều, không có w_naive) —
    coi như chưa hợp lệ, fallback về mặc định mới thay vì cố migrate 2→3."""
    if os.path.exists(WEIGHTS_PATH):
        try:
            with open(WEIGHTS_PATH, encoding="utf-8") as f:
                w = json.load(f)
            return float(w["w_arima"]), float(w["w_xgb"]), float(w["w_naive"])
        except Exception:
            pass
    return W_ARIMA, W_XGB, W_NAIVE


def _mape_last_days(conn, model_version: str, window_days: int, min_samples: int) -> "float | None":
    with conn.cursor() as cur:
        cur.execute("""
            SELECT AVG(ABS(pa.error_pct)), COUNT(*)
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            WHERE np.model_version = %s
              AND pa.logged_at >= NOW() - (%s || ' days')::interval
        """, (model_version, window_days))
        mape, n = cur.fetchone()
    if n and n >= min_samples and mape is not None and mape > 0:
        return float(mape)
    return None


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


def _latest_xgb_version(conn) -> str:
    """T2-007 bump version (xgb-v1 → xgb-v2 → ...) mỗi lần --train — không được
    hardcode 'xgb-v1' ở đây (BUG cũ: ensemble skip 100% quỹ ngay sau lần
    retrain thứ 2 vì tìm 'xgb-v1' trong khi predictions mới nhất đã ghi dưới
    'xgb-v2'). Lấy version XGBoost được dùng gần đây nhất trong nav_predictions."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT model_version FROM nav_predictions
            WHERE model_version LIKE 'xgb-v%'
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
    return row[0] if row else "xgb-v1"


def cmd_predict(only_code: str = None):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db
    if not db.is_available():
        db.init_pool()  # save_prediction() dùng db.get_conn() (pooled) — cần init trước

    w_arima, w_xgb, w_naive = _load_weights()

    conn = _get_conn()
    xgb_version = _latest_xgb_version(conn)
    with conn.cursor() as cur:
        if only_code:
            cur.execute(
                "SELECT DISTINCT fund_code FROM nav_predictions WHERE fund_code = %s",
                (only_code.upper(),)
            )
        else:
            cur.execute("""
                SELECT DISTINCT fund_code FROM nav_predictions
                WHERE model_version IN ('arima-v1', %s, %s)
                ORDER BY fund_code
            """, (xgb_version, NAIVE_VERSION))
        codes = [r[0] for r in cur.fetchall()]

    print(f"Ensemble T+2 cho {len(codes)} quỹ "
          f"(W_ARIMA={w_arima:.3f}, W_XGB={w_xgb:.3f}, W_NAIVE={w_naive:.3f}, xgb_version={xgb_version})...")
    ok = skipped = errors = 0

    for code in codes:
        arima = _latest_pred(conn, code, "arima-v1")
        xgb_p = _latest_pred(conn, code, xgb_version)
        naive = _latest_pred(conn, code, NAIVE_VERSION)
        if not arima or not xgb_p or not naive:
            skipped += 1
            continue
        dates = {arima["predicted_for_date"], xgb_p["predicted_for_date"], naive["predicted_for_date"]}
        if len(dates) > 1:
            print(f"  {code}: date mismatch arima={arima['predicted_for_date']} "
                  f"xgb={xgb_p['predicted_for_date']} naive={naive['predicted_for_date']} "
                  f"— skip (1 model chưa chạy hôm nay)")
            skipped += 1
            continue

        ens_nav = (w_arima * arima["predicted_nav"]
                   + w_xgb * xgb_p["predicted_nav"]
                   + w_naive * naive["predicted_nav"])

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
    print(f"\nEnsemble xong: {ok} OK, {skipped} skip (thiếu 1 trong 3 model), {errors} lỗi")


def cmd_reweight():
    """T2-008/T2-012: tính lại W_ARIMA/W_XGB/W_NAIVE theo MAPE 30 ngày qua
    (inverse-MAPE weighting 3 chiều — model sai ít hơn được trọng số cao hơn)."""
    conn = _get_conn()
    xgb_version = _latest_xgb_version(conn)
    mape_arima = _mape_last_days(conn, "arima-v1",    REWEIGHT_WINDOW_DAYS, MIN_SAMPLES_REWEIGHT)
    mape_xgb   = _mape_last_days(conn, xgb_version,   REWEIGHT_WINDOW_DAYS, MIN_SAMPLES_REWEIGHT)
    mape_naive = _mape_last_days(conn, NAIVE_VERSION, REWEIGHT_WINDOW_DAYS, MIN_SAMPLES_REWEIGHT)
    conn.close()

    if mape_arima is None or mape_xgb is None or mape_naive is None:
        cur_w_arima, cur_w_xgb, cur_w_naive = _load_weights()
        print(f"Không đủ dữ liệu chấm điểm {REWEIGHT_WINDOW_DAYS} ngày qua cho cả 3 model "
              f"(cần ≥{MIN_SAMPLES_REWEIGHT} mẫu/model) — giữ nguyên trọng số hiện tại "
              f"(W_ARIMA={cur_w_arima:.3f}, W_XGB={cur_w_xgb:.3f}, W_NAIVE={cur_w_naive:.3f}).")
        return

    inv_arima = 1.0 / mape_arima
    inv_xgb   = 1.0 / mape_xgb
    inv_naive = 1.0 / mape_naive
    total = inv_arima + inv_xgb + inv_naive

    w_arima = inv_arima / total
    w_xgb   = inv_xgb / total
    w_naive = inv_naive / total

    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "w_arima": w_arima, "w_xgb": w_xgb, "w_naive": w_naive,
            "mape_arima": mape_arima, "mape_xgb": mape_xgb, "mape_naive": mape_naive,
            "xgb_version": xgb_version,
            "window_days": REWEIGHT_WINDOW_DAYS,
            "computed_at": __import__("datetime").date.today().isoformat(),
        }, f, ensure_ascii=False, indent=2)

    print(f"Trọng số mới: W_ARIMA={w_arima:.3f} (MAPE 30d={mape_arima:.2f}%) "
          f"W_XGB={w_xgb:.3f} (MAPE 30d={mape_xgb:.2f}%) "
          f"W_NAIVE={w_naive:.3f} (MAPE 30d={mape_naive:.2f}%)")
    print(f"Đã lưu: {WEIGHTS_PATH}")


def cmd_status():
    w_arima, w_xgb, w_naive = _load_weights()
    reweighted = os.path.exists(WEIGHTS_PATH)
    print(f"Trọng số hiện tại: W_ARIMA={w_arima:.3f} W_XGB={w_xgb:.3f} W_NAIVE={w_naive:.3f} "
          f"({'adaptive (đã --reweight)' if reweighted else 'tĩnh mặc định — chưa --reweight lần nào'})")

    conn = _get_conn()
    xgb_version = _latest_xgb_version(conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT np.model_version,
                   ROUND(AVG(ABS(pa.error_pct))::numeric, 2) AS mape,
                   COUNT(*) AS n
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            WHERE np.model_version IN ('arima-v1', %s, %s, 'ensemble-v1')
            GROUP BY np.model_version
            ORDER BY mape
        """, (xgb_version, NAIVE_VERSION))
        rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"Chưa có dữ liệu chấm điểm cho arima-v1/{xgb_version}/{NAIVE_VERSION}/ensemble-v1.")
        return
    print("\nMAPE so sánh toàn thời gian (thấp hơn = tốt hơn):")
    for model_version, mape, n in rows:
        print(f"  {model_version}: MAPE={mape}% (n={n})")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _db_url():
        print("ERROR: DATABASE_URL chưa được set", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="T+2 Ensemble Forecast Engine (ARIMA + XGBoost + Naive)")
    parser.add_argument("--predict",  action="store_true", help="Ensemble dự báo T+2 cho tất cả quỹ")
    parser.add_argument("--reweight", action="store_true", help="T2-008: tính lại trọng số theo MAPE 30 ngày qua")
    parser.add_argument("--status",   action="store_true", help="So sánh MAPE ensemble vs 3 model con + trọng số hiện tại")
    parser.add_argument("--code",     type=str,             help="Chỉ xử lý 1 mã quỹ")
    args = parser.parse_args()

    if args.predict:
        cmd_predict(args.code)
    elif args.reweight:
        cmd_reweight()
    elif args.status:
        cmd_status()
    else:
        parser.print_help()
