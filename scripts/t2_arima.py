#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t2_arima.py — T+2 NAV Forecast Engine (ARIMA baseline)
T2-002 + T2-003

Modes:
  --predict           Dự báo T+2 cho tất cả quỹ có đủ dữ liệu, lưu vào nav_predictions
  --predict --code X  Chỉ dự báo 1 quỹ
  --score             Chấm điểm các dự báo có predicted_for_date = hôm nay (T2-006)
  --status            Thống kê bảng nav_predictions + MAPE hiện tại

Yêu cầu:
  pip install statsmodels psycopg2-binary
  DATABASE_URL env var

Chạy hàng ngày (cron 18:31 — sau harvest_nav.py):
  python3 scripts/t2_arima.py --predict
  python3 scripts/t2_arima.py --score
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

# ── DB setup ─────────────────────────────────────────────────────────────────

def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        cfg_path = os.path.join(os.path.dirname(__file__), "../telegram-bot/config.json")
        try:
            with open(cfg_path) as f:
                url = json.load(f).get("database_url", "")
        except Exception:
            pass
    return url


def _get_conn():
    import psycopg2
    return psycopg2.connect(_db_url())


# ── Feature pipeline (T2-002) ─────────────────────────────────────────────────

MIN_HISTORY = 60   # Cần ít nhất 60 điểm NAV để fit ARIMA
PREDICT_STEPS = 2  # T+2 trading days


def _fetch_nav_series(conn, fund_code: str, limit: int = 500) -> list:
    """Lấy `limit` điểm NAV GẦN NHẤT (date, nav) từ nav_history, trả về sắp xếp
    tăng dần theo ngày để feature/lag tính đúng thứ tự thời gian.
    Ép nav về float — cột NUMERIC trong Postgres trả về decimal.Decimal qua
    psycopg2, gây lỗi "unsupported operand type" khi tính toán chung với
    float (numpy/xgboost) ở các bước sau (VD: t2_xgboost.py cmd_train).

    BUG cũ (2026-07-14): "ORDER BY nav_date ASC LIMIT %s" lấy `limit` điểm
    CŨ NHẤT chứ không phải gần nhất — với quỹ có >500 điểm lịch sử (VD:
    VCBFTBF, DCDS, TCGF...), series[-1] (điểm "mới nhất" theo code) thực ra
    là 1 ngày từ nhiều năm trước, khiến T+2 dự báo ra ngày trong quá khứ
    (đã thấy trực tiếp: T+2=2005-10-04, 2009-07-14...). Sửa: lấy DESC LIMIT
    (điểm mới nhất) trước, rồi đảo lại ASC."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT nav_date, nav FROM (
                SELECT nav_date, nav FROM nav_history
                WHERE fund_code = %s AND nav IS NOT NULL AND nav > 0
                ORDER BY nav_date DESC
                LIMIT %s
            ) recent
            ORDER BY nav_date ASC
        """, (fund_code.upper(), limit))
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def _next_trading_date(from_date: date, steps: int = 2) -> date:
    """T+N ngày giao dịch (bỏ qua T7/CN). Đơn giản — không tính nghỉ lễ."""
    d = from_date
    count = 0
    while count < steps:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0=T2, 4=T6
            count += 1
    return d


