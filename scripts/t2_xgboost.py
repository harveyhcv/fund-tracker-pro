#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
t2_xgboost.py — T+2 NAV Forecast Engine (XGBoost)
T2-004

Pooled model qua tất cả quỹ (fund_code là 1 feature) — dùng chung feature
pipeline T2-002 với t2_arima.py (import lại `_build_features`/`_fetch_nav_series`
/`_next_trading_date` để tránh trùng logic). Target = % thay đổi NAV sau 2 phiên
(không dự báo NAV tuyệt đối trực tiếp) → ổn định hơn khi pool nhiều quỹ có NAV
khác thang đo.

Modes:
  --train              Train model trên toàn bộ nav_history, time-split 80/20
                        theo từng quỹ (không shuffle — tránh look-ahead bias),
                        in MAPE test-set, ghi vào model_metrics, lưu model vào
                        scripts/models/xgb_t2.json (+ meta json)
  --predict            Dự báo T+2 cho tất cả quỹ có đủ dữ liệu (cần model đã train)
  --predict --code X   Chỉ dự báo 1 quỹ
  --status             In MAPE gần nhất (model_metrics, model_version=xgb-v1)

Yêu cầu:
  pip install xgboost psycopg2-binary
  DATABASE_URL env var

Chạy hàng ngày (cron 18:31 — cùng lúc ARIMA, sau harvest_nav.py):
  python3 scripts/t2_xgboost.py --predict

Retrain định kỳ (T2-007 — Chủ nhật 02:00):
  python3 scripts/t2_xgboost.py --train
"""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from t2_arima import (  # noqa: E402
    _db_url, _get_conn, _fetch_nav_series, _next_trading_date, _build_features,
)


# GOV-007 (2026-07-14): model PHẢI nằm trong DATA_DIR (Railway volume /data —
# bền vững qua redeploy), KHÔNG được nằm trong scripts/models (nằm trong image
# container — bị xoá sạch mỗi lần deploy code mới). Đây là lý do model XGBoost
# chưa bao giờ tồn tại được quá 1 lần deploy trên production, khiến T+2 luôn
# rỗng dù job train chạy hàng tuần.
DATA_DIR   = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "telegram-bot"))
MODEL_DIR  = os.path.join(DATA_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "xgb_t2.json")
META_PATH  = os.path.join(MODEL_DIR, "xgb_t2_meta.json")

DEFAULT_MODEL_VERSION = "xgb-v1"   # dùng khi chưa từng train (model_metrics rỗng)
MIN_HISTORY   = 60   # khớp t2_arima — quỹ cần ≥60 điểm NAV để dự báo
MIN_TRAIN_LEN = 25   # điểm tối thiểu để bắt đầu build training rows cho 1 quỹ

FEATURE_KEYS = [
    "nav_lag_1", "nav_lag_2", "nav_lag_3", "nav_lag_4", "nav_lag_5",
    "chg_1d", "chg_5d", "chg_21d", "vol_5d", "vol_21d",
    "day_of_week", "days_to_month_end", "days_to_quarter_end",
    "fund_idx",
]


def _feature_vector(feats: dict, fund_idx: int) -> list:
    """Chuyển feature dict → vector theo FEATURE_KEYS, None → NaN (XGBoost tự xử lý missing)."""
    import math
    row = []
    for k in FEATURE_KEYS:
        if k == "fund_idx":
            row.append(float(fund_idx))
            continue
        v = feats.get(k)
        row.append(float(v) if v is not None else math.nan)
    return row


# ── Training set construction ──────────────────────────────────────────────

def _build_training_rows(conn, codes: list) -> tuple:
    """Trả (X: list[list[float]], y: list[float] % chg T+2, fund_of_row: list[str])."""
    X, y, fund_of_row = [], [], []
    fund_idx_map = {c: i for i, c in enumerate(sorted(codes))}

    for code in codes:
        series = _fetch_nav_series(conn, code)
        if len(series) < MIN_TRAIN_LEN + 2:
            continue
        for i in range(MIN_TRAIN_LEN - 1, len(series) - 2):
            hist = series[:i + 1]
            feats = _build_features(hist)
            if not feats:
                continue
            nav_now = series[i][1]
            nav_t2  = series[i + 2][1]
            if not nav_now:
                continue
            target_pct = (nav_t2 - nav_now) / nav_now * 100
            X.append(_feature_vector(feats, fund_idx_map[code]))
            y.append(target_pct)
            fund_of_row.append(code)

    return X, y, fund_of_row, fund_idx_map


def _time_split_8020(codes_of_row: list) -> tuple:
    """Chỉ số train/test theo time-split 80/20 PER-FUND (giữ thứ tự thời gian
    trong từng quỹ, gộp lại thành 1 tập train + 1 tập test)."""
    from collections import defaultdict
    idx_by_fund = defaultdict(list)
    for i, code in enumerate(codes_of_row):
        idx_by_fund[code].append(i)

    train_idx, test_idx = [], []
    for code, idxs in idx_by_fund.items():
        cut = max(1, int(len(idxs) * 0.8))
        train_idx.extend(idxs[:cut])
        test_idx.extend(idxs[cut:])
    return train_idx, test_idx


# ── Commands ──────────────────────────────────────────────────────────────

def _next_version(conn) -> str:
    """T2-007: tìm xgb-vN lớn nhất đã từng ghi model_metrics, trả về xgb-v{N+1}.
    Chưa train lần nào → DEFAULT_MODEL_VERSION (xgb-v1)."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT model_version FROM model_metrics WHERE model_version LIKE 'xgb-v%'")
        versions = [r[0] for r in cur.fetchall()]
    max_n = 0
    for v in versions:
        try:
            max_n = max(max_n, int(v[len("xgb-v"):]))
        except ValueError:
            continue
    return f"xgb-v{max_n + 1}" if max_n > 0 else DEFAULT_MODEL_VERSION


