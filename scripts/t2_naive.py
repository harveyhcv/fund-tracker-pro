#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t2_naive.py — T+2 NAV Forecast Engine (Naive/Persistence baseline)
T2-012

Backtest walk-forward (2026-07-14, xem BACKLOG.md) cho thấy: với NAV quỹ mở
ở khung T+2, dự báo "NAV không đổi" (persistence) đã đánh bại ARIMA(2,1,2)
ở TẤT CẢ 8 quỹ test (VD TCBF: naive MAPE=0.159% vs ARIMA=0.183%), và ARIMA
thỉnh thoảng "nổ" dự báo cực đoan (DCDS: MAPE=716%). Naive không cần model,
không cần train, gần như không bao giờ sai nặng — thêm vào ensemble làm
model thứ 3 để tự cân trọng số công bằng, thay vì chỉ tin ARIMA/XGBoost.

Modes:
  --predict           Dự báo T+2 cho tất cả quỹ có dữ liệu, lưu vào nav_predictions
  --predict --code X  Chỉ dự báo 1 quỹ
  --status            Thống kê MAPE hiện tại (model_metrics + prediction_actuals)

Yêu cầu:
  DATABASE_URL env var

Chạy hàng ngày (cron — cùng lúc ARIMA/XGBoost, trước ensemble):
  python3 scripts/t2_naive.py --predict
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from t2_arima import _db_url, _get_conn, _fetch_nav_series, _next_trading_date  # noqa: E402

MODEL_VERSION = "naive-v1"
PREDICT_STEPS = 2

# CI naive không có sẵn từ model — dùng biên độ % cố định dựa trên biến động
# NAV quỹ mở điển hình (đa số <1%/2 phiên, xem backtest) để hiển thị UI không
# bị trống, KHÔNG dùng để tính toán gì khác.
FALLBACK_CI_PCT = 1.0


def cmd_predict(only_code: str = None):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db
    if not db.is_available():
        db.init_pool()  # save_prediction() dùng db.get_conn() (pooled) — cần init trước

    conn = _get_conn()
    with conn.cursor() as cur:
        if only_code:
            cur.execute("SELECT DISTINCT fund_code FROM nav_history WHERE fund_code = %s", (only_code.upper(),))
        else:
            cur.execute("SELECT DISTINCT fund_code FROM nav_history ORDER BY fund_code")
        codes = [r[0] for r in cur.fetchall()]

    print(f"Dự báo T+2 (Naive/Persistence) cho {len(codes)} quỹ...")
    ok = skipped = errors = 0

    for code in codes:
        series = _fetch_nav_series(conn, code, limit=2)  # chỉ cần điểm gần nhất
        if not series:
            skipped += 1
            continue

        last_date, last_nav = series[-1]
        t2_date = _next_trading_date(last_date, steps=PREDICT_STEPS)
        ci_lo = last_nav * (1 - FALLBACK_CI_PCT / 100)
        ci_hi = last_nav * (1 + FALLBACK_CI_PCT / 100)

        try:
            pred_id = db.save_prediction(
                fund_code          = code,
                predicted_for_date = t2_date,
                predicted_nav      = last_nav,
                model_version       = MODEL_VERSION,
                ci_low              = ci_lo,
                ci_high             = ci_hi,
            )
            print(f"  {code}: T+2={t2_date} nav={last_nav:.4f} (persistence) id={pred_id}")
            ok += 1
        except Exception as e:
            print(f"  {code}: DB error: {e}", file=sys.stderr)
            errors += 1

    conn.close()
    print(f"\nDự báo xong: {ok} OK, {skipped} skip (thiếu dữ liệu), {errors} lỗi")


def cmd_status():
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ROUND(AVG(ABS(pa.error_pct))::numeric, 3) AS mape, COUNT(*) AS n
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            WHERE np.model_version = %s
        """, (MODEL_VERSION,))
        row = cur.fetchone()
    conn.close()
    if row and row[0] is not None:
        print(f"Naive/Persistence ({MODEL_VERSION}) — MAPE live: {row[0]}% (n={row[1]})")
    else:
        print(f"Chưa có dữ liệu chấm điểm cho {MODEL_VERSION}.")


if __name__ == "__main__":
    if not _db_url():
        print("ERROR: DATABASE_URL chưa được set", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="T+2 Naive/Persistence Forecast Engine")
    parser.add_argument("--predict", action="store_true", help="Dự báo T+2 cho tất cả quỹ")
    parser.add_argument("--status",  action="store_true", help="Thống kê MAPE naive-v1")
    parser.add_argument("--code",    type=str,            help="Chỉ xử lý 1 mã quỹ")
    args = parser.parse_args()

    if args.predict:
        cmd_predict(only_code=args.code)
    elif args.status:
        cmd_status()
    else:
        parser.print_help()