def _build_features(nav_series: list) -> dict:
    """T2-002: Feature dict từ NAV series.
    Trả: {nav_lag_1..5, chg_1d, chg_5d, chg_21d, vol_5d, vol_21d,
          day_of_week, days_to_month_end, days_to_quarter_end}
    """
    if len(nav_series) < 6:
        return {}
    prices = [r[1] for r in nav_series]
    last_date = nav_series[-1][0]

    def chg(i): return (prices[-1] - prices[i]) / prices[i] * 100 if prices[i] else 0
    def vol(w):
        if len(prices) < w + 1: return None
        rets = [(prices[-i] / prices[-i-1] - 1) * 100 for i in range(1, w+1)]
        import statistics
        return statistics.stdev(rets)

    last_dt = datetime(last_date.year, last_date.month, last_date.day)
    next_month_start = (last_dt.replace(day=1) + timedelta(days=32)).replace(day=1)
    next_q_month = ((last_dt.month - 1) // 3 + 1) * 3 + 1
    next_q_year = last_dt.year + (1 if next_q_month > 12 else 0)
    next_q_month = next_q_month if next_q_month <= 12 else next_q_month - 12
    next_q = datetime(next_q_year, next_q_month, 1)

    return {
        "nav_lag_1": prices[-1],
        "nav_lag_2": prices[-2],
        "nav_lag_3": prices[-3] if len(prices) >= 3 else None,
        "nav_lag_4": prices[-4] if len(prices) >= 4 else None,
        "nav_lag_5": prices[-5] if len(prices) >= 5 else None,
        "chg_1d": chg(-2),
        "chg_5d": chg(-6) if len(prices) >= 6 else None,
        "chg_21d": chg(-22) if len(prices) >= 22 else None,
        "vol_5d": vol(5),
        "vol_21d": vol(21),
        "day_of_week": last_date.weekday(),
        "days_to_month_end": (next_month_start.date() - last_date).days,
        "days_to_quarter_end": (next_q.date() - last_date).days,
    }


# ── ARIMA forecast (T2-003) ───────────────────────────────────────────────────

def _arima_predict(nav_series: list) -> dict:
    """Dự báo T+2 bằng ARIMA(2,1,2). Trả {predicted_nav, ci_low, ci_high, model_version}."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        import warnings
        warnings.filterwarnings("ignore")
    except ImportError:
        print("  statsmodels chưa cài. Chạy: pip install statsmodels", file=sys.stderr)
        return {}

    prices = [r[1] for r in nav_series]
    if len(prices) < MIN_HISTORY:
        return {}

    try:
        model = ARIMA(prices, order=(2, 1, 2))
        fit = model.fit()
        forecast = fit.get_forecast(steps=PREDICT_STEPS)
        pred_mean = forecast.predicted_mean
        conf_int  = forecast.conf_int(alpha=0.2)  # 80% CI

        # ARIMA(prices,...) nhận plain list (không phải pandas Series có index
        # ngày) → statsmodels trả predicted_mean/conf_int là numpy.ndarray
        # thuần, không có .iloc (lỗi thấy trực tiếp khi chạy thật trên
        # production: "'numpy.ndarray' object has no attribute 'iloc'").
        t2_nav   = float(pred_mean[-1])
        t2_ci_lo = float(conf_int[-1, 0])
        t2_ci_hi = float(conf_int[-1, 1])

        # Sanity: dự báo không được cách giá cuối > 10%
        last_nav = prices[-1]
        if abs(t2_nav - last_nav) / last_nav > 0.10:
            # Clip về ±10% để tránh model explode
            direction = 1 if t2_nav > last_nav else -1
            t2_nav   = last_nav * (1 + direction * 0.05)
            t2_ci_lo = last_nav * 0.97
            t2_ci_hi = last_nav * 1.03

        return {
            "predicted_nav": t2_nav,
            "ci_low": t2_ci_lo,
            "ci_high": t2_ci_hi,
            "model_version": "arima-v1",
        }
    except Exception as e:
        print(f"  ARIMA fit error: {e}", file=sys.stderr)
        return {}


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_predict(only_code: str = None):
    """Dự báo T+2 cho tất cả quỹ (hoặc 1 quỹ nếu --code)."""
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

    print(f"Dự báo T+2 cho {len(codes)} quỹ...")
    ok = skipped = errors = 0

    for code in codes:
        series = _fetch_nav_series(conn, code)
        if len(series) < MIN_HISTORY:
            skipped += 1
            continue

        result = _arima_predict(series)
        if not result:
            errors += 1
            continue

        last_date = series[-1][0]
        t2_date   = _next_trading_date(last_date, steps=2)

        try:
            pred_id = db.save_prediction(
                fund_code        = code,
                predicted_for_date = t2_date,
                predicted_nav    = result["predicted_nav"],
                model_version    = result["model_version"],
                ci_low           = result.get("ci_low"),
                ci_high          = result.get("ci_high"),
            )
            print(f"  {code}: T+2={t2_date} nav={result['predicted_nav']:.4f} "
                  f"CI=[{result.get('ci_low',0):.4f}, {result.get('ci_high',0):.4f}] id={pred_id}")
            ok += 1
        except Exception as e:
            print(f"  {code}: DB error: {e}", file=sys.stderr)
            errors += 1

    conn.close()
    print(f"\nDự báo xong: {ok} OK, {skipped} skip (thiếu dữ liệu), {errors} lỗi")


def cmd_score():
    """T2-006: Chấm điểm dự báo cho ngày hôm nay."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db
    if not db.is_available():
        db.init_pool()

    today = date.today()
    print(f"Chấm điểm dự báo cho {today}...")
    results = db.score_predictions(today)

    if not results:
        print("Không có dự báo nào cần chấm điểm hôm nay (hoặc NAV chưa về).")
        return

    for r in results:
        direction = "↑" if r["error_pct"] > 0 else "↓"
        print(f"  {r['fund_code']} [{r['model_version']}]: "
              f"pred={r['predicted_nav']:.4f} actual={r['actual_nav']:.4f} "
              f"err={r['error_pct']:+.2f}% {direction}")

    mape = sum(abs(r["error_pct"]) for r in results) / len(results)
    print(f"\nMAPE ngày {today}: {mape:.2f}% ({len(results)} quỹ)")


def cmd_status():
    """Tổng quan nav_predictions + độ chính xác."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM nav_predictions")
        n_pred = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM prediction_actuals")
        n_actual = cur.fetchone()[0]
        cur.execute("""
            SELECT model_version,
                   ROUND(AVG(ABS(error_pct))::numeric, 2) AS mape,
                   COUNT(*) AS n
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            GROUP BY model_version
            ORDER BY mape
        """)
        metrics = cur.fetchall()
    conn.close()

    print(f"nav_predictions: {n_pred} rows")
    print(f"prediction_actuals: {n_actual} rows")
    if metrics:
        print("\nMAPE tổng hợp:")
        for row in metrics:
            print(f"  {row[0]}: MAPE={row[1]}% (n={row[2]})")
    else:
        print("Chưa có dữ liệu chấm điểm.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _db_url():
        print("ERROR: DATABASE_URL chưa được set", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="T+2 ARIMA Forecast Engine")
    parser.add_argument("--predict", action="store_true", help="Dự báo T+2 cho tất cả quỹ")
    parser.add_argument("--score",   action="store_true", help="Chấm điểm dự báo hôm nay")
    parser.add_argument("--status",  action="store_true", help="Thống kê predictions + MAPE")
    parser.add_argument("--code",    type=str,            help="Chỉ xử lý 1 mã quỹ")
    args = parser.parse_args()

    if args.predict:
        cmd_predict(args.code)
    elif args.score:
        cmd_score()
    elif args.status:
        cmd_status()
    else:
        parser.print_help()