def cmd_train():
    import xgboost as xgb

    conn = _get_conn()
    model_version = _next_version(conn)
    print(f"Model version cho lần train này: {model_version}")
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fund_code FROM nav_history ORDER BY fund_code")
        codes = [r[0] for r in cur.fetchall()]

    print(f"Building training set từ {len(codes)} quỹ...")
    X, y, fund_of_row, fund_idx_map = _build_training_rows(conn, codes)
    print(f"  {len(X)} training rows")

    if len(X) < 100:
        print("ERROR: Không đủ dữ liệu để train (cần ≥100 rows).", file=sys.stderr)
        conn.close()
        sys.exit(1)

    train_idx, test_idx = _time_split_8020(fund_of_row)
    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_test  = [X[i] for i in test_idx]
    y_test  = [y[i] for i in test_idx]
    print(f"  train={len(X_train)} test={len(X_test)} (time-split 80/20 per-fund)")

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_KEYS, missing=float("nan"))
    dtest  = xgb.DMatrix(X_test,  label=y_test,  feature_names=FEATURE_KEYS, missing=float("nan"))

    params = {
        "objective": "reg:squarederror",
        "max_depth": 5,
        "eta": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "seed": 42,
    }
    evals_result = {}
    booster = xgb.train(
        params, dtrain, num_boost_round=500,
        evals=[(dtrain, "train"), (dtest, "test")],
        early_stopping_rounds=30, evals_result=evals_result, verbose_eval=False,
    )
    print(f"  best_iteration={booster.best_iteration} best_test_rmse={booster.best_score:.4f}")

    # MAPE trên test set — cần recover NAV thực (không phải % chg) để tính đúng nghĩa MAPE giá
    preds_pct = booster.predict(dtest, iteration_range=(0, booster.best_iteration + 1))
    nav_now_test = [X_test[i][0] for i in range(len(X_test))]  # nav_lag_1 = feature index 0
    abs_pct_errors = []
    for pred_pct, actual_pct in zip(preds_pct, y_test):
        # MAPE tính trên % thay đổi dự báo vs % thay đổi thực (cùng đơn vị, robust hơn NAV tuyệt đối)
        if actual_pct == 0:
            continue
        abs_pct_errors.append(abs((pred_pct - actual_pct) / (100 + actual_pct) * 100))
    mape = sum(abs_pct_errors) / len(abs_pct_errors) if abs_pct_errors else float("nan")
    print(f"  MAPE (test, price-equivalent) = {mape:.3f}% (n={len(abs_pct_errors)})")

    os.makedirs(MODEL_DIR, exist_ok=True)
    booster.save_model(MODEL_PATH)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "model_version": model_version,
            "feature_keys": FEATURE_KEYS,
            "fund_idx_map": fund_idx_map,
            "best_iteration": booster.best_iteration,
            "trained_at": date.today().isoformat(),
            "train_rows": len(X_train),
            "test_rows": len(X_test),
            "test_mape": float(mape),  # numpy.float32 (từ booster.predict) không JSON serializable
        }, f, ensure_ascii=False, indent=2)
    print(f"  Model saved: {MODEL_PATH}")
    print(f"  Meta saved:  {META_PATH}")

    # Ghi model_metrics để so sánh với ARIMA (T2-008 dùng cái này) — dùng lại
    # `conn` (raw psycopg2, mở từ _get_conn() ở đầu hàm) thay vì db.get_conn()
    # (cần init_pool() trước, script này không gọi nên luôn crash "DB pool
    # not initialised").
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db
    db._ensure_prediction_tables(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO model_metrics (model_version, fund_code, window_days, mape, sample_size) "
            "VALUES (%s, NULL, %s, %s, %s)",
            (model_version, 0, float(mape), len(abs_pct_errors)),  # psycopg2 không adapt được numpy.float32
        )
    conn.commit()
    conn.close()
    print(f"\nTrain xong ({model_version}). Chạy --predict để dự báo T+2 với model mới.")


def _load_model():
    if not (os.path.exists(MODEL_PATH) and os.path.exists(META_PATH)):
        print("ERROR: Chưa có model. Chạy --train trước.", file=sys.stderr)
        sys.exit(1)
    import xgboost as xgb
    booster = xgb.Booster()
    booster.load_model(MODEL_PATH)
    with open(META_PATH, encoding="utf-8") as f:
        meta = json.load(f)
    return booster, meta


def cmd_predict(only_code: str = None):
    import xgboost as xgb

    booster, meta = _load_model()
    fund_idx_map  = meta["fund_idx_map"]
    best_iter     = meta.get("best_iteration", 0)
    model_version = meta.get("model_version", DEFAULT_MODEL_VERSION)

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../telegram-bot"))
    import db

    conn = _get_conn()
    with conn.cursor() as cur:
        if only_code:
            cur.execute("SELECT DISTINCT fund_code FROM nav_history WHERE fund_code = %s", (only_code.upper(),))
        else:
            cur.execute("SELECT DISTINCT fund_code FROM nav_history ORDER BY fund_code")
        codes = [r[0] for r in cur.fetchall()]

    print(f"Dự báo T+2 (XGBoost) cho {len(codes)} quỹ...")
    ok = skipped = errors = 0

    for code in codes:
        series = _fetch_nav_series(conn, code)
        if len(series) < MIN_HISTORY:
            skipped += 1
            continue

        feats = _build_features(series)
        if not feats:
            skipped += 1
            continue

        fund_idx = fund_idx_map.get(code, -1)  # quỹ mới (chưa thấy lúc train) → -1
        row = _feature_vector(feats, fund_idx)
        dmat = xgb.DMatrix([row], feature_names=FEATURE_KEYS, missing=float("nan"))

        try:
            pred_pct = float(booster.predict(dmat, iteration_range=(0, best_iter + 1))[0])
        except Exception as e:
            print(f"  {code}: predict error: {e}", file=sys.stderr)
            errors += 1
            continue

        last_nav = series[-1][1]
        t2_nav   = last_nav * (1 + pred_pct / 100)

        # Sanity clip ±10% — cùng ngưỡng với ARIMA (T2-003)
        if abs(t2_nav - last_nav) / last_nav > 0.10:
            direction = 1 if t2_nav > last_nav else -1
            t2_nav = last_nav * (1 + direction * 0.05)

        last_date = series[-1][0]
        t2_date   = _next_trading_date(last_date, steps=2)

        try:
            pred_id = db.save_prediction(
                fund_code           = code,
                predicted_for_date  = t2_date,
                predicted_nav       = t2_nav,
                model_version       = model_version,
            )
            print(f"  {code}: T+2={t2_date} nav={t2_nav:.4f} (pred_chg={pred_pct:+.3f}%) id={pred_id}")
            ok += 1
        except Exception as e:
            print(f"  {code}: DB error: {e}", file=sys.stderr)
            errors += 1

    conn.close()
    print(f"\nDự báo xong: {ok} OK, {skipped} skip (thiếu dữ liệu), {errors} lỗi")


def cmd_status():
    current_version = DEFAULT_MODEL_VERSION
    if os.path.exists(META_PATH):
        with open(META_PATH, encoding="utf-8") as f:
            meta = json.load(f)
        current_version = meta.get("model_version", DEFAULT_MODEL_VERSION)
        print(f"Model hiện tại (deployed): {current_version} — trained_at={meta.get('trained_at')} "
              f"train_rows={meta.get('train_rows')} test_mape={meta.get('test_mape'):.3f}%")
    else:
        print("Chưa có model đã train.")

    conn = _get_conn()
    with conn.cursor() as cur:
        # Lịch sử tất cả retrain (xgb-v1, xgb-v2, ...) — MAPE test-set lúc train
        cur.execute("""
            SELECT model_version, mape, sample_size, evaluated_at
            FROM model_metrics
            WHERE model_version LIKE 'xgb-v%'
            ORDER BY evaluated_at DESC
            LIMIT 20
        """)
        train_history = cur.fetchall()
        # MAPE live (đã chấm điểm thực tế) cho model đang deploy
        cur.execute("""
            SELECT ROUND(AVG(ABS(error_pct))::numeric, 2) AS mape, COUNT(*) AS n
            FROM prediction_actuals pa
            JOIN nav_predictions np ON np.id = pa.prediction_id
            WHERE np.model_version = %s
        """, (current_version,))
        row = cur.fetchone()
    conn.close()

    if train_history:
        print("\nLịch sử retrain (test MAPE lúc train):")
        for mv, mape, n, ts in train_history:
            print(f"  {mv}: MAPE={mape:.3f}% (n={n}) @ {ts}")

    if row and row[0] is not None:
        print(f"\nLive MAPE ({current_version}, từ prediction_actuals): {row[0]}% (n={row[1]})")
    else:
        print(f"\nChưa có dữ liệu chấm điểm live cho {current_version} "
              "(chạy scripts/t2_arima.py --score sau khi có actuals).")


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _db_url():
        print("ERROR: DATABASE_URL chưa được set", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="T+2 XGBoost Forecast Engine")
    parser.add_argument("--train",   action="store_true", help="Train model trên toàn bộ nav_history")
    parser.add_argument("--predict", action="store_true", help="Dự báo T+2 cho tất cả quỹ")
    parser.add_argument("--status",  action="store_true", help="Thống kê MAPE model xgb-v1")
    parser.add_argument("--code",    type=str,             help="Chỉ xử lý 1 mã quỹ (--predict)")
    args = parser.parse_args()

    if args.train:
        cmd_train()
    elif args.predict:
        cmd_predict(args.code)
    elif args.status:
        cmd_status()
    else:
        parser.print_help()
