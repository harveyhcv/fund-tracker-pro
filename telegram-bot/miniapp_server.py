#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
miniapp_server.py — HTTP server phục vụ Telegram Mini App + REST API

Port: PORT_MINIAPP env (mặc định 8443)
Endpoints:
  GET  /              → index.html (Mini App)
  GET  /api/me        → profile + portfolio của user (auth bằng telegram_id query param)
  GET  /api/signals   → tín hiệu kỹ thuật tất cả quỹ watched
  GET  /api/nav/<code>→ NAV history từ Railway DB
  POST /api/trade     → thêm giao dịch mua/bán vào config.json
  GET  /api/dca       → DCA calculator result cho user
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse as _uparse
from datetime import date, datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("miniapp")

ROOT      = Path(__file__).parent.parent
DATA_DIR  = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
CFG_FILE  = DATA_DIR / "config.json"
HTML_FILE     = Path(__file__).parent / "miniapp" / "index.html"
HTML_FILE_PNL = Path(__file__).parent / "miniapp" / "admin_pnl.html"
HTML_FILE_WEB = Path(__file__).parent / "miniapp" / "web.html"

# Trang /admin/pnl mở trực tiếp qua trình duyệt (không phải trong Telegram Mini
# App) nên không có X-Init-Data để xác thực như các endpoint khác — dùng token
# bí mật riêng, Harvey tự đặt trên Railway (ADMIN_WEB_TOKEN) và giữ kín trong URL
# đã bookmark. Không set biến này = endpoint từ chối tất cả (an toàn theo mặc định).
_ADMIN_WEB_TOKEN = os.environ.get("ADMIN_WEB_TOKEN", "")

# Lấy từ RAILWAY_GIT_COMMIT_SHA (Railway tự inject mỗi lần deploy) thay vì
# hardcode tay — trước đây có 2 chuỗi version tách biệt (1 ở đây, 1 trong
# APP_VERSION của index.html) phải bump tay đồng bộ, dẫn tới lệch bản thật
# (badge hiện v1.3 dù code đã qua nhiều lần deploy). Giờ GET /api/version là
# nguồn version DUY NHẤT, luôn khớp commit đang thực sự chạy — frontend fetch
# giá trị này thay vì tự giữ 1 chuỗi riêng.
_SERVER_VERSION = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev")[:7]

# Railway inject PORT; fallback PORT_MINIAPP cho local dev
PORT_MINIAPP = int(os.environ.get("PORT_MINIAPP") or os.environ.get("PORT") or 8443)

# Freemium gate (GATE-003): free tier tối đa 2 mã theo dõi
FREE_FUND_LIMIT = 2

# PAY-004/005: MoMo payment v2. Test/sandbox credentials mặc định theo tài liệu
# công khai của MoMo (https://developers.momo.vn) — override bằng ENV khi có
# merchant thật (đăng ký tại business.momo.vn).
_MOMO_ENDPOINT     = os.environ.get("MOMO_ENDPOINT", "https://test-payment.momo.vn/v2/gateway/api/create")
_MOMO_PARTNER_CODE = os.environ.get("MOMO_PARTNER_CODE", "MOMO")
_MOMO_ACCESS_KEY   = os.environ.get("MOMO_ACCESS_KEY", "F8BBA842ECF85")
_MOMO_SECRET_KEY   = os.environ.get("MOMO_SECRET_KEY", "K951B6PE1waDMi640xX08PD3vg6EkVlz")

# PAY-009: SePay VietQR — chuyển khoản ngân hàng cá nhân (không cần merchant
# license), SePay bắn webhook khi tiền về khớp nội dung chuyển khoản.
# Đã xác nhận trực tiếp với tài khoản SePay thật (2026-07-15, đọc từ trang
# "Hướng dẫn xác thực trên server" trong dashboard SePay):
#   - Xác thực HMAC-SHA256 (an toàn hơn Apikey tĩnh — chống replay/giả mạo tốt
#     hơn vì chữ ký gắn với từng request, không phải 1 key cố định dùng mãi):
#     header X-SePay-Signature: "sha256=<hex hmac>", header X-SePay-Timestamp:
#     <unix seconds>, chuỗi được ký = "{timestamp}.{raw_body}".
#   - Field webhook payload (id/gateway/transferAmount/transferType/content):
#     CHƯA verify field-level với tài khoản thật, log payload thô để dễ chỉnh
#     nếu field không khớp thực tế.
_SEPAY_API_KEY        = os.environ.get("SEPAY_API_KEY", "")           # fallback: header Authorization: Apikey <key>
_SEPAY_HMAC_SECRET    = os.environ.get("SEPAY_HMAC_SECRET", "")       # Secret Key (whsec_...) — ưu tiên dùng nếu có
_SEPAY_HMAC_MAX_AGE_S = 300   # chống replay: từ chối nếu X-SePay-Timestamp cách hiện tại >5 phút
_SEPAY_ACCOUNT_NUMBER = os.environ.get("SEPAY_ACCOUNT_NUMBER", "")    # số tài khoản ngân hàng nhận tiền
_SEPAY_BANK_CODE      = os.environ.get("SEPAY_BANK_CODE", "")         # mã ngân hàng VietQR (vd MBBank, TPBank...)
_SEPAY_QR_BASE        = os.environ.get("SEPAY_QR_BASE", "https://qr.sepay.vn/img")

from pricing import PRO_PLANS, PLAN_ORDER, DEFAULT_PLAN, resolve_plan


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    try:
        return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cfg(cfg: dict) -> None:
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_default(o):
    """Fallback serializer cho json.dumps — datetime/date/Decimal từ Postgres
    (RealDictCursor trả kiểu Python thật, không tự thành JSON được) → str/float.
    Không có fallback này, bất kỳ endpoint nào lỡ trả nguyên datetime sẽ crash
    TOÀN BỘ request (không gửi được response nào) → client thấy lỗi 502."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    try:
        from decimal import Decimal
        if isinstance(o, Decimal):
            return float(o)
    except ImportError:
        pass
    return str(o)


def _json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _find_profile(cfg: dict, telegram_id: str):
    """Tìm profile theo telegram_id. Nguồn chính: bảng bot_profiles trên PostgreSQL
    (persistent qua redeploy) — cùng nguồn với bot.py. Fallback config.json nếu DB down."""
    if _db_mod is not None and _db_mod.is_available():
        try:
            p = _db_mod.find_profile(telegram_id)
            if p:
                return p
        except Exception as e:
            log.warning(f"[_find_profile] DB lỗi, fallback config.json: {e}")
    for p in cfg.get("profiles", []):
        if str(p.get("telegram_id", "")) == str(telegram_id):
            return p
    return None




# ── Gold helpers ──────────────────────────────────────────────────────────────

_GOLD_LABELS = {
    "SJC:SJC_1L":          "Vàng miếng SJC 1L",
    "DOJI:SJC_1L":         "SJC tại DOJI 1L",
    "DOJI:DOJI_NHAN":      "Nhẫn DOJI 999.9",
    "DOJI:DOJI_NHAN_9999": "Nhẫn DOJI 9999 24K",
    "INTERNATIONAL:XAU_USD": "Vàng QT (XAU/USD)",
    # VANGTODAYAPI (nguồn chính, fetch_gold.py) — trước đây thiếu các mã này nên
    # rơi vào fallback "{source} {product}" thô (vd "VANGTODAYAPI DOJI_NHAN_HCM"),
    # hiện nguyên trong dropdown chọn sản phẩm bán vàng (Harvey phát hiện 2026-07-16).
    "VANGTODAYAPI:SJC_1L":         "Vàng miếng SJC 9999 — 1L",
    "VANGTODAYAPI:DOJI_NHAN_9999": "Nhẫn tròn DOJI 9999 (HN)",
    "VANGTODAYAPI:DOJI_NHAN_HCM":  "Nhẫn tròn DOJI 9999 (HCM)",
    "VANGTODAYAPI:DOJI_JEWELRY":   "DOJI Jewelry",
    "VANGTODAYAPI:SJC_NHAN":       "Nhẫn tròn SJC 9999",
    "VANGTODAYAPI:PNJ_HN":         "PNJ Hà Nội",
    "VANGTODAYAPI:PNJ_24K":        "Nhẫn 24K PNJ 9999",
    "VANGTODAYAPI:BAOTINNGUYEN":   "Vàng nhẫn Bảo Tín 9999",
    "VANGTODAYAPI:BAOTINSJC":      "Vàng SJC tại Bảo Tín",
    "VANGTODAYAPI:VNGOLD_SJC":     "Vàng SJC tại VN Gold",
    "VANGTODAYAPI:VIETTIN_SJC":    "Vàng SJC tại Việt Tín",
    "VANGTODAYAPI:XAUUSD":         "Vàng quốc tế XAU/USD",
}

def _gold_product_label(source: str, product: str) -> str:
    return _GOLD_LABELS.get(f"{source}:{product}", f"{source} {product}")


def _gold_label_for_product(product: str) -> str:
    """Tên hiển thị chỉ theo product (không biết source) — dùng khi sản phẩm
    chưa có giá hôm nay (price_entry=None) nên không xác định được nguồn. Tra
    ngược trong _GOLD_LABELS bất kỳ key nào khớp product, fallback về product thô."""
    for key, label in _GOLD_LABELS.items():
        if key.split(":", 1)[-1] == product:
            return label
    return product


def _unit_to_luong(unit: str) -> float:
    """Quy đổi đơn vị về lượng. 1 lượng = 10 chỉ = 37.5g."""
    return {"luong": 1.0, "chi": 0.1, "gram": 1.0 / 37.5}.get(unit, 1.0)


def _calc_gold_signals(db_url: str) -> dict:
    """Tính chỉ số kỹ thuật cho giá SJC — RSI/BB/MA/score (thang điểm riêng cho vàng)
    cộng thêm bộ chỉ số mở rộng dùng chung với CCQ (Stochastic, CCI, ROC, Golden/Death
    Cross, Sharpe, Sortino, Volatility, Max Drawdown) bằng cách tái dùng calc_signal()
    của bot.py trên chuỗi giá vàng — cùng công thức, không viết lại logic riêng.

    Dùng product='SJC_1L' từ MỌI nguồn (không khoá cứng source='SJC' — nguồn đó
    (webgia.com) đã ngừng cập nhật). Khi nhiều nguồn có cùng ngày, ưu tiên
    VANGTODAYAPI/DOJI_SCRAPE (đang chạy hàng ngày) hơn SJC/GIAVANG_ORG (cũ, tĩnh).
    """
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=6)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (price_date) price_date::text, sell_price::float
                FROM gold_prices
                WHERE product = 'SJC_1L'
                ORDER BY price_date DESC,
                         CASE source
                             WHEN 'VANGTODAYAPI' THEN 2
                             WHEN 'DOJI_SCRAPE'  THEN 2
                             WHEN 'SJC'          THEN 1
                             ELSE 0
                         END DESC
                LIMIT 300
            """)
            rows = cur.fetchall()
        conn.close()
        if len(rows) < 10:
            return {}
        rows = list(reversed(rows))  # DB trả DESC theo ngày, đảo lại thành ASC để tính RSI
        dates  = [r[0] for r in rows]
        prices = [r[1] for r in rows]
        # RSI(14)
        rsi = _gold_rsi(prices)
        # MA20, MA50
        ma20 = sum(prices[-20:]) / min(len(prices), 20)
        ma50 = sum(prices[-50:]) / min(len(prices), 50) if len(prices) >= 20 else None
        cur_price = prices[-1]
        prev_price = prices[-2] if len(prices) >= 2 else cur_price
        chg_pct = (cur_price - prev_price) / prev_price * 100 if prev_price else 0
        # BB(20)
        window = prices[-20:] if len(prices) >= 20 else prices
        mean   = sum(window) / len(window)
        std    = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5
        bb_pct = (cur_price - (mean - 2 * std)) / (4 * std) * 100 if std else 50
        # Signal score (thang điểm riêng cho vàng — không dùng chung score CCQ)
        score = 0
        if rsi is not None:
            if rsi < 33:   score += 2
            elif rsi < 48: score += 1
            elif rsi > 70: score -= 2
        if bb_pct < 25:    score += 1
        elif bb_pct > 75:  score -= 1
        if ma50 and cur_price > ma50: score += 1
        if score >= 3:      sig = "MUA 🟢"
        elif score >= 1:    sig = "TÍCH LŨY 🟡"
        elif score <= -2:   sig = "THẬN TRỌNG 🔴"
        else:               sig = "HOLD ⚪"

        # Chỉ số mở rộng — tái dùng calc_signal() (Stochastic, CCI, ROC, Golden/Death
        # Cross, Sharpe, Sortino, Volatility, Max Drawdown). Cần >=60 điểm giá.
        extended = {}
        if _BOT_IMPORTED and len(prices) >= 60:
            try:
                pts = [{"date": d_, "nav": p} for d_, p in zip(dates, prices)]
                live = _calc_signal_bot("GOLD_SJC", pts)
                extended = {
                    "stoch_k":    live.get("stoch_k"),
                    "stoch_d":    live.get("stoch_d"),
                    "cci":        live.get("cci"),
                    "roc":        live.get("roc"),
                    "gc_type":    live.get("gc_type"),
                    "sharpe":     live.get("sharpe"),
                    "sortino":    live.get("sortino"),
                    "volatility": live.get("volatility"),
                    "max_dd":     live.get("max_dd"),
                }
            except Exception as e:
                log.debug(f"[gold_signals] extended indicators: {e}")

        return {
            "signal": sig, "score": score,
            "rsi": round(rsi, 1) if rsi else None,
            "bb_pct": round(bb_pct, 1),
            "ma20": round(ma20, 0),
            "ma50": round(ma50, 0) if ma50 else None,
            "price": cur_price,
            "chg_pct": round(chg_pct, 2),
            "date": dates[-1],
            "n_points": len(prices),
            **extended,
        }
    except Exception as e:
        return {"error": str(e)}


def _gold_rsi(prices: list, period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(d, 0) for d in deltas[-period:]]
    losses = [max(-d, 0) for d in deltas[-period:]]
    avg_g  = sum(gains) / period
    avg_l  = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


_GOLD_PRICE_SRC_PRIORITY = {"VANGTODAYAPI": 2, "DOJI_SCRAPE": 2, "SJC": 1, "GIAVANG_ORG": 0}

# Sản phẩm KHÔNG có feed giá riêng (scripts/fetch_gold.py chưa từng scrape) — dùng giá
# của sản phẩm tương đương gần nhất để không hiện -100% giả do thiếu dữ liệu. Nếu sau
# này có feed riêng cho các mã này, xoá alias tương ứng để dùng giá thật.
_GOLD_PRODUCT_ALIAS = {
    "DOJI_NHAN_HCM": "DOJI_NHAN_9999",  # DOJI công bố 1 giá nhẫn 999.9 toàn quốc
}


def _best_price_for_product(prices: dict, product: str) -> dict | None:
    """Chọn giá mới nhất cho 1 product cụ thể, ưu tiên nguồn đang chạy hàng ngày khi hoà ngày.
    Nếu product không có feed riêng, fallback sang alias (_GOLD_PRODUCT_ALIAS)."""
    candidates = [v for v in prices.values() if v.get("product") == product]
    if not candidates and product in _GOLD_PRODUCT_ALIAS:
        candidates = [v for v in prices.values() if v.get("product") == _GOLD_PRODUCT_ALIAS[product]]
    if not candidates:
        return None
    return max(candidates, key=lambda v: (v.get("date", ""), _GOLD_PRICE_SRC_PRIORITY.get(v.get("source"), 0)))


def _calc_gold_portfolio(cfg: dict, tg_id: str, prices: dict) -> dict:
    """Tính portfolio vàng THEO TỪNG LOẠI VÀNG (product) riêng biệt — không gộp chung
    SJC miếng với nhẫn trơn hay vàng quốc tế vì giá mỗi loại khác nhau.
    Giá vốn (lúc mua) đã chốt sẵn trong total_vnd của từng giao dịch (dùng giá BÁN
    của tiệm tại thời điểm mua). Giá trị hiện tại dùng giá MUA của tiệm hôm nay
    (giá mà user sẽ nhận được nếu bán ra — không dùng giá bán vì đó là giá tiệm
    bán RA cho khách, không phải giá tiệm trả lại cho khách)."""
    by_product: dict[str, dict] = {}
    # "OTHER" (Vàng khác) gộp chung 1 khối để tính số lượng/giá vốn, nhưng vẫn giữ
    # riêng theo TÊN user tự đặt (note) — chỉ để hiển thị breakdown tham khảo
    # trong dropdown UI, không ảnh hưởng tới cách tính tổng.
    other_by_name: dict[str, dict] = {}
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT product, type, qty_luong, total_vnd, note FROM user_gold_trades "
                "WHERE telegram_id=%s ORDER BY trade_date, id",
                [tg_id]
            )
            rows = cur.fetchall()
        conn.close()
    except Exception as _e:
        log.warning(f"[gold_portfolio] DB error: {_e}")
        rows = []
    for (product, tx_type, qty_luong, total_vnd, note) in rows:
        agg = by_product.setdefault(product, {"luong": 0.0, "cost": 0.0})
        ql = float(qty_luong or 0)
        tv = float(total_vnd or 0)
        if tx_type == "buy":
            agg["luong"] += ql
            agg["cost"]  += tv
        elif tx_type == "sell":
            frac = ql / agg["luong"] if agg["luong"] > 0 else 0
            agg["cost"]  -= agg["cost"] * frac
            agg["luong"] -= ql
        if product == "OTHER":
            name = (note or "").strip() or "Vàng khác"
            sub = other_by_name.setdefault(name, {"luong": 0.0, "cost": 0.0})
            if tx_type == "buy":
                sub["luong"] += ql
                sub["cost"]  += tv
            elif tx_type == "sell":
                sfrac = ql / sub["luong"] if sub["luong"] > 0 else 0
                sub["cost"]  -= sub["cost"] * sfrac
                sub["luong"] -= ql

    breakdown = {}
    missing_price_products = []
    total_luong = total_cost = total_value = 0.0
    for product, agg in by_product.items():
        luong, cost = agg["luong"], agg["cost"]
        if luong < 0.001:
            continue
        price_entry = _best_price_for_product(prices, product)
        if price_entry is None:
            # Không có dữ liệu giá (kể cả alias) — KHÔNG hiện -100% giả. Vẫn tính vào
            # tổng vốn để "tổng vốn" đúng, nhưng loại khỏi tổng giá trị/lãi lỗ vì
            # không xác định được — tránh gây hiểu lầm đã mất trắng.
            breakdown[product] = {
                "label":          "Vàng khác" if product == "OTHER" else _gold_label_for_product(product),
                "luong":          round(luong, 4),
                "avg_cost":       round(cost / luong, 0) if luong else 0,
                "cost":           round(cost, 0),
                "price_missing":  True,
            }
            if product == "OTHER":
                sub_items = [
                    {"name": name, "luong": round(v["luong"], 4)}
                    for name, v in other_by_name.items() if v["luong"] > 0.001
                ]
                # Chỉ tách breakdown theo tên khi user THỰC SỰ có đặt tên riêng —
                # nếu toàn bộ đều là bucket mặc định "Vàng khác" thì không cần tách
                # (dùng cho dropdown Bán — mỗi tên riêng là 1 lựa chọn, phần KHÔNG đặt
                # tên gộp vào "Vàng khác còn lại" để phân biệt với các tên riêng khác).
                if any(s["name"] != "Vàng khác" for s in sub_items):
                    for s in sub_items:
                        if s["name"] == "Vàng khác":
                            s["name"] = "Vàng khác còn lại"
                    breakdown[product]["sub_items"] = sub_items
            missing_price_products.append(product)
            total_cost += cost
            continue
        cur_buy = price_entry["buy"]
        value = luong * cur_buy
        pnl = value - cost
        breakdown[product] = {
            "label":         price_entry["label"],
            "luong":         round(luong, 4),
            "avg_cost":      round(cost / luong, 0) if luong else 0,
            "current_price": cur_buy,
            "current_value": round(value, 0),
            "cost":          round(cost, 0),
            "pnl":           round(pnl, 0),
            "pnl_pct":       round(pnl / cost * 100, 2) if cost else 0,
        }
        total_luong += luong
        total_cost  += cost
        total_value += value

    if total_luong < 0.001 and not missing_price_products:
        return {"total_luong": 0.0, "avg_cost": 0, "current_value": 0, "pnl": 0, "pnl_pct": 0, "by_product": {}}
    pnl_total = total_value - total_cost
    priced_cost = total_cost - sum(breakdown[p]["cost"] for p in missing_price_products)
    return {
        "total_luong":    round(total_luong, 4),
        "avg_cost":       round(priced_cost / total_luong, 0) if total_luong else 0,
        "current_value":  round(total_value, 0),
        "total_cost":     round(total_cost, 0),
        "pnl":            round(pnl_total, 0),
        "pnl_pct":        round(pnl_total / priced_cost * 100, 2) if priced_cost else 0,
        "missing_price_products": missing_price_products,
        "by_product":     breakdown,
    }


# Import calc_signal + get_nav_series từ bot.py để dùng cùng logic tính tín hiệu
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from bot import (
        calc_signal as _calc_signal_bot,
        get_nav_series as _get_nav_series_bot,
        job_check_signals as _job_check_signals_bot,
        FUND_CATALOG as _FUND_CATALOG,
    )
    import db as _db_mod
    _db_mod.init_pool()
    _BOT_IMPORTED = True
except Exception as _e:
    log.warning(f"[miniapp] Không import được bot.py: {_e}")
    _db_mod = None
    _BOT_IMPORTED = False


_STRENGTH_TO_SIGNAL = {
    "strong_buy":    "MUA MẠNH 🟢🟢",
    "buy":           "MUA 🟢",
    "hold":          "HOLD ⚪",
    "reduce":        "BÁN 🔴",
    "strong_reduce": "BÁN MẠNH 🔴🔴",
}


def _row_to_signal(row) -> dict:
    import json as _json
    (code, strength, score, rsi, bb_pct, macd_hist,
     nav, signal_date, chg_pct, chg7d, chg30d, details_raw, nav_date,
     ma20, ma50) = row
    details = details_raw if isinstance(details_raw, list) else (
        _json.loads(details_raw) if details_raw else []
    )
    return {
        "signal":    _STRENGTH_TO_SIGNAL.get(strength, "HOLD ⚪"),
        "score":     score or 0,
        "nav":       float(nav or 0),
        "nav_date":  nav_date or signal_date or "",
        "rsi":       float(rsi) if rsi is not None else None,
        "bb_pct":    float(bb_pct) if bb_pct is not None else None,
        "macd_hist": float(macd_hist) if macd_hist is not None else None,
        "chg_pct":   float(chg_pct or 0),
        "chg7":      float(chg7d) if chg7d is not None else None,
        "chg30":     float(chg30d) if chg30d is not None else None,
        "details":   details,
        "ma20":      float(ma20) if ma20 is not None else None,
        "ma50":      float(ma50) if ma50 is not None else None,
    }

def _get_nav_confidence_map(codes: list) -> dict:
    """
    Trả {fund_code: {source, pending_nav}} cho NAV mới nhất của từng quỹ.
    Dùng để hiển thị confidence badge trong UI.
    """
    if not codes or _db_mod is None or not _db_mod.is_available():
        return {}
    try:
        ph = ",".join(["%s"] * len(codes))
        with _db_mod.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT DISTINCT ON (fund_code)
                        fund_code, source, pending_nav, nav_date::text
                    FROM nav_history
                    WHERE fund_code IN ({ph})
                    ORDER BY fund_code, nav_date DESC
                """, codes)
                return {
                    r[0]: {"nav_source": r[1], "pending_nav": float(r[2]) if r[2] else None, "nav_date": r[3]}
                    for r in cur.fetchall()
                }
    except Exception as e:
        log.debug(f"[nav_confidence_map] {e}")
        return {}


_SIGNAL_SELECT = """
    SELECT DISTINCT ON (fund_code)
        fund_code, strength, score,
        rsi, bb_pct, macd_hist,
        nav_at_signal, signal_date::text,
        chg_pct, chg7d, chg30d, details,
        nav_date::text, ma20, ma50
    FROM buy_signals
    WHERE fund_code IN ({ph})
    ORDER BY fund_code, signal_date DESC
"""


def _trigger_t2_repredict(codes: list):
    """T2-013 (2026-07-15): NAV vừa được admin sửa/cập nhật/import lại (fetch-nav,
    nav/confirm, import-nav) — mọi dự báo T+2 đã có cho quỹ đó (ARIMA/XGBoost/
    Ensemble) giờ dựa trên NAV SAI, phải tính lại NGAY thay vì chờ tới job hàng
    ngày 18:31. Bug thật đã xảy ra: sửa xong NAV VCBFTBF nhưng T+2 vẫn hiện giá
    trị cũ tính từ lịch sử sai trước đó, khiến user hoang mang tưởng NAV vẫn sai.

    Chạy nền (thread riêng, không chặn response API) — mỗi model con trước,
    ensemble sau cùng (cần cả 3 dự báo con của cùng ngày đã ghi DB)."""
    codes = sorted(set(c.upper() for c in codes if c))
    if not codes:
        return

    def _run():
        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        for code in codes:
            for script in ("t2_arima.py", "t2_xgboost.py", "t2_naive.py"):
                try:
                    subprocess.run(
                        [sys.executable, os.path.join(scripts_dir, script), "--predict", "--code", code],
                        capture_output=True, text=True, timeout=60,
                        env={**os.environ},
                    )
                except Exception as ex:
                    log.warning(f"[t2-repredict] {script} {code}: {ex}")
            try:
                subprocess.run(
                    [sys.executable, os.path.join(scripts_dir, "t2_ensemble.py"), "--predict", "--code", code],
                    capture_output=True, text=True, timeout=60,
                    env={**os.environ},
                )
            except Exception as ex:
                log.warning(f"[t2-repredict] ensemble {code}: {ex}")
        log.info(f"[t2-repredict] xong cho {len(codes)} quỹ: {codes}")

    threading.Thread(target=_run, daemon=True, name="t2-repredict").start()


def _compute_from_nav_history(codes: list, cfg: dict, telegram_id: str = None):
    """Tính signal từ nav_history DB.
    Nếu telegram_id (Pro user): merge thêm pending nav_drafts của họ vào series.
    Không gọi API ngoài — DB là nguồn duy nhất."""
    if not _BOT_IMPORTED or not codes:
        return
    db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
    if not db_url:
        return
    from datetime import date as _date
    today = _date.today()
    strength_map = {
        "MUA MẠNH": "strong_buy", "MUA": "buy",
        "BÁN MẠNH": "strong_reduce", "BÁN": "reduce",
    }
    # Load pending drafts của user (nếu có) để merge vào series
    user_drafts: dict[str, dict] = {}  # {fund_code: {nav_date_str: nav}}
    if telegram_id and _db_mod and _db_mod.is_available():
        try:
            for d in _db_mod.get_nav_drafts(telegram_id, codes):
                user_drafts.setdefault(d["fund_code"], {})[d["nav_date"]] = d["nav"]
        except Exception as e:
            log.warning(f"[compute-from-db] load drafts: {e}")

    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=8)
    except Exception as e:
        log.warning(f"[compute-from-db] DB connect failed: {e}")
        return

    for code in codes:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT nav_date::text, nav::float FROM nav_history "
                    "WHERE fund_code=%s ORDER BY nav_date",
                    (code,)
                )
                rows = cur.fetchall()
            # Merge draft points: draft ghi đè nav_history cùng ngày, hoặc thêm ngày mới
            pts_map = {r[0]: r[1] for r in rows}
            for draft_date, draft_nav in user_drafts.get(code, {}).items():
                pts_map[draft_date] = draft_nav
            pts = [{"date": d, "nav": v} for d, v in sorted(pts_map.items())]
            if not pts:
                log.warning(f"[compute-from-db] {code}: không có data trong nav_history")
                continue
            d = _calc_signal_bot(code, pts)
            sig = d.get("signal", "")
            strength = next((v for k, v in strength_map.items() if k in sig), "hold")
            fund_cfg = _FUND_CATALOG.get(code, cfg.get("funds", {}).get(code, {}))
            settle = fund_cfg.get("settlement", "T2")
            if _db_mod and _db_mod.is_available():
                _db_mod.save_signal(
                    fund_code=code,
                    signal_date=today,
                    strength=strength,
                    score=d.get("score", 0),
                    nav_at_signal=d.get("nav", 0),
                    indicators={
                        "rsi":          d.get("rsi"),
                        "bb_pct":       d.get("bb_pct"),
                        "macd_hist":    d.get("macd_hist"),
                        "ma20_vs_ma50": (d.get("ma20") or 0) > (d.get("ma50") or 0),
                        "ma20":         d.get("ma20"),
                        "ma50":         d.get("ma50"),
                        "momentum_30d": d.get("chg30"),
                        "chg_pct":      d.get("chg_pct"),
                        "chg7d":        d.get("chg7"),
                        "chg30d":       d.get("chg30"),
                        "details":      d.get("details", []),
                        "nav_date":     d.get("nav_date"),
                    },
                    settlement_rule=settle,
                )
                log.info(f"[compute-from-db] {code}: signal={sig}, nav_date={d.get('nav_date')}")
        except Exception as e:
            log.warning(f"[compute-from-db] {code}: {e}")
    conn.close()





def _get_signals_for_codes(codes: list, cfg: dict, background_compute: bool = True) -> dict:
    """Đọc tín hiệu từ buy_signals.
    background_compute=True (default): stale/missing → trigger tính ngầm, trả về ngay cached.
    background_compute=False: block cho đến khi tính xong (chỉ dùng từ /api/signals tab).
    """
    results = {}
    if not codes:
        return results
    db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
    if not db_url:
        return results

    def _query(cur, code_list):
        ph = ",".join(["%s"] * len(code_list))
        cur.execute(_SIGNAL_SELECT.format(ph=ph), code_list)
        return cur.fetchall()

    try:
        if _db_mod is not None and _db_mod.is_available():
            with _db_mod.get_conn() as conn:
                with conn.cursor() as cur:
                    rows = _query(cur, codes)
        else:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                rows = _query(cur, codes)
            conn.close()
    except Exception as e:
        log.warning(f"[miniapp] _get_signals_for_codes DB: {e}")
        return results

    today_str = datetime.now().strftime("%Y-%m-%d")
    stale = []
    for row in rows:
        results[row[0]] = _row_to_signal(row)
        signal_date = row[7] or ""   # signal_date::text, index 7
        nav_date    = row[12] or ""  # nav_date::text, index 12
        # GOV-011 (2026-07-15): trước đây chỉ so signal_date — nhưng
        # _compute_from_nav_history() luôn ghi signal_date=hôm nay bất kể nav_date
        # dùng để tính là ngày nào, nên 1 lần tính ra nav_date=hôm qua (nguồn
        # chưa publish) sẽ bị coi là "fresh" CẢ NGÀY dù sau đó nav_history đã có
        # NAV mới hơn (SSISCA: tính lúc sáng ra 14/7, sau đó harvest ghi thêm
        # 15/7 nhưng cache không bao giờ refresh lại vì signal_date đã = hôm nay).
        # Phải so cả nav_date — cache re-tính (rẻ, chỉ đọc nav_history, không gọi
        # API ngoài) mỗi khi nav_date cũ hơn hôm nay, để luôn bắt kịp NAV mới nhất.
        if signal_date < today_str or nav_date < today_str:
            stale.append(row[0])

    missing = [c for c in codes if c not in results] + stale
    if missing:
        if background_compute:
            # Trả về ngay với cached data; tính ngầm trong background thread
            threading.Thread(
                target=_compute_from_nav_history,
                args=(missing, cfg),
                daemon=True,
                name="compute-signals-bg",
            ).start()
            log.info(f"[signals] background compute triggered for {len(missing)} codes")
        else:
            # Block: đợi tính xong rồi đọc lại (chỉ dùng từ /api/signals)
            _compute_from_nav_history(missing, cfg)
            try:
                if _db_mod is not None and _db_mod.is_available():
                    with _db_mod.get_conn() as conn:
                        with conn.cursor() as cur:
                            rows2 = _query(cur, missing)
                else:
                    import psycopg2
                    conn = psycopg2.connect(db_url, connect_timeout=8)
                    with conn.cursor() as cur:
                        rows2 = _query(cur, missing)
                    conn.close()
                for row in rows2:
                    results[row[0]] = _row_to_signal(row)
            except Exception as e:
                log.warning(f"[miniapp] re-query after compute: {e}")

    # Fallback cho quỹ vẫn không có data
    for code in codes:
        if code not in results:
            results[code] = {"signal": "N/A", "score": 0, "nav": 0, "nav_date": "",
                             "rsi": None, "bb_pct": None, "chg_pct": 0, "details": []}
    return results


def _db_get_ccq_holdings(tg_id: str) -> list:
    """Tính holdings CCQ từ user_ccq_trades — luôn fresh từ DB."""
    try:
        if _db_mod is not None and _db_mod.is_available():
            with _db_mod.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT code, type, units, nav, amount
                        FROM user_ccq_trades
                        WHERE telegram_id = %s
                        ORDER BY trade_date, id
                    """, [tg_id])
                    rows = cur.fetchall()
        else:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT code, type, units, nav, amount
                    FROM user_ccq_trades
                    WHERE telegram_id = %s
                    ORDER BY trade_date, id
                """, [tg_id])
                rows = cur.fetchall()
            conn.close()
    except Exception as e:
        log.warning(f"[portfolio] _db_get_ccq_holdings: {e}")
        return []
    h: dict = {}
    for code, tx_type, units, nav, amount in rows:
        units = float(units or 0); nav = float(nav or 0); amount = float(amount or 0)
        if tx_type == "buy":
            if code not in h: h[code] = {"units": 0.0, "total_cost": 0.0}
            h[code]["units"]      += units
            h[code]["total_cost"] += units * nav
        elif tx_type == "dividend":
            if code not in h: h[code] = {"units": 0.0, "total_cost": 0.0}
            # CCQ tái đầu tư → cộng units; tiền mặt (units=0) → giảm cost basis như TCinvest
            h[code]["units"] += units
            if units <= 0 and amount > 0:
                h[code]["total_cost"] -= amount
        elif tx_type == "sell" and code in h and h[code]["units"] > 0:
            frac = min(units / h[code]["units"], 1.0)
            h[code]["total_cost"] -= h[code]["total_cost"] * frac
            h[code]["units"]      -= units
            if h[code]["units"] < 0.001: del h[code]
    return [
        {"code": c, "units": round(v["units"], 4),
         "avg_cost": round(v["total_cost"] / v["units"], 2)}
        for c, v in h.items() if v["units"] >= 0.001
    ]


def _calc_portfolio_with_holdings(holdings: list, signals: dict) -> dict:
    """Tính P&L từ holdings đã có sẵn — không query DB thêm."""
    return _calc_portfolio_core(holdings, signals)


def _calc_portfolio(profile: dict, signals: dict) -> dict:
    """Tính P&L từng quỹ — holdings đọc thẳng từ DB (không dùng snapshot config)."""
    tg_id = str(profile.get("telegram_id", ""))
    holdings = _db_get_ccq_holdings(tg_id) if tg_id else profile.get("portfolio", [])
    return _calc_portfolio_core(holdings, signals)


def _calc_portfolio_core(holdings: list, signals: dict) -> dict:
    items = []
    total_val = total_cost = 0.0
    for h in holdings:
        code = h.get("code", "")
        units = float(h.get("units", 0))
        avg_cost = float(h.get("avg_cost", 0))
        if not code or units <= 0 or avg_cost <= 0:
            continue
        sig_d = signals.get(code, {})
        nav_now = sig_d.get("nav", 0)
        if not nav_now:
            items.append({"code": code, "units": units, "avg_cost": avg_cost,
                         "nav": 0, "value": 0, "pnl": 0, "pnl_pct": 0, "signal": "N/A"})
            continue
        cost_val = units * avg_cost
        cur_val  = units * nav_now
        pnl      = cur_val - cost_val
        pnl_pct  = (nav_now - avg_cost) / avg_cost * 100
        total_val  += cur_val
        total_cost += cost_val
        items.append({
            "code": code, "units": units, "avg_cost": avg_cost,
            "nav": nav_now, "nav_date": sig_d.get("nav_date", ""),
            "value": round(cur_val), "cost": round(cost_val),
            "pnl": round(pnl), "pnl_pct": round(pnl_pct, 2),
            "signal": sig_d.get("signal", "N/A"),
            "rsi": sig_d.get("rsi"), "chg_pct": sig_d.get("chg_pct", 0),
        })
    total_pnl     = total_val - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0
    return {
        "items": items,
        "total_value": round(total_val),
        "total_cost": round(total_cost),
        "total_pnl": round(total_pnl),
        "total_pnl_pct": round(total_pnl_pct, 2),
    }


def _compute_vol_30d_batch(codes: list) -> dict:
    """Tính biến động 30 ngày (năm hoá) cho nhiều mã cùng lúc, dùng cho DCA
    riskparity/mpt. Trước đây `_calc_dca` đọc `s.get("vol_30d")` từ dict
    signals — nhưng field này KHÔNG BAO GIỜ có trong signals (chỉ tồn tại ở
    `compute_research_stats` trong bot.py, chạy riêng cho modal Nghiên cứu
    từng mã) → luôn fallback về hằng số 10 cho mọi quỹ → risk parity/MPT vô
    tình chia đều bất kể biến động thật khác nhau thế nào. Hàm này query
    trực tiếp nav_history (đã có sẵn, không cần fetch lại từ TCBS/fmarket)."""
    import math, statistics as _st
    result = {}
    if not codes or _db_mod is None or not _db_mod.is_available():
        return result
    try:
        with _db_mod.get_conn() as conn:
            with conn.cursor() as cur:
                for code in codes:
                    cur.execute(
                        "SELECT nav FROM nav_history WHERE fund_code=%s "
                        "ORDER BY nav_date DESC LIMIT 31",
                        (code,),
                    )
                    navs = [float(r[0]) for r in cur.fetchall()][::-1]  # oldest→newest
                    if len(navs) < 5:
                        continue
                    rets = [(navs[i] / navs[i - 1] - 1) for i in range(1, len(navs)) if navs[i - 1] > 0]
                    if len(rets) < 2:
                        continue
                    try:
                        result[code] = round(_st.stdev(rets) * math.sqrt(252) * 100, 2)
                    except Exception:
                        continue
    except Exception as e:
        log.warning(f"[dca] _compute_vol_30d_batch: {e}")
    return result


def _calc_dca(profile: dict, signals: dict, budget: float = 0, style: str = "dca") -> dict:
    """
    Phân bổ ngân sách theo 5 trường phái đầu tư.

    style:
      dca          - Intelligent DCA (Graham): weight = max(0, score+6), mua nhiều hơn khi rẻ
      value        - Value/Contrarian: ưu tiên quỹ gần đáy 52W, drawdown lớn, RSI thấp
      momentum     - Momentum: ưu tiên quỹ MA20>MA50, chg30 dương, score kỹ thuật cao
      riskparity   - Risk Parity (Dalio): weight = 1/volatility, quỹ ít biến động được nhiều hơn
      mpt          - MPT/Sharpe: weight = expected_return / variance (Sharpe proxy)
    """
    import math, statistics as _st

    holdings = {h["code"]: h for h in profile.get("portfolio", []) if h.get("units", 0) > 0}
    watched  = profile.get("watched_funds", [])
    monthly  = budget or float(profile.get("monthly_dca", 0) or 0)

    if monthly <= 0:
        return {"error": "Chưa cấu hình ngân sách DCA", "budget": 0, "items": [], "style": style}

    STYLE_META = {
        "dca":        {"name": "DCA Thông Minh",  "author": "Benjamin Graham",
                       "desc": "Mua nhiều hơn khi quỹ rẻ (RSI thấp, score tốt). Chia đều tối thiểu, ưu tiên tín hiệu tốt."},
        "value":      {"name": "Đầu Tư Giá Trị", "author": "Graham / Buffett",
                       "desc": "Tập trung vào quỹ đang gần đáy 52 tuần, bị bán quá mức. Mua nhiều nhất khi RSI<33 và BB%<20%."},
        "momentum":   {"name": "Theo Đà",          "author": "Jegadeesh & Titman",
                       "desc": "Phân bổ nhiều hơn cho quỹ đang trong xu hướng tăng (MA20>MA50, chg30 dương). Không mua quỹ đang giảm."},
        "riskparity": {"name": "Cân Bằng Rủi Ro", "author": "Ray Dalio",
                       "desc": "Quỹ biến động ÍT nhận VỐN NHIỀU hơn — để mỗi quỹ đóng góp rủi ro bằng nhau."},
        "mpt":        {"name": "Tối Ưu Sharpe",   "author": "Harry Markowitz",
                       "desc": "Tối đa hóa lợi nhuận kỳ vọng / biến động. Nghiêng về quỹ có Sharpe Ratio cao nhất."},
    }
    meta = STYLE_META.get(style, STYLE_META["dca"])

    # riskparity/mpt cần vol_30d thật — signals[] không có field này (chỉ được
    # tính riêng cho modal Nghiên cứu), nên tính batch 1 lần ở đây thay vì để
    # mỗi quỹ fallback về hằng số 10 (vô tình biến risk parity thành chia đều).
    vol_by_code = _compute_vol_30d_batch(watched) if style in ("riskparity", "mpt") else {}

    weights = {}
    reasons = {}  # lý do cho từng quỹ

    for code in watched:
        s   = signals.get(code, {})
        sc  = s.get("score", 0)
        rsi = s.get("rsi") or 50
        bb  = s.get("bb_pct") or 50
        nav = s.get("nav", 0)
        chg30 = s.get("chg30") or 0
        ma20  = s.get("ma20")  or 0
        ma50  = s.get("ma50")  or 0
        vol   = vol_by_code.get(code) or s.get("vol_30d") or 10  # % annualized volatility
        sig   = s.get("signal", "N/A")

        if style == "dca":
            # Graham Intelligent DCA: weight = max(0, score+6)
            # HOLD=6, MUA=9, MUA MẠNH=12, BÁN=3, BÁN MẠNH=0
            w = max(0.0, sc + 6.0)
            if rsi < 40: w += 2
            elif rsi < 50: w += 1
            r = f"Score {sc:+}, RSI {rsi:.0f}"
            if rsi < 40: r += " (quá bán ✅)"

        elif style == "value":
            # Value: ưu tiên rẻ so với 52W, RSI thấp, BB thấp
            # Drawdown từ đỉnh: lấy từ pct_from_high nếu có, else ước từ bb
            pct_from_high = s.get("pct_from_high") or -(50 - bb) * 0.3
            below_ma50 = nav and ma50 and nav < ma50
            w = 1.0  # base
            if pct_from_high < -20:   w += 4; r_part = "Cách đỉnh >20%🟢🟢"
            elif pct_from_high < -10: w += 2; r_part = "Cách đỉnh >10%🟢"
            else:                     r_part = f"Cách đỉnh {pct_from_high:.0f}%"
            if rsi < 33:   w += 3; r_part += ", RSI quá bán🟢🟢"
            elif rsi < 45: w += 1; r_part += ", RSI thấp🟢"
            if bb < 20:    w += 2; r_part += ", BB đáy🟢"
            if below_ma50: w += 1; r_part += ", dưới MA50✅"
            if "BÁN MẠNH" in sig: w = 0.5  # vẫn mua nhưng rất ít
            r = r_part

        elif style == "momentum":
            # Momentum: chỉ mua quỹ đang tăng, bỏ qua quỹ giảm
            up_trend = ma20 and ma50 and ma20 > ma50
            w = 0.1  # tối thiểu để không bỏ trống
            r_parts = []
            if up_trend:      w += 3; r_parts.append("MA20>MA50✅")
            if chg30 > 3:     w += 3; r_parts.append(f"chg30 +{chg30:.1f}%🟢")
            elif chg30 > 0:   w += 1; r_parts.append(f"chg30 +{chg30:.1f}%")
            elif chg30 < -3:  w  = 0; r_parts.append(f"chg30 {chg30:.1f}%🔴 → bỏ qua")
            if sc >= 6:       w += 2; r_parts.append("Score mạnh")
            elif sc >= 3:     w += 1
            if "BÁN" in sig and not "MUA" in sig: w = 0; r_parts.append("Tín hiệu BÁN → 0%")
            r = ", ".join(r_parts) if r_parts else "Không đủ đà"

        elif style == "riskparity":
            # Risk Parity: weight = 1 / volatility
            # vol_30d từ calc_signal nếu có, else ước từ chg30
            if vol and vol > 0:
                w = 1.0 / vol
                r = f"Vol {vol:.1f}% → weight {w:.3f}"
            else:
                w = 0.1
                r = "Không đủ dữ liệu vol"

        elif style == "mpt":
            # MPT Sharpe proxy: weight = E[R] / Var(R)
            # E[R] proxy = chg30 annualized; Var = vol²
            er = (chg30 / 30 * 252) if chg30 else 5.0  # annualized % return estimate
            variance = (vol ** 2) if vol else 100
            sharpe_proxy = er / variance if variance > 0 else 0
            w = max(0.01, sharpe_proxy)
            r = f"E[R]≈{er:.0f}%, Vol={vol:.0f}% → Sharpe≈{sharpe_proxy:.3f}"

        else:
            w = 1.0; r = "Chia đều"

        weights[code] = max(0.0, w)
        reasons[code] = r

    total_w = sum(weights.values()) or 1
    items   = []
    for code in watched:
        s   = signals.get(code, {})
        nav = s.get("nav", 0)
        pct = weights[code] / total_w
        amount = round(monthly * pct / 1000) * 1000
        units  = round(amount / nav, 4) if nav and nav > 0 else 0
        h      = holdings.get(code, {})
        items.append({
            "code":         code,
            "amount":       amount,
            "pct_alloc":    round(pct * 100, 1),
            "units_est":    units,
            "nav":          nav,
            "nav_date":     s.get("nav_date", ""),
            "signal":       s.get("signal", "N/A"),
            "rsi":          s.get("rsi"),
            "bb_pct":       s.get("bb_pct"),
            "score":        s.get("score", 0),
            "reason":       reasons.get(code, ""),
            "current_units":float(h.get("units", 0)),
            "avg_cost":     float(h.get("avg_cost", 0)),
            "skip":         weights[code] == 0,
        })
    items.sort(key=lambda x: x["pct_alloc"], reverse=True)
    total_alloc = sum(i["amount"] for i in items)
    remainder   = int(monthly) - total_alloc

    return {
        "budget":      round(monthly),
        "total_alloc": total_alloc,
        "remainder":   remainder,
        "style":       style,
        "style_name":  meta["name"],
        "style_author":meta["author"],
        "style_desc":  meta["desc"],
        "items":       items,
    }


# ── Telegram initData auth ────────────────────────────────────────────────────

_INIT_DATA_MAX_AGE_SECONDS = 86400  # 24h — khớp khuyến nghị chống replay của Telegram
_INIT_DATA_CLOCK_SKEW_SECONDS = 300  # 5 phút — dung sai lệch giờ giữa client/server


def _validate_init_data(init_data_str: str, bot_token: str):
    """Xác thực chữ ký HMAC của Telegram WebApp initData.
    Returns parsed user dict nếu hợp lệ, None nếu không hợp lệ hoặc thiếu.

    Kèm check `auth_date` (chống replay): initData quá cũ (>24h) hoặc auth_date
    ở tương lai (ngoài dung sai lệch giờ) đều bị từ chối, dù chữ ký HMAC vẫn đúng
    — vì initData có thể bị chặn bắt/lưu lại rồi replay sau (GOV-005 còn thiếu).
    """
    if not init_data_str or not bot_token:
        return None
    try:
        params = dict(_uparse.parse_qsl(init_data_str, keep_blank_values=True))
        hash_val = params.pop("hash", "")
        if not hash_val:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed   = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, hash_val):
            return None
        auth_date_raw = params.get("auth_date")
        if auth_date_raw is not None:
            try:
                age = time.time() - int(auth_date_raw)
            except (TypeError, ValueError):
                return None
            if age > _INIT_DATA_MAX_AGE_SECONDS or age < -_INIT_DATA_CLOCK_SKEW_SECONDS:
                return None
        return json.loads(params.get("user", "{}"))
    except Exception:
        return None


def _auth_write(handler, claimed_tg_id: str) -> bool:
    """Kiểm tra quyền ghi: initData phải hợp lệ (chữ ký HMAC thật từ Telegram) và
    user.id đã xác thực phải khớp claimed_tg_id.

    LƯU Ý BẢO MẬT: trước đây có bypass "nếu claimed_tg_id == admin_id thì cho
    qua luôn, không cần initData" — đây là lỗ hổng nghiêm trọng vì claimed_tg_id
    lấy thẳng từ body request (client tự khai), KHÔNG phải giá trị đã xác thực.
    Bất kỳ ai biết telegram_id thật của admin đều có thể giả danh admin mà
    không cần chữ ký Telegram nào. Đã bỏ bypass này — admin (kể cả tài khoản
    /beta của admin, lưu dưới id ÂM) giờ BẮT BUỘC phải qua initData thật như
    user thường, chỉ khác là id âm được đối chiếu với id dương đã xác thực.

    Trả về True nếu được phép, False và tự gửi 403 nếu bị từ chối.
    """
    cfg       = _load_cfg()
    bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
    admin_id  = str(cfg.get("admin_telegram_id", ""))

    init_data   = handler.headers.get("X-Init-Data", "")
    web_session = handler.headers.get("X-Web-Session", "")

    if not init_data and web_session:
        # Bản Web độc lập (ngoài Telegram) — đăng nhập qua Telegram Login Widget,
        # xem _verify_telegram_login_widget()/_issue_web_session() phía trên.
        real_id = _verify_web_session(web_session)
        if not real_id:
            _json(handler, {"error": "Phiên đăng nhập Web đã hết hạn, vui lòng đăng nhập lại"}, 403)
            return False
        if claimed_tg_id == real_id:
            return True
        _json(handler, {"error": "Không có quyền thao tác trên tài khoản này"}, 403)
        return False

    if not init_data:
        # Dev/local mode CHỈ khi ENV MINIAPP_NO_AUTH được set thủ công trên server
        # (không phải thứ client có thể tự bật) — dùng khi test cục bộ.
        if os.environ.get("MINIAPP_NO_AUTH"):
            return True
        _json(handler, {"error": "Yêu cầu xác thực Telegram"}, 403)
        return False

    user = _validate_init_data(init_data, bot_token)
    if not user:
        _json(handler, {"error": "initData không hợp lệ"}, 403)
        return False

    real_id = str(user.get("id", ""))
    if claimed_tg_id == real_id:
        return True
    # Tài khoản /beta của admin: claimed_tg_id là id ÂM, nhưng phiên Telegram
    # đăng nhập vẫn phải là chính admin thật (real_id == admin_id).
    if real_id and real_id == admin_id and claimed_tg_id == "-" + real_id:
        return True

    _json(handler, {"error": "Không có quyền thao tác trên tài khoản này"}, 403)
    return False


# ── Telegram Login Widget auth (bản Web độc lập, ngoài Telegram) ─────────────
# Mini App dùng "initData" (window.Telegram.WebApp) — chỉ hoạt động khi mở QUA
# app Telegram. Web bên ngoài (browser thường) dùng cơ chế khác của Telegram:
# "Login Widget" (https://core.telegram.org/widgets/login) — thuật toán ký
# HÁC KHÁC initData (secret_key = SHA256(bot_token) thẳng, không phải
# HMAC(bot_token, key="WebAppData") như initData) nên không thể tái dùng
# _validate_init_data() ở trên. Sau khi verify xong 1 lần lúc đăng nhập, server
# tự phát hành 1 "web session token" riêng (ký bằng WEB_SESSION_SECRET) để các
# request ghi (write) sau đó gửi qua header X-Web-Session — xem _auth_write().
_WEB_SESSION_SECRET = os.environ.get("WEB_SESSION_SECRET", "")
_WEB_SESSION_MAX_AGE_SECONDS = 30 * 86400  # 30 ngày — user Web không re-login mỗi lần mở tab
_LOGIN_WIDGET_MAX_AGE_SECONDS = 86400      # 24h — chống replay payload widget cũ


def _verify_telegram_login_widget(payload: dict, bot_token: str) -> "dict | None":
    """Xác thực payload trả về từ Telegram Login Widget (KHÁC initData của Mini
    App — xem ghi chú phía trên). Trả dict user (id, first_name, username...)
    nếu hợp lệ, None nếu sai chữ ký hoặc quá hạn (chống replay)."""
    if not payload or not bot_token:
        return None
    data = {k: v for k, v in payload.items() if k != "hash"}
    hash_val = str(payload.get("hash", ""))
    if not hash_val:
        return None
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed   = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, hash_val):
        return None
    try:
        age = time.time() - int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return None
    if age > _LOGIN_WIDGET_MAX_AGE_SECONDS or age < -_INIT_DATA_CLOCK_SKEW_SECONDS:
        return None
    return data


def _issue_web_session(telegram_id: str) -> str:
    """Phát hành session token cho Web sau khi đăng nhập Telegram Login Widget
    thành công — format `<tg_id>.<expiry_unix>.<hmac_hex>`. Không dùng JWT thư
    viện ngoài để tránh thêm dependency chỉ cho 1 việc đơn giản này."""
    expiry = int(time.time()) + _WEB_SESSION_MAX_AGE_SECONDS
    body = f"{telegram_id}.{expiry}"
    sig = hmac.new(_WEB_SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_web_session(token: str) -> "str | None":
    """Kiểm tra web session token — trả telegram_id nếu hợp lệ và chưa hết hạn."""
    if not token or not _WEB_SESSION_SECRET:
        return None
    try:
        tg_id, expiry_str, sig = token.split(".", 2)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return None
    body = f"{tg_id}.{expiry_str}"
    expected = hmac.new(_WEB_SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    if time.time() > expiry:
        return None
    return tg_id


def _check_admin_secret(data: dict) -> bool:
    """Xác thực script nội bộ (chạy từ máy admin, KHÔNG có phiên Telegram nên
    không tạo được X-Init-Data) bằng secret ADMIN_API_KEY — CHỈ đặt được qua ENV
    trên server, không phải giá trị client tự khai như telegram_id (khác hẳn
    lỗ hổng cũ). Dùng cho scripts/import_tcbs_xlsx.py và các script tương tự.
    Trả False (không phải 403) nếu ADMIN_API_KEY chưa được set — không tạo thêm
    đường vòng nào khi tính năng chưa được bật."""
    secret = os.environ.get("ADMIN_API_KEY", "")
    if not secret:
        return False
    return hmac.compare_digest(str(data.get("admin_key", "")), secret)


def _is_admin(telegram_id: str) -> bool:
    """Kiểm tra tg_id có phải admin_telegram_id trong config không."""
    if not telegram_id:
        return False
    cfg = _load_cfg()
    admin_id = str(cfg.get("admin_telegram_id", ""))
    return bool(admin_id and str(telegram_id) == admin_id)


def _effective_tg_id(tg_id: str, is_beta: bool) -> str:
    """/beta mode (BETA-001): nếu is_beta=True VÀ caller là admin, mọi thao tác
    tài khoản (profile, watched_funds, giao dịch, tier, alerts...) được chuyển
    sang telegram_id ÂM (cô lập hoàn toàn khỏi tài khoản thật) — NAV/tín hiệu/
    giá vàng/dự báo T+2 KHÔNG đi qua hàm này nên vẫn dùng chung dữ liệu thật.
    Chỉ admin mới được vào chế độ này — user khác gửi beta=1 sẽ bị bỏ qua."""
    if is_beta and _is_admin(tg_id):
        try:
            return str(-abs(int(tg_id)))
        except (TypeError, ValueError):
            return tg_id
    return tg_id


def _qs_tg_id(qs: dict, alt_key: str = None) -> str:
    """Đọc user_id từ query string + tự áp dụng /beta remap nếu có &beta=1.
    Dùng cho các endpoint tài khoản (KHÔNG dùng cho endpoint admin-only —
    admin-only phải check _is_admin() bằng id thật trước khi remap)."""
    tg_id = (qs.get("user_id") or (qs.get(alt_key) if alt_key else None) or [""])[0]
    if qs.get("beta") == ["1"]:
        tg_id = _effective_tg_id(tg_id, True)
    return tg_id


def _data_tg_id(data: dict, key: str = "telegram_id") -> str:
    """Đọc telegram_id từ body POST + tự áp dụng /beta remap nếu data['beta']==1.
    Gọi SAU khi _auth_write() đã xác thực bằng id thật thành công."""
    tg_id = str(data.get(key, ""))
    if str(data.get("beta")) == "1":
        tg_id = _effective_tg_id(tg_id, True)
    return tg_id


# GOV-003: phát hiện brute-force đoán mã khuyến mãi/giới thiệu — in-memory, đủ dùng vì
# đây là soft rate-limit theo tiến trình server (Railway restart reset là chấp nhận được,
# không phải cơ chế bảo mật chính, chỉ là lớp cảnh báo sớm bổ sung).
_PROMO_ATTEMPTS: dict = {}
PROMO_ABUSE_WINDOW_SEC  = 60
PROMO_ABUSE_MAX_ATTEMPTS = 5


def _check_promo_abuse(tg_id: str) -> bool:
    """True nếu tg_id vừa thử áp mã > PROMO_ABUSE_MAX_ATTEMPTS lần trong
    PROMO_ABUSE_WINDOW_SEC giây gần nhất (mỗi lần gọi = 1 lần thử, kể cả redeem thành công)."""
    now = time.time()
    hist = [t for t in _PROMO_ATTEMPTS.get(tg_id, []) if now - t < PROMO_ABUSE_WINDOW_SEC]
    hist.append(now)
    _PROMO_ATTEMPTS[tg_id] = hist
    return len(hist) > PROMO_ABUSE_MAX_ATTEMPTS


# GOV-010: ngưỡng cảnh báo sybil farm referral — số lượt redeem KHÁC NHAU của
# cùng 1 mã referral trong 24h. Referrer chỉ nhận bonus 1 lần/30 ngày nên giá
# trị kinh tế của farm đã bị chặn phần lớn, nhưng vẫn cảnh báo để admin biết mà
# ban thủ công nếu cần (xem POST /api/admin/user/ban).
REFERRAL_SYBIL_ALERT_THRESHOLD = 3


def _notify_admin_referral_sybil(code: str, referrer_id, recent_count: int) -> None:
    cfg = _load_cfg()
    admin_id = str(cfg.get("admin_telegram_id") or os.environ.get("ADMIN_TELEGRAM_ID", "")).strip()
    token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
    if not admin_id or not token or token.startswith("NHAP"):
        return
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": admin_id,
                  "text": f"⚠️ Nghi ngờ sybil farm mã giới thiệu: code={code} "
                          f"referrer={referrer_id} — {recent_count} lượt redeem trong 24h.\n"
                          f"Dùng /api/admin/user/ban nếu cần khoá thủ công."},
            timeout=8,
        )
    except Exception:
        pass


def _notify_admin_promo_abuse(tg_id: str) -> None:
    cfg = _load_cfg()
    admin_id = str(cfg.get("admin_telegram_id") or os.environ.get("ADMIN_TELEGRAM_ID", "")).strip()
    token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
    if not admin_id or not token or token.startswith("NHAP"):
        return
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": admin_id,
                  "text": f"⚠️ Phát hiện đoán mã khuyến mãi bất thường: telegram_id={tg_id} "
                          f"(>{PROMO_ABUSE_MAX_ATTEMPTS} lần thử trong {PROMO_ABUSE_WINDOW_SEC}s)"},
            timeout=8,
        )
    except Exception:
        pass


def _get_tier(telegram_id: str) -> dict:
    """Trả {tier, pro_expires_at}. Admin luôn là 'pro' effective. 'free' nếu DB không sẵn sàng."""
    if _is_admin(telegram_id):
        # Admin có toàn bộ Pro features, không cần mua
        return {"tier": "pro", "pro_expires_at": None}
    if _db_mod is not None and _db_mod.is_available():
        try:
            return _db_mod.get_tier(telegram_id)
        except Exception as e:
            log.warning(f"[miniapp] get_tier lỗi: {e}")
    return {"tier": "free", "pro_expires_at": None}


def _check_tier(handler, telegram_id: str, required_tier: str = "pro") -> bool:
    """Middleware (GATE-002): chặn request nếu user chưa đủ tier.
    Admin bypass tất cả. Trả True nếu đủ quyền; False + 403 nếu không."""
    if required_tier == "free":
        return True
    if _is_admin(telegram_id):
        return True
    info = _get_tier(telegram_id)
    if info.get("tier") == required_tier:
        return True
    _json(handler, {"error": "pro_required", "upgrade_url": "/buy"}, 403)
    return False


# ── PostgreSQL trade tables ────────────────────────────────────────────────────

_TRADE_TABLES_READY = False


def _get_db_conn():
    """Kết nối PostgreSQL từ DATABASE_URL."""
    import psycopg2
    db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
    return psycopg2.connect(db_url, connect_timeout=8)


def _init_trade_tables():
    """Tạo bảng user_ccq_trades + user_gold_trades nếu chưa có."""
    global _TRADE_TABLES_READY
    if _TRADE_TABLES_READY:
        return
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_ccq_trades (
                    id            SERIAL PRIMARY KEY,
                    telegram_id   TEXT NOT NULL,
                    code          TEXT NOT NULL,
                    type          TEXT NOT NULL CHECK (type IN ('buy','sell')),
                    trade_date    DATE NOT NULL,
                    units         DOUBLE PRECISION NOT NULL,
                    nav           DOUBLE PRECISION NOT NULL,
                    amount        BIGINT NOT NULL,
                    note          TEXT DEFAULT '',
                    nav_mismatch  BOOLEAN DEFAULT FALSE,
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_ccq_tg  ON user_ccq_trades(telegram_id);
                CREATE INDEX IF NOT EXISTS idx_ccq_code ON user_ccq_trades(code);

                CREATE TABLE IF NOT EXISTS user_gold_trades (
                    id              SERIAL PRIMARY KEY,
                    telegram_id     TEXT NOT NULL,
                    product         TEXT NOT NULL,
                    type            TEXT NOT NULL CHECK (type IN ('buy','sell')),
                    trade_date      DATE NOT NULL,
                    unit            TEXT DEFAULT 'luong',
                    qty             DOUBLE PRECISION NOT NULL,
                    qty_luong       DOUBLE PRECISION NOT NULL,
                    price_per_luong BIGINT NOT NULL,
                    total_vnd       BIGINT NOT NULL,
                    note            TEXT DEFAULT '',
                    name            TEXT DEFAULT '',
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_gold_tg ON user_gold_trades(telegram_id);
                ALTER TABLE user_gold_trades ADD COLUMN IF NOT EXISTS name TEXT DEFAULT '';
            """)
        conn.commit()
        conn.close()
        _TRADE_TABLES_READY = True
        log.info("[miniapp] Trade tables ready")
    except Exception as e:
        log.warning(f"[miniapp] _init_trade_tables: {e}")


def _db_recalc_portfolio(cfg: dict, tg_id: str):
    """No-op: portfolio giờ được tính on-demand từ DB trong _calc_portfolio."""
    pass


# ── Request Handler ────────────────────────────────────────────────────────────

class MiniAppHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.debug(fmt % args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-HTTP-Method-Override, X-Init-Data, X-Web-Session")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"
        qs     = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_html()
        elif path == "/admin/pnl":
            self._serve_pnl_html()
        elif path == "/web":
            self._serve_web_html()
        elif path == "/api/admin/pnl":
            self._api_admin_pnl_get(qs)
        elif path == "/api/me":
            self._api_me(qs)
        elif path == "/api/signals":
            self._api_signals(qs)
        elif path.startswith("/api/nav/"):
            code = path[len("/api/nav/"):].upper()
            self._api_nav_history(code)
        elif path.startswith("/api/research/"):
            code = path[len("/api/research/"):].upper()
            self._api_research(code, qs)
        elif path.startswith("/api/t2/accuracy/"):
            code = path[len("/api/t2/accuracy/"):].upper()
            self._api_t2_accuracy(code, qs)
        elif path == "/api/dca":
            self._api_dca(qs)
        elif path == "/api/trades":
            self._api_get_trades(qs)
        elif path == "/api/gold":
            self._api_gold(qs)
        elif path == "/api/gold/history":
            self._api_gold_history(qs)
        elif path == "/api/gold/chart":
            self._api_gold_chart(qs)
        elif path == "/api/gold/trades":
            self._api_get_gold_trades(qs)
        elif path == "/api/fed-rate":
            self._api_fed_rate()
        elif path == "/api/alerts":
            self._api_list_alerts(qs)
        elif path == "/api/admin/nav/pending":
            self._api_admin_nav_pending(qs)
        elif path == "/api/referral/mine":
            self._api_referral_mine(qs)
        elif path == "/api/payment/sepay/status":
            self._api_sepay_status(qs)
        elif path == "/api/admin/promo/list":
            self._api_admin_promo_list(qs)
        elif path == "/api/admin/audit":
            self._api_admin_audit(qs)
        elif path == "/api/admin/summary":
            self._api_admin_summary(qs)
        elif path == "/api/admin/user/banned-list":
            self._api_admin_banned_list(qs)
        elif path == "/api/admin/users":
            self._api_admin_users(qs)
        elif path == "/api/admin/discount/list":
            self._api_admin_discount_list(qs)
        elif path == "/api/admin/payments/recent":
            self._api_admin_payments_recent(qs)
        elif path == "/api/history":
            self._api_unified_history(qs)
        elif path.startswith("/api/nav_history/"):
            code = path[len("/api/nav_history/"):].upper()
            self._api_nav_history_chart(code, qs)
        elif path.startswith("/api/gold/price_history/"):
            from urllib.parse import unquote
            product = unquote(path[len("/api/gold/price_history/"):])
            self._api_gold_price_history(product)
        elif path == "/health":
            _json(self, {"ok": True, "ts": datetime.now().isoformat()})
        elif path == "/api/version":
            self._api_version(qs)
        else:
            _json(self, {"error": "Not found"}, 404)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        # Lưu raw bytes — cần cho xác thực chữ ký HMAC-SHA256 (SePay webhook):
        # chữ ký ký trên ĐÚNG byte stream gốc, parse lại JSON rồi re-serialize
        # có thể đổi thứ tự key/khoảng trắng → sai chữ ký dù nội dung giống hệt.
        self._raw_body = body
        try:
            return json.loads(body) if body else {}
        except Exception:
            return {}

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        data   = self._read_body()
        if path.startswith("/api/gold/trade/"):
            idx = path[len("/api/gold/trade/"):]
            self._api_delete_gold_trade(idx, data)
        elif path.startswith("/api/trade/"):
            idx = path[len("/api/trade/"):]
            self._api_delete_trade(idx, data)
        elif path.startswith("/api/alerts/"):
            idx = path[len("/api/alerts/"):]
            self._api_delete_alert(idx, data)
        else:
            _json(self, {"error": "Not found"}, 404)

    def do_POST(self):
        data   = self._read_body()
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/api/me/watched_funds":
            self._api_update_watched(data)
        elif path == "/api/alerts":
            self._api_create_alert(data)
        elif path == "/api/gold/trade":
            self._api_add_gold_trade(data)
        elif path.startswith("/api/gold/trade/"):
            idx = path[len("/api/gold/trade/"):]
            self._api_edit_gold_trade(idx, data)
        elif path == "/api/trade":
            self._api_add_trade(data)
        elif path.startswith("/api/trade/"):
            idx = path[len("/api/trade/"):]
            method = self.headers.get("X-HTTP-Method-Override", "").upper() or "POST"
            if method == "DELETE":
                self._api_delete_trade(idx, data)
            else:
                self._api_edit_trade(idx, data)
        elif path == "/api/admin/settoken":
            self._api_admin_settoken(data)
        elif path == "/api/admin/fetch-nav":
            self._api_admin_fetch_nav(data)
        elif path == "/api/admin/import-nav":
            self._api_admin_import_nav(data)
        elif path == "/api/admin/nav/confirm":
            self._api_admin_nav_confirm(data)
        elif path == "/api/nav/draft":
            self._api_nav_draft(data)
        elif path == "/api/admin/fixportfolio":
            self._api_admin_fixportfolio(data)
        elif path == "/api/admin/import-trades":
            self._api_admin_import_trades(data)
        elif path == "/api/payment/stars/create":
            self._api_create_stars_invoice(data)
        elif path == "/api/payment/momo/create":
            self._api_momo_create(data)
        elif path == "/api/payment/momo/ipn":
            self._api_momo_ipn(data)
        elif path == "/api/payment/sepay/create":
            self._api_sepay_create(data)
        elif path == "/api/payment/sepay/webhook":
            self._api_sepay_webhook(data)
        elif path == "/api/promo/redeem":
            self._api_promo_redeem(data)
        elif path == "/api/admin/promo/create":
            self._api_admin_promo_create(data)
        elif path == "/api/admin/promo/deactivate":
            self._api_admin_promo_deactivate(data)
        elif path == "/api/admin/promo/activate":
            self._api_admin_promo_activate(data)
        elif path == "/api/admin/promo/edit":
            self._api_admin_promo_edit(data)
        elif path == "/api/admin/user/ban":
            self._api_admin_ban_user(data)
        elif path == "/api/admin/user/unban":
            self._api_admin_unban_user(data)
        elif path == "/api/admin/pnl/cost":
            self._api_admin_pnl_set_cost(data)
        elif path == "/api/admin/discount/create":
            self._api_admin_discount_create(data)
        elif path == "/api/admin/discount/edit":
            self._api_admin_discount_edit(data)
        elif path == "/api/admin/discount/activate":
            self._api_admin_discount_set_active(data, True)
        elif path == "/api/admin/discount/deactivate":
            self._api_admin_discount_set_active(data, False)
        elif path == "/api/auth/telegram-login":
            self._api_auth_telegram_login(data)
        else:
            _json(self, {"error": "Not found"}, 404)

    # ── Endpoints ────────────────────────────────────────────────────

    def _serve_html(self):
        if not HTML_FILE.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"miniapp/index.html not found")
            return
        content = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_pnl_html(self):
        """GET /admin/pnl — trang admin xem P&L thật, mở trực tiếp qua trình
        duyệt (ngoài Telegram). Trang tĩnh, tự fetch dữ liệu qua /api/admin/pnl
        bằng token trong query string — không cần build gì đặc biệt ở đây."""
        if not HTML_FILE_PNL.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"admin_pnl.html not found")
            return
        content = HTML_FILE_PNL.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_web_html(self):
        """GET /web — bản Web độc lập, đăng nhập qua Telegram Login Widget thay
        vì mở trong Telegram (xem _verify_telegram_login_widget() ở trên)."""
        if not HTML_FILE_WEB.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"miniapp/web.html not found")
            return
        content = HTML_FILE_WEB.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _api_auth_telegram_login(self, data: dict):
        """POST /api/auth/telegram-login — body là object Telegram Login Widget
        trả về nguyên văn (id, first_name, username, photo_url, auth_date, hash).
        Verify xong thì phát hành web session token cho client lưu lại, gửi kèm
        header X-Web-Session ở mọi request ghi tiếp theo (xem _auth_write())."""
        if not _WEB_SESSION_SECRET:
            _json(self, {"error": "Web login chưa được cấu hình (thiếu WEB_SESSION_SECRET)"}, 503)
            return
        cfg       = _load_cfg()
        bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
        user = _verify_telegram_login_widget(data, bot_token)
        if not user:
            _json(self, {"error": "Xác thực Telegram thất bại hoặc đã hết hạn"}, 403)
            return
        tg_id = str(user.get("id", ""))
        session = _issue_web_session(tg_id)
        if _db_mod is not None and _db_mod.is_available():
            _db_mod.log_audit(tg_id, "web.login", "users", tg_id,
                               note=f"username={user.get('username', '')}")
        _json(self, {
            "ok": True, "telegram_id": tg_id, "session": session,
            "first_name": user.get("first_name", ""), "username": user.get("username", ""),
            "photo_url": user.get("photo_url", ""),
        })

    def _check_admin_web_token(self, token: str) -> bool:
        if not _ADMIN_WEB_TOKEN:
            return False
        return hmac.compare_digest(str(token or ""), _ADMIN_WEB_TOKEN)

    def _api_admin_pnl_get(self, qs: dict):
        token = (qs.get("token") or [""])[0]
        if not self._check_admin_web_token(token):
            _json(self, {"error": "invalid token"}, 403)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        data = _db_mod.get_real_pnl_summary()
        cfg = _load_cfg()
        admin_tg_id = str(cfg.get("admin_telegram_id", "")).strip()
        if admin_tg_id:
            holdings = _db_get_ccq_holdings(admin_tg_id)
            if holdings:
                signals = _get_signals_for_codes([h["code"] for h in holdings], cfg)
                portfolio = _calc_portfolio_core(holdings, signals)
                data["admin_portfolio"] = portfolio
        _json(self, data)

    def _api_admin_pnl_set_cost(self, data: dict):
        token = str(data.get("token", ""))
        if not self._check_admin_web_token(token):
            _json(self, {"error": "invalid token"}, 403)
            return
        try:
            cost = float(data.get("hosting_cost_vnd"))
            assert cost >= 0
        except (TypeError, ValueError, AssertionError):
            _json(self, {"error": "hosting_cost_vnd phải là số >= 0"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        _db_mod.set_setting("hosting_cost_vnd", str(cost))
        _json(self, {"ok": True})

    def _api_me(self, qs: dict):
        import time as _time
        t0 = _time.time()
        tg_id = _qs_tg_id(qs, "telegram_id")
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400)
            return
        if not _auth_write(self, tg_id):
            return
        cfg     = _load_cfg()
        profile = _find_profile(cfg, tg_id)
        log.info(f"[/api/me] {tg_id} find_profile={_time.time()-t0:.2f}s")
        if not profile:
            reg_name = (qs.get("name") or [""])[0].strip() or f"User_{str(tg_id)[-4:]}"
            default_funds = cfg.get("default_watched_funds", ["TCBF", "SSISCA", "VCBFBCF"])
            if _db_mod is not None and _db_mod.is_available():
                try:
                    profile = _db_mod.create_profile(tg_id, reg_name, default_funds)
                    log.info(f"[miniapp][auto-register] {reg_name} ({tg_id})")
                except Exception as e:
                    log.error(f"[miniapp][auto-register] DB lỗi: {e}")
            if not profile:
                _json(self, {"error": "Profile không tìm thấy", "telegram_id": tg_id}, 404)
                return
        watched  = profile.get("watched_funds", [])
        holdings = _db_get_ccq_holdings(tg_id)  # 1 lần duy nhất
        log.info(f"[/api/me] {tg_id} holdings={len(holdings)} t={_time.time()-t0:.2f}s")
        portfolio_codes = [h["code"] for h in holdings]
        all_codes = list(dict.fromkeys(watched + portfolio_codes))
        signals  = _get_signals_for_codes(all_codes, cfg)  # background, trả về ngay
        log.info(f"[/api/me] {tg_id} signals cached={len([s for s in signals.values() if s.get('nav')])} t={_time.time()-t0:.2f}s")
        portfolio = _calc_portfolio_with_holdings(holdings, signals)  # tái dùng holdings
        is_admin  = _is_admin(tg_id)
        tier_info = _get_tier(tg_id)  # admin → luôn trả "pro" effective
        is_pro    = tier_info.get("tier") == "pro"

        # T2-009: Dự báo T+2 cho Pro/Admin users
        predictions = {}
        if is_pro and _db_mod is not None and _db_mod.is_available():
            try:
                predictions = _db_mod.get_predictions(all_codes)
            except Exception as e:
                log.debug(f"[/api/me] get_predictions error (non-fatal): {e}")

        log.info(f"[/api/me] {tg_id} DONE t={_time.time()-t0:.2f}s")

        # tier hiển thị: admin → "admin", pro → "pro", else "free"
        display_tier = "admin" if is_admin else tier_info.get("tier", "free")
        _json(self, {
            "name": profile.get("name", ""),
            "telegram_id": tg_id,
            "watched_funds": watched,
            "monthly_dca": profile.get("monthly_dca", 0),
            "portfolio": portfolio,
            "signals": signals,
            "tier": display_tier,
            "is_admin": is_admin,
            "pro_expires_at": tier_info.get("pro_expires_at").isoformat() if tier_info.get("pro_expires_at") else None,
            "free_fund_limit": FREE_FUND_LIMIT if not is_pro else None,
            "predictions": predictions,
        })

    def _api_signals(self, qs: dict):
        tg_id = _qs_tg_id(qs)
        if tg_id and not _auth_write(self, tg_id):
            return
        cfg     = _load_cfg()
        profile = _find_profile(cfg, tg_id) if tg_id else None
        watched = profile.get("watched_funds", []) if profile else list(cfg.get("funds", {}).keys())[:10]
        signals = _get_signals_for_codes(watched, cfg, background_compute=False)
        # Merge confidence info (provisional/manual/pending_confirm/confirmed) vào mỗi signal
        confidence = _get_nav_confidence_map(watched)
        for code, conf in confidence.items():
            if code in signals:
                signals[code]["nav_source"]  = conf.get("nav_source", "")
                signals[code]["pending_nav"] = conf.get("pending_nav")
        # Vị thế cá nhân (units/avg_cost/pnl) — CHỈ hiển thị, KHÔNG dùng để tính signal/score.
        if tg_id:
            for h in _db_get_ccq_holdings(tg_id):
                code = h["code"]
                if code in signals and signals[code].get("nav"):
                    nav = signals[code]["nav"]
                    units, avg_cost = h["units"], h["avg_cost"]
                    pnl_pct = (nav / avg_cost - 1) * 100 if avg_cost else 0
                    signals[code]["position"] = {
                        "units": units, "avg_cost": avg_cost,
                        "pnl": round((nav - avg_cost) * units, 0),
                        "pnl_pct": round(pnl_pct, 2),
                    }
        all_funds = {code: info.get("name", code) for code, info in cfg.get("funds", {}).items()}
        _json(self, {"signals": signals, "updated": datetime.now().isoformat(),
                     "watched": watched, "all_funds": all_funds})

    def _api_update_watched(self, data: dict):
        """POST /api/me/watched_funds — cập nhật danh sách quỹ theo dõi."""
        tg_id   = _data_tg_id(data)
        watched = data.get("watched_funds", [])
        if not tg_id:
            _json(self, {"error": "telegram_id required"}, 400)
            return
        cfg = _load_cfg()
        profile = _find_profile(cfg, tg_id)
        if not profile:
            _json(self, {"error": "Profile không tìm thấy"}, 404)
            return
        all_codes = set(cfg.get("funds", {}).keys())
        valid = [c.upper() for c in watched if c.upper() in all_codes]
        if not valid:
            _json(self, {"error": "Không có mã hợp lệ"}, 400)
            return

        # GATE-003: free tier giới hạn FREE_FUND_LIMIT mã theo dõi. Admin + Pro bypass.
        if not _is_admin(tg_id) and _get_tier(tg_id).get("tier") != "pro" and len(valid) > FREE_FUND_LIMIT:
            _json(self, {
                "error": "pro_required",
                "upgrade_url": "/buy",
                "limit": FREE_FUND_LIMIT,
            }, 403)
            return

        db_backed = _db_mod is not None and _db_mod.is_available()
        if db_backed:
            try:
                _db_mod.set_watched_funds(tg_id, valid)
            except Exception as e:
                log.error(f"[miniapp] set_watched_funds DB lỗi: {e}")
                _json(self, {"error": "Lỗi lưu vào DB"}, 500)
                return
        else:
            profile["watched_funds"] = valid
            _save_cfg(cfg)
        _json(self, {"ok": True, "watched_funds": valid})

    def _api_list_alerts(self, qs: dict):
        """GET /api/alerts?user_id=... — PRO-004, danh sách cảnh báo đang bật của user."""
        tg_id = _qs_tg_id(qs)
        if not _auth_write(self, tg_id):
            return
        if not _check_tier(self, tg_id, "pro"):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"alerts": []})
            return
        try:
            alerts = _db_mod.list_alerts(tg_id)
        except Exception as e:
            log.error(f"[miniapp] list_alerts lỗi: {e}")
            _json(self, {"error": "Lỗi đọc cảnh báo"}, 500)
            return
        _json(self, {"alerts": alerts})

    def _api_create_alert(self, data: dict):
        """POST /api/alerts — PRO-004, tạo cảnh báo mới cho 1 quỹ."""
        tg_id     = str(data.get("telegram_id", ""))
        fund_code = str(data.get("fund_code", "")).upper()
        condition = str(data.get("condition", ""))
        threshold = data.get("threshold")
        if not tg_id or not fund_code or not condition:
            _json(self, {"error": "telegram_id, fund_code, condition required"}, 400)
            return
        if condition not in ("nav_up", "nav_down", "signal_buy", "signal_sell"):
            _json(self, {"error": "condition không hợp lệ"}, 400)
            return
        if condition in ("nav_up", "nav_down"):
            try:
                threshold = float(threshold)
                assert threshold > 0
            except (TypeError, ValueError, AssertionError):
                _json(self, {"error": "threshold phải là số dương (%)"}, 400)
                return
        else:
            threshold = None
        if not _auth_write(self, tg_id):
            return
        tg_id = _data_tg_id(data)
        if not _check_tier(self, tg_id, "pro"):
            return
        cfg = _load_cfg()
        if fund_code not in cfg.get("funds", {}):
            _json(self, {"error": f"Mã quỹ không hợp lệ: {fund_code}"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            alert = _db_mod.create_alert(tg_id, fund_code, condition, threshold)
            _json(self, {"ok": True, "alert": alert})
        except Exception as e:
            log.error(f"[miniapp] create_alert lỗi: {e}")
            _json(self, {"error": "Lỗi tạo cảnh báo"}, 500)

    def _api_delete_alert(self, alert_id: str, data: dict):
        """DELETE /api/alerts/<id> — PRO-004, tắt (soft-delete) 1 cảnh báo."""
        tg_id = str(data.get("telegram_id", ""))
        if not tg_id or not alert_id.isdigit():
            _json(self, {"error": "telegram_id + alert id required"}, 400)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            ok = _db_mod.delete_alert(alert_id, tg_id)
        except Exception as e:
            log.error(f"[miniapp] delete_alert lỗi: {e}")
            _json(self, {"error": "Lỗi xóa cảnh báo"}, 500)
            return
        if not ok:
            _json(self, {"error": "Không tìm thấy cảnh báo"}, 404)
            return
        _json(self, {"ok": True})

    def _api_t2_accuracy(self, code: str, qs: dict):
        """GET /api/t2/accuracy/<code>?user_id=...&model=... — T2-010, yêu cầu tier=pro.
        Trả {summary:[{model_version,mape_7d,n_7d,mape_30d,n_30d,mape_all,n_all}],
             history:[{predicted_for_date,predicted_nav,actual_nav,error_pct,model_version}]}."""
        if not code or len(code) > 10:
            _json(self, {"error": "Invalid code"}, 400)
            return
        tg_id = _qs_tg_id(qs)
        if not _auth_write(self, tg_id):
            return
        if not _check_tier(self, tg_id, "pro"):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"summary": [], "history": []})
            return
        model = (qs.get("model") or [None])[0]
        try:
            summary = _db_mod.get_accuracy_summary(code)
            history = _db_mod.get_accuracy_history(code, model_version=model, limit=60)
        except Exception as e:
            log.error(f"[miniapp] t2_accuracy {code} lỗi: {e}")
            _json(self, {"error": "Lỗi đọc dữ liệu độ chính xác"}, 500)
            return
        _json(self, {"summary": summary, "history": history})

    def _api_research(self, code: str, qs: dict):
        """Phân tích sâu 5 trường phái cho 1 quỹ — PRO-001, yêu cầu tier=pro."""
        if not code or len(code) > 10:
            _json(self, {"error": "Invalid code"}, 400)
            return
        tg_id = _qs_tg_id(qs)
        if not _auth_write(self, tg_id):
            return
        if not _check_tier(self, tg_id, "pro"):
            return
        cfg = _load_cfg()
        sigs = _get_signals_for_codes([code], cfg)
        d    = sigs.get(code, {})
        if not d or not d.get("nav"):
            _json(self, {"error": f"Không có dữ liệu cho {code}"}, 404)
            return

        # Tính extended stats (52w high/low, vol, drawdown) + full indicator set
        # (stoch, cci, roc, sharpe, sortino, volatility, max_dd, golden cross) — tính
        # LIVE từ NAV series thay vì phụ thuộc buy_signals đã lưu, vì các chỉ số này
        # không được persist vào DB (chỉ dùng nội bộ để tính score).
        stats = {}
        live  = {}
        pts   = []
        if _BOT_IMPORTED:
            try:
                from bot import get_nav_series as _gnv, compute_research_stats
                pts = _gnv(code, _FUND_CATALOG.get(code, cfg.get("funds", {}).get(code, {})), cfg) or []
                if pts:
                    stats = compute_research_stats(pts)
                    live  = _calc_signal_bot(code, pts)
            except Exception as e:
                log.warning(f"[research] extended_stats {code}: {e}")

        nav  = d.get("nav", 0)
        rsi  = d.get("rsi")
        bb   = d.get("bb_pct")
        sc   = d.get("score", 0)
        ma20 = d.get("ma20") or 0
        ma50 = d.get("ma50") or 0
        chg30 = d.get("chg30")
        macd  = d.get("macd_hist")
        sig   = d.get("signal", "N/A")

        stoch_k    = live.get("stoch_k")
        stoch_d    = live.get("stoch_d")
        cci        = live.get("cci")
        roc        = live.get("roc")
        sharpe     = live.get("sharpe")
        sortino    = live.get("sortino")
        volatility = live.get("volatility")
        gc_type    = live.get("gc_type")

        pct_from_high = stats.get("pct_from_high", 0)
        pct_from_low  = stats.get("pct_from_low",  0)
        pos_in_range  = stats.get("pos_in_range",  50)
        nav_52w_high  = stats.get("nav_52w_high",  nav)
        nav_52w_low   = stats.get("nav_52w_low",   nav)
        vol_30d       = stats.get("vol_30d")
        max_dd        = stats.get("max_drawdown",  0)
        chg365        = stats.get("chg365")

        # ─ Technical ─
        if   sc >= 6:  ta_v = "MUA MẠNH 🟢🟢"
        elif sc >= 3:  ta_v = "MUA 🟢"
        elif sc <= -6: ta_v = "BÁN MẠNH 🔴🔴"
        elif sc <= -3: ta_v = "BÁN 🔴"
        else:          ta_v = "TRUNG TÍNH ⚪"

        def rsi_note(r):
            if r is None: return None
            if r < 30:  return f"{r:.1f} — Quá bán mạnh 🟢🟢"
            if r < 40:  return f"{r:.1f} — Vùng quá bán 🟢"
            if r > 75:  return f"{r:.1f} — Quá mua mạnh 🔴🔴"
            if r > 65:  return f"{r:.1f} — Vùng quá mua 🔴"
            return f"{r:.1f} — Trung tính ⚪"

        def bb_note(b):
            if b is None: return None
            if b < 10:  return f"{b:.0f}% — Đáy dải Bollinger 🟢🟢"
            if b < 20:  return f"{b:.0f}% — Gần đáy dải 🟢"
            if b > 90:  return f"{b:.0f}% — Đỉnh dải Bollinger 🔴🔴"
            if b > 80:  return f"{b:.0f}% — Gần đỉnh dải 🔴"
            return f"{b:.0f}% — Vùng giữa ⚪"

        def stoch_note(k, d_):
            if k is None or d_ is None: return None
            if k < 20 and d_ < 20:  return f"%K {k:.0f} / %D {d_:.0f} — Quá bán 🟢"
            if k > 80 and d_ > 80:  return f"%K {k:.0f} / %D {d_:.0f} — Quá mua 🔴"
            return f"%K {k:.0f} / %D {d_:.0f} — Trung tính ⚪"

        def cci_note(c):
            if c is None: return None
            if c < -100: return f"{c:.0f} — Quá bán 🟢"
            if c > 100:  return f"{c:.0f} — Quá mua 🔴"
            return f"{c:.0f} — Trung tính ⚪"

        def roc_note(r):
            if r is None: return None
            if r < -5: return f"{r:.1f}% — Đà giảm mạnh 🟢 (cơ hội dip)"
            if r > 5:  return f"+{r:.1f}% — Đà tăng mạnh ⚠️"
            return f"{'+' if r>=0 else ''}{r:.1f}% — Đà trung tính ⚪"

        def gc_note(g):
            return {
                "golden": "Golden Cross 🟢🟢 — MA20 vừa cắt lên MA50",
                "death":  "Death Cross 🔴🔴 — MA20 vừa cắt xuống MA50",
                "above":  "MA20 > MA50 — xu hướng tăng ↑",
                "below":  "MA20 < MA50 — xu hướng giảm ↓",
            }.get(g)

        def sharpe_note(s):
            if s is None: return None
            if s > 1:   return f"{s:.2f} — Tốt 🟢 (lợi nhuận bù đắp rủi ro tốt)"
            if s < 0:   return f"{s:.2f} — Kém 🔴 (rủi ro không được bù đắp)"
            return f"{s:.2f} — Trung bình ⚪"

        # ─ Value ─
        if   pct_from_low < 5:      val_v = "RẤT RẺ — Gần đáy 52 tuần 🟢🟢"
        elif pct_from_low < 15:     val_v = "RẺ — Vùng tích lũy tốt 🟢"
        elif pct_from_high > -5:    val_v = "ĐẮT — Gần đỉnh 52 tuần 🔴"
        elif pos_in_range > 70:     val_v = "TRUNG BÌNH CAO ⚠️"
        else:                        val_v = "TRUNG BÌNH ⚪"

        # ─ Momentum ─
        up_trend = bool(ma20 and ma50 and ma20 > ma50)
        if chg30 is not None and ma20 and ma50:
            if chg30 > 2 and up_trend:       mom_v = "TĂNG MẠNH — Đà và xu hướng tốt 🟢"
            elif chg30 < -2 and not up_trend: mom_v = "GIẢM — Không bắt đáy vội 🔴"
            elif up_trend:                    mom_v = "TĂNG NHẸ — Xu hướng tích cực ⚪"
            else:                             mom_v = "PHÂN KỲ — Đà ngắn hạn suy yếu ⚠️"
        else:
            mom_v = "Không đủ dữ liệu"

        # ─ DCA ─
        below_ma50 = bool(ma50 and nav < ma50)
        oversold   = rsi is not None and rsi < 45
        if below_ma50 and oversold:   dca_v = "TỐT NHẤT — Dưới MA50 + RSI quá bán 🟢🟢"
        elif below_ma50 or oversold:  dca_v = "PHÙ HỢP — Giá hợp lý để tích lũy dần 🟢"
        elif pct_from_high > -5:      dca_v = "NÊN CHỜ — NAV gần đỉnh 52 tuần ⚠️"
        else:                          dca_v = "TRUNG TÍNH — Theo kế hoạch DCA ⚪"

        # ─ Risk ─
        if vol_30d is not None:
            if vol_30d < 4:    risk_v = "THẤP 🟢"
            elif vol_30d < 10: risk_v = "TRUNG BÌNH 🟡"
            else:              risk_v = "CAO 🔴"
        else:
            risk_v = "Chưa đủ dữ liệu"

        fund_name = cfg.get("funds", {}).get(code, {}).get("name", "")

        # Vị thế cá nhân — CHỈ hiển thị, không dùng để tính signal/score (signal luôn
        # thuần kỹ thuật, giống nhau cho mọi user xem cùng 1 mã).
        position = None
        if tg_id:
            for h in _db_get_ccq_holdings(tg_id):
                if h["code"] == code:
                    units, avg_cost = h["units"], h["avg_cost"]
                    pnl_pct = (nav / avg_cost - 1) * 100 if avg_cost else 0
                    position = {
                        "units": units, "avg_cost": avg_cost,
                        "current_value": round(nav * units, 0),
                        "pnl": round((nav - avg_cost) * units, 0),
                        "pnl_pct": round(pnl_pct, 2),
                    }
                    break

        # Trả về 90 điểm NAV gần nhất cho sparkline — pts đã có sẵn trong memory
        try:
            nav_series = [{"date": str(p[0])[:10], "nav": float(p[1])} for p in pts[-90:] if p[1] is not None]
        except Exception:
            nav_series = []

        _json(self, {
            "code": code, "fund_name": fund_name,
            "nav": nav, "nav_date": d.get("nav_date",""),
            "signal": sig, "score": sc, "chg_pct": d.get("chg_pct", 0),
            "position": position,
            "nav_series": nav_series,
            "technical": {
                "verdict": ta_v, "score": sc,
                "rsi": rsi_note(rsi), "bb": bb_note(bb),
                "macd": ("Dương — Đà tăng 🟢" if macd and macd>0 else "Âm — Đà giảm ⚠️") if macd is not None else None,
                "ma": (f"MA20 {'>' if ma20>ma50 else '<'} MA50 → {'Xu hướng tăng ↑' if ma20>ma50 else 'Xu hướng giảm ↓'}") if ma20 and ma50 else None,
                "stoch": stoch_note(stoch_k, stoch_d),
                "cci": cci_note(cci),
                "roc": roc_note(roc),
                "golden_cross": gc_note(gc_type),
                "details": d.get("details", []),
            },
            "value": {
                "verdict": val_v,
                "nav_52w_high": nav_52w_high, "nav_52w_low": nav_52w_low,
                "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
                "pos_in_range": pos_in_range, "chg365": chg365,
            },
            "momentum": {
                "verdict": mom_v, "chg30": chg30,
                "up_trend": up_trend, "ma20": ma20, "ma50": ma50,
            },
            "dca": {
                "verdict": dca_v, "below_ma50": below_ma50, "oversold": oversold,
            },
            "risk": {
                "verdict": risk_v, "vol_30d": vol_30d, "max_drawdown": max_dd,
                "sharpe": sharpe_note(sharpe), "sortino": round(sortino, 2) if sortino is not None else None,
                "volatility_1y": round(volatility, 2) if volatility is not None else None,
            },
        })

    def _api_nav_history(self, code: str):
        if not code or len(code) > 10:
            _json(self, {"error": "Invalid code"}, 400)
            return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not set"}, 503)
            return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT nav_date::text, nav::float
                    FROM nav_history WHERE fund_code = %s
                    ORDER BY nav_date
                """, (code,))
                rows = cur.fetchall()
            conn.close()
            _json(self, {"code": code, "data": [{"date": r[0], "nav": r[1]} for r in rows]})
        except Exception as e:
            _json(self, {"error": str(e)}, 500)

    def _api_dca(self, qs: dict):
        tg_id = _qs_tg_id(qs)
        if tg_id and not _auth_write(self, tg_id):
            return
        budget = float((qs.get("budget") or ["0"])[0])
        style  = (qs.get("style") or ["dca"])[0]
        cfg    = _load_cfg()
        profile = _find_profile(cfg, tg_id) if tg_id else None
        if not profile:
            _json(self, {"error": "Profile không tìm thấy"}, 404)
            return
        watched  = profile.get("watched_funds", [])
        signals  = _get_signals_for_codes(watched, cfg)
        result   = _calc_dca(profile, signals, budget, style)
        _json(self, result)

    def _api_add_trade(self, data: dict):
        """POST /api/trade — thêm CCQ trade vào PostgreSQL.
        Accept cả field names cũ (code/type/date) lẫn mới (fund_code/trade_type/trade_date).
        """
        tg_id    = str(data.get("telegram_id", ""))
        code     = str(data.get("fund_code") or data.get("code", "")).upper()
        tx_type  = str(data.get("trade_type") or data.get("type", "")).lower()
        units    = float(data.get("units", 0))
        amount   = float(data.get("amount", 0))
        tx_date  = str(data.get("trade_date") or data.get("date") or date.today().isoformat())
        nav_mm   = bool(data.get("nav_mismatch", False))
        note     = str(data.get("note", ""))
        is_dividend = tx_type == "dividend"
        # For dividend: nav may be 0 (cash dividend) or derived from amount/units
        nav      = float(data.get("price_per_unit", 0)) or (amount / units if units > 0 else 0)
        if not tg_id or not code or tx_type not in ("buy", "sell", "dividend"):
            _json(self, {"error": "Thiếu hoặc sai thông tin giao dịch"}, 400); return
        if not is_dividend and (units <= 0 or amount <= 0):
            _json(self, {"error": "Thiếu hoặc sai thông tin giao dịch"}, 400); return
        if is_dividend and units <= 0 and amount <= 0:
            _json(self, {"error": "Lợi tức cần có số CCQ hoặc số tiền"}, 400); return
        if not _auth_write(self, tg_id): return
        tg_id = _data_tg_id(data)
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_ccq_trades
                      (telegram_id, code, type, trade_date, units, nav, amount, note, nav_mismatch)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, [tg_id, code, tx_type, tx_date, round(units,4), round(nav,2),
                      round(amount), note, nav_mm])
                new_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.ccq.add", "user_ccq_trades", str(new_id),
                               after={"code": code, "type": tx_type, "units": units, "amount": amount})
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "id": new_id, "code": code, "type": tx_type,
                     "units": units, "amount": amount, "nav_mismatch": nav_mm})

    def _api_get_trades(self, qs: dict):
        """GET /api/trades?user_id=... — trả về CCQ trades từ DB."""
        tg_id = _qs_tg_id(qs, "telegram_id")
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400); return
        if not _auth_write(self, tg_id): return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, code, type, trade_date::text, units, nav, amount, note, nav_mismatch
                    FROM user_ccq_trades
                    WHERE telegram_id = %s
                    ORDER BY trade_date DESC, id DESC
                """, [tg_id])
                rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        trades = [
            {"index": r[0], "telegram_id": tg_id, "code": r[1], "type": r[2],
             "date": r[3], "units": r[4], "nav": r[5], "price_per_unit": r[5],
             "amount": r[6], "note": r[7], "nav_mismatch": r[8]}
            for r in rows
        ]
        _json(self, {"trades": trades})

    def _api_delete_trade(self, raw_idx: str, data: dict):
        """DELETE /api/trade/<id> — xóa CCQ trade từ DB (chỉ chủ sở hữu)."""
        try:
            trade_id = int(raw_idx)
        except (ValueError, TypeError):
            _json(self, {"error": "Invalid id"}, 400); return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id FROM user_ccq_trades WHERE id=%s", [trade_id])
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if not row:
            _json(self, {"error": "Giao dịch không tồn tại"}, 404); return
        tg_id = row[0]
        if not _auth_write(self, tg_id): return
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_ccq_trades WHERE id=%s", [trade_id])
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.ccq.delete", "user_ccq_trades", str(trade_id))
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "deleted_id": trade_id})

    def _api_edit_trade(self, raw_idx: str, data: dict):
        """POST /api/trade/<id> — sửa CCQ trade trong DB (chỉ chủ sở hữu)."""
        try:
            trade_id = int(raw_idx)
        except (ValueError, TypeError):
            _json(self, {"error": "Invalid id"}, 400); return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id, units, nav, amount, trade_date::text, type, note, nav_mismatch FROM user_ccq_trades WHERE id=%s", [trade_id])
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if not row:
            _json(self, {"error": "Giao dịch không tồn tại"}, 404); return
        tg_id = row[0]
        if not _auth_write(self, tg_id): return
        units  = float(data.get("units",  row[1]))
        nav    = float(data.get("price_per_unit", row[2]))
        amount = float(data.get("amount", row[3])) or units * nav
        tx_date= str(data.get("date",  row[4]))
        tx_type= str(data.get("type",  row[5])).lower()
        note   = str(data.get("note",  row[6] or ""))
        nav_mm = bool(data.get("nav_mismatch", row[7]))
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_ccq_trades
                    SET units=%s, nav=%s, amount=%s, trade_date=%s, type=%s, note=%s, nav_mismatch=%s
                    WHERE id=%s
                """, [round(units,4), round(nav,2), round(amount), tx_date, tx_type, note, nav_mm, trade_id])
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.ccq.edit", "user_ccq_trades", str(trade_id),
                               before={"units": row[1], "nav": row[2], "amount": row[3], "date": row[4], "type": row[5]},
                               after={"units": units, "nav": nav, "amount": amount, "date": tx_date, "type": tx_type})
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "id": trade_id})

    # ── Gold APIs ────────────────────────────────────────────────────────────────

    def _api_gold(self, qs: dict):
        """GET /api/gold?user_id=... — giá vàng mới nhất + tín hiệu + portfolio."""
        tg_id = _qs_tg_id(qs)
        if tg_id and not _auth_write(self, tg_id):
            return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        prices = {}
        if db_url:
            try:
                import psycopg2
                conn = psycopg2.connect(db_url, connect_timeout=8)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT ON (source, product)
                               source, product, buy_price::float, sell_price::float,
                               price_date::text, currency, extra
                        FROM gold_prices
                        WHERE price_date >= CURRENT_DATE - INTERVAL '7 days'
                        ORDER BY source, product, price_date DESC
                    """)
                    rows = cur.fetchall()
                conn.close()
                # key = "SOURCE:PRODUCT", e.g. "SJC:SJC_1L", "DOJI:DOJI_NHAN"
                for src, prod, buy, sell, dt, curr, extra in rows:
                    key = f"{src}:{prod}"
                    prices[key] = {
                        "source": src, "product": prod,
                        "buy": buy, "sell": sell,
                        "date": dt, "currency": curr,
                        "extra": extra or {},
                        "label": _gold_product_label(src, prod),
                    }
            except Exception as e:
                prices = {"error": str(e)}

        # Tính signals từ lịch sử SJC (60 ngày gần nhất, mọi nguồn — xem _calc_gold_signals)
        signals = _calc_gold_signals(db_url) if db_url else {}

        # Portfolio vàng — tính riêng theo từng product user đang nắm (xem _calc_gold_portfolio)
        portfolio = None
        if tg_id:
            cfg = _load_cfg()
            portfolio = _calc_gold_portfolio(cfg, tg_id, prices)

        _json(self, {
            "prices":    prices,
            "signals":   signals,
            "portfolio": portfolio,
            "updated":   datetime.now().isoformat(),
        })

    def _api_gold_history(self, qs: dict):
        """GET /api/gold/history?source=SJC&product=SJC_1L&days=90 — lịch sử giá vàng."""
        source  = (qs.get("source")  or ["SJC"])[0].upper()
        product = (qs.get("product") or ["SJC_1L"])[0]
        days    = int((qs.get("days") or ["90"])[0])
        db_url  = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not set"}, 503)
            return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT price_date::text, buy_price::float, sell_price::float, extra
                    FROM gold_prices
                    WHERE source = %s AND product = %s
                      AND price_date >= CURRENT_DATE - INTERVAL %s
                    ORDER BY price_date
                """, (source, product, f"{days} days"))
                rows = cur.fetchall()
            conn.close()
            data = [{"date": r[0], "buy": r[1], "sell": r[2],
                     "extra": r[3] or {}} for r in rows]
            _json(self, {"source": source, "product": product, "data": data})
        except Exception as e:
            _json(self, {"error": str(e)}, 500)

    def _api_gold_chart(self, qs: dict):
        """GET /api/gold/chart?days=365 — all 4 series for gold chart in one call.
        Returns: sjc_buy[], sjc_sell[], xau_usd[], xau_vnd[], usd_vnd (latest)
        """
        days = int((qs.get("days") or ["0"])[0])
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not set"}, 503); return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                _all_sources = "('SJC','GIAVANG_ORG','INTERNATIONAL','VANGTODAYAPI','DOJI_SCRAPE')"
                if days > 0:
                    cur.execute(f"""
                        SELECT source, product, price_date::text, buy_price::float, sell_price::float, extra
                        FROM gold_prices
                        WHERE price_date >= CURRENT_DATE - INTERVAL %s
                          AND source IN {_all_sources}
                        ORDER BY price_date
                    """, (f"{days} days",))
                else:
                    cur.execute(f"""
                        SELECT source, product, price_date::text, buy_price::float, sell_price::float, extra
                        FROM gold_prices
                        WHERE source IN {_all_sources}
                        ORDER BY price_date
                    """)
                rows = cur.fetchall()
            conn.close()
            # Priority: VANGTODAYAPI=2 > SJC=1 > GIAVANG_ORG=0 (cho cùng ngày)
            _SJC_PRIORITY = {"VANGTODAYAPI": 2, "DOJI_SCRAPE": 2, "SJC": 1, "GIAVANG_ORG": 0}
            sjc_map = {}   # date -> {buy, sell, priority}
            xau_usd_pts, xau_vnd_pts = [], []
            usd_vnd_latest = None
            for src, prod, dt, buy, sell, extra in rows:
                if prod == "SJC_1L" and src in _SJC_PRIORITY:
                    priority = _SJC_PRIORITY[src]
                    if dt not in sjc_map or priority > sjc_map[dt]["p"]:
                        sjc_map[dt] = {"buy": buy, "sell": sell, "p": priority}
                elif src == "INTERNATIONAL" and prod == "XAU_USD":
                    xau_usd_pts.append({"date": dt, "val": buy})
                    if extra and "usd_vnd" in extra:
                        usd_vnd_latest = extra["usd_vnd"]
                elif src == "INTERNATIONAL" and prod == "XAU_VND_LUONG":
                    xau_vnd_pts.append({"date": dt, "val": buy})
                elif src == "VANGTODAYAPI" and prod == "XAUUSD" and buy:
                    # XAUUSD từ vang.today — dùng khi không có INTERNATIONAL
                    if extra and "usd_vnd" in extra:
                        usd_vnd_latest = extra.get("usd_vnd") or usd_vnd_latest
                    if extra and extra.get("xau_vnd_luong"):
                        xau_vnd_pts.append({"date": dt, "val": extra["xau_vnd_luong"]})
            sjc_buy  = [{"date": dt, "val": v["buy"]}  for dt, v in sorted(sjc_map.items())]
            sjc_sell = [{"date": dt, "val": v["sell"]} for dt, v in sorted(sjc_map.items())]
            _json(self, {
                "sjc_buy": sjc_buy, "sjc_sell": sjc_sell,
                "xau_usd": xau_usd_pts, "xau_vnd": xau_vnd_pts,
                "usd_vnd": usd_vnd_latest, "days": days
            })
        except Exception as e:
            _json(self, {"error": str(e)}, 500)

    def _api_get_gold_trades(self, qs: dict):
        """GET /api/gold/trades?user_id=... — đọc từ PostgreSQL."""
        tg_id = _qs_tg_id(qs)
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400); return
        if not _auth_write(self, tg_id): return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, product, type, trade_date::text, unit, qty, qty_luong,
                           price_per_luong, total_vnd, note,
                           COALESCE(name, '') AS name
                    FROM user_gold_trades
                    WHERE telegram_id = %s
                    ORDER BY trade_date DESC, id DESC
                """, [tg_id])
                rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        trades = [
            {"index": r[0], "telegram_id": tg_id, "product": r[1], "type": r[2],
             "date": r[3], "unit": r[4], "qty": r[5], "qty_luong": r[6],
             "price_per_luong": r[7], "total_vnd": r[8], "note": r[9], "name": r[10]}
            for r in rows
        ]
        _json(self, {"trades": trades})

    def _api_add_gold_trade(self, data: dict):
        """POST /api/gold/trade — thêm giao dịch vàng vào PostgreSQL.
        Accept cả field names cũ (type/qty/price_per_luong/date) lẫn mới
        (trade_type/units/price/trade_date/name) từ web_js.js mới.
        """
        tg_id   = str(data.get("telegram_id", ""))
        tx_type = str(data.get("trade_type") or data.get("type", "")).lower()
        unit    = str(data.get("unit", "luong")).lower()
        product = str(data.get("product", "SJC_1L"))
        qty     = float(data.get("qty") or data.get("units") or 0)
        price   = float(data.get("price_per_luong") or data.get("price") or 0)
        total   = float(data.get("total_vnd", 0)) or round(qty * price * _unit_to_luong(unit))
        tx_date = str(data.get("trade_date") or data.get("date") or date.today().isoformat())
        note    = str(data.get("note", ""))
        if not all([tg_id, tx_type in ("buy", "sell"), qty > 0, price > 0]):
            _json(self, {"error": "Thiếu hoặc sai thông tin"}, 400); return
        if not _auth_write(self, tg_id): return
        tg_id = _data_tg_id(data)
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                gold_name = str(data.get("name", ""))[:100]
                cur.execute("""
                    INSERT INTO user_gold_trades
                      (telegram_id, product, type, trade_date, unit, qty, qty_luong,
                       price_per_luong, total_vnd, note, name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, [tg_id, product, tx_type, tx_date, unit,
                      round(qty,4), round(qty * _unit_to_luong(unit),4),
                      round(price), round(total), note, gold_name])
                new_id = cur.fetchone()[0]
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.gold.add", "user_gold_trades", str(new_id),
                               after={"product": product, "type": tx_type, "qty": qty, "total_vnd": total})
        _json(self, {"ok": True, "id": new_id, "type": tx_type, "qty": qty,
                     "price_per_luong": price, "total_vnd": total})

    def _api_edit_gold_trade(self, raw_idx: str, data: dict):
        """POST /api/gold/trade/<id> — sửa giao dịch vàng (chỉ chủ sở hữu)."""
        try:
            trade_id = int(raw_idx)
        except (ValueError, TypeError):
            _json(self, {"error": "Invalid id"}, 400); return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id, unit, qty, price_per_luong, total_vnd, trade_date::text, type, note, name FROM user_gold_trades WHERE id=%s", [trade_id])
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if not row:
            _json(self, {"error": "Giao dịch không tồn tại"}, 404); return
        tg_id = row[0]
        if not _auth_write(self, tg_id): return
        unit  = str(data.get("unit",  row[1])).lower()
        qty   = float(data.get("qty",  row[2]))
        price = float(data.get("price_per_luong", row[3]))
        total = float(data.get("total_vnd", 0)) or round(qty * price * _unit_to_luong(unit))
        tx_date = str(data.get("date", row[5]))
        tx_type = str(data.get("type", row[6])).lower()
        note    = str(data.get("note", row[7] or ""))
        gold_name = str(data.get("name", row[8] or ""))[:100]
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_gold_trades
                    SET unit=%s, qty=%s, qty_luong=%s, price_per_luong=%s,
                        total_vnd=%s, trade_date=%s, type=%s, note=%s, name=%s
                    WHERE id=%s
                """, [unit, round(qty,4), round(qty*_unit_to_luong(unit),4),
                      round(price), round(total), tx_date, tx_type, note, gold_name, trade_id])
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.gold.edit", "user_gold_trades", str(trade_id),
                               before={"qty": row[2], "price_per_luong": row[3], "total_vnd": row[4], "type": row[6], "name": row[8]},
                               after={"qty": qty, "price_per_luong": price, "total_vnd": total, "type": tx_type, "name": gold_name})
        _json(self, {"ok": True, "id": trade_id})

    def _api_delete_gold_trade(self, raw_idx: str, data: dict):
        """DELETE /api/gold/trade/<id> — xóa giao dịch vàng (chỉ chủ sở hữu)."""
        try:
            trade_id = int(raw_idx)
        except (ValueError, TypeError):
            _json(self, {"error": "Invalid id"}, 400); return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id FROM user_gold_trades WHERE id=%s", [trade_id])
                row = cur.fetchone()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if not row:
            _json(self, {"error": "Giao dịch không tồn tại"}, 404); return
        tg_id = row[0]
        if not _auth_write(self, tg_id): return
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_gold_trades WHERE id=%s", [trade_id])
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        if _db_mod is not None:
            _db_mod.log_audit(tg_id, "trade.gold.delete", "user_gold_trades", str(trade_id))
        _json(self, {"ok": True, "deleted_id": trade_id})

    def _api_fed_rate(self):
        """GET /api/fed-rate — lấy lãi suất Fed từ Yahoo Finance server-side (tránh CORS)."""
        import urllib.request as _urlreq
        urls = [
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EIRX?interval=1d&range=5d",
            "https://query2.finance.yahoo.com/v8/finance/chart/%5EIRX?interval=1d&range=5d",
        ]
        for url in urls:
            try:
                req = _urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with _urlreq.urlopen(req, timeout=8) as resp:
                    import json as _json_mod
                    d = _json_mod.loads(resp.read())
                rate = d.get("chart", {}).get("result", [{}])[0].get("meta", {}).get("regularMarketPrice")
                if rate is not None:
                    _json(self, {"rate": round(float(rate), 2), "source": "Yahoo ^IRX"})
                    return
            except Exception:
                continue
        _json(self, {"error": "Không lấy được lãi suất Fed"}, 503)

    def _api_admin_nav_pending(self, qs: dict):
        """GET /api/admin/nav/pending — danh sách NAV pending_confirm cần admin xác nhận."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"pending": []})
            return
        _json(self, {"pending": _db_mod.get_pending_confirms()})

    def _api_version(self, qs: dict):
        """GET /api/version?user_id=... — chỉ admin xem được commit hash đang
        chạy (dùng để xác nhận deploy mới nhất, không phải image cũ). Ẩn với
        user thường — không có lý do gì để họ thấy chi tiết hạ tầng/mã nguồn."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        _json(self, {"version": _SERVER_VERSION, "ts": datetime.now().isoformat()})

    def _api_admin_audit(self, qs: dict):
        """GET /api/admin/audit?user_id=&action=&actor_id=&limit= — xem audit log
        gần đây cho admin dashboard (GOV-004). Read-only, không cho phép sửa/xoá."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"log": []})
            return
        action = (qs.get("action") or [None])[0]
        actor_id = (qs.get("actor_id") or [None])[0]
        try:
            limit = min(max(int((qs.get("limit") or ["100"])[0]), 1), 500)
        except ValueError:
            limit = 100
        try:
            rows = _db_mod.get_audit_log(limit=limit, action=action, actor_id=actor_id)
        except Exception as e:
            log.error(f"[admin_audit] {e}")
            _json(self, {"error": "Lỗi đọc audit log"}, 500)
            return
        _json(self, {"log": rows})

    def _api_admin_summary(self, qs: dict):
        """GET /api/admin/summary?user_id=... — dashboard tổng hợp cho admin (GOV-004
        phần còn thiếu): user theo tier, MAPE model 7 ngày gần nhất, quỹ chưa có NAV hôm
        nay, giao dịch thanh toán gần đây. Read-only."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"users": {}, "model_mape": [], "funds_missing_today": [], "recent_payments": []})
            return
        try:
            _json(self, _db_mod.get_admin_summary())
        except Exception as e:
            log.error(f"[admin_summary] {e}")
            _json(self, {"error": "Lỗi tổng hợp dashboard"}, 500)

    def _api_referral_mine(self, qs: dict):
        """GET /api/referral/mine?user_id=... — mã giới thiệu cá nhân + số người đã dùng.
        Ai nhập mã này sẽ được +30 ngày Pro, và chủ mã (referrer) cũng được +30 ngày."""
        tg_id = _qs_tg_id(qs)
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            code = _db_mod.get_or_create_referral_code(tg_id)
            stats = _db_mod.get_referral_stats(tg_id)
        except Exception as e:
            log.error(f"[referral] {tg_id}: {e}")
            _json(self, {"error": "Lỗi tạo mã giới thiệu"}, 500)
            return
        _json(self, {"code": code, "uses_count": stats.get("uses_count", 0)})

    def _api_promo_redeem(self, data: dict):
        """POST /api/promo/redeem — {telegram_id, code}. Áp dụng mã trial/giảm giá
        hoặc mã giới thiệu — cộng dồn ngày Pro (không reset), 1 mã/1 tài khoản."""
        tg_id = str(data.get("telegram_id", ""))
        code  = str(data.get("code", ""))
        if not tg_id or not code:
            _json(self, {"error": "telegram_id và code là bắt buộc"}, 400)
            return
        if not _auth_write(self, tg_id):
            return
        tg_id = _data_tg_id(data)
        if _check_promo_abuse(tg_id):
            log.warning(f"[promo_redeem][ABUSE] {tg_id} thử >{PROMO_ABUSE_MAX_ATTEMPTS} mã trong {PROMO_ABUSE_WINDOW_SEC}s")
            if _db_mod is not None and _db_mod.is_available():
                _db_mod.log_audit(tg_id, "promo_abuse_detected", "promo_codes", code,
                                   note=f">{PROMO_ABUSE_MAX_ATTEMPTS} lần thử mã trong {PROMO_ABUSE_WINDOW_SEC}s")
            _notify_admin_promo_abuse(tg_id)
            _json(self, {"error": "Quá nhiều lần thử mã, vui lòng thử lại sau"}, 429)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            result = _db_mod.redeem_promo_code(code, tg_id)
            # GOV-017: mã Promo (free ngày, không cần mua) giờ được tạo trong
            # discount_codes (requires_purchase=false) chứ không còn promo_codes
            # — nếu không tìm thấy trong promo_codes (referral + legacy admin),
            # thử tiếp bên discount_codes trước khi báo lỗi "không tồn tại".
            if not result.get("ok") and result.get("error") == "Mã không tồn tại":
                result = _db_mod.redeem_instant_discount_code(code, tg_id)
        except Exception as e:
            log.error(f"[promo_redeem] {tg_id} code={code}: {e}")
            _json(self, {"error": "Lỗi áp dụng mã"}, 500)
            return
        if not result.get("ok"):
            _json(self, {"error": result.get("error", "Mã không hợp lệ")}, 400)
            return
        # GOV-010: nhiều tài khoản khác nhau redeem cùng 1 mã referral trong thời
        # gian ngắn là dấu hiệu sybil farm — cap 1 lần/30 ngày đã chặn được phần
        # lớn giá trị kinh tế, nhưng vẫn cảnh báo admin để có thể ban thủ công nếu
        # cần (referrer_bonus_days=0 không có nghĩa là an toàn, cooldown có thể
        # đang bị lợi dụng để "test" trước khi tấn công quy mô lớn hơn).
        if result.get("recent_redemptions_24h", 0) >= REFERRAL_SYBIL_ALERT_THRESHOLD:
            _notify_admin_referral_sybil(code, result.get("referrer_id"), result["recent_redemptions_24h"])
        _json(self, result)

    def _api_admin_promo_list(self, qs: dict):
        """GET /api/admin/promo/list?user_id=... — admin xem tất cả mã trial/giảm giá đã tạo."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"codes": []})
            return
        _json(self, {"codes": _db_mod.list_promo_codes()})

    def _api_admin_promo_create(self, data: dict):
        """POST /api/admin/promo/create — {telegram_id, days, max_uses, note, code?}.
        Admin tạo mã trial (vd 30-90 ngày cho bạn bè), max_uses giới hạn tổng số lượt
        dùng (None = không giới hạn số NGƯỜI, nhưng mỗi người vẫn chỉ dùng được 1 lần)."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        try:
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            _json(self, {"error": "days phải là số nguyên"}, 400)
            return
        if days <= 0 or days > 365:
            _json(self, {"error": "days phải trong khoảng 1-365"}, 400)
            return
        max_uses_raw = data.get("max_uses")
        max_uses = None
        if max_uses_raw not in (None, "", 0):
            try:
                max_uses = int(max_uses_raw)
                if max_uses <= 0:
                    max_uses = None
            except (TypeError, ValueError):
                max_uses = None
        note = str(data.get("note", ""))[:200]
        custom_code = str(data.get("code", "")).strip() or None
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            promo = _db_mod.create_promo_code(days, max_uses, tg_id, note, code=custom_code)
        except Exception as e:
            log.error(f"[admin_promo_create] {e}")
            _json(self, {"error": "Không tạo được mã (có thể trùng mã đã tồn tại)"}, 500)
            return
        _json(self, {"ok": True, "promo": promo})

    def _api_admin_promo_deactivate(self, data: dict):
        """POST /api/admin/promo/deactivate — {telegram_id, code}."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        code = str(data.get("code", ""))
        if not code:
            _json(self, {"error": "code required"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        ok = _db_mod.deactivate_promo_code(code, actor_id=tg_id)
        _json(self, {"ok": ok})

    def _api_admin_promo_activate(self, data: dict):
        """POST /api/admin/promo/activate — {telegram_id, code} — bật lại mã đã vô hiệu hoá."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        code = str(data.get("code", ""))
        if not code:
            _json(self, {"error": "code required"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        ok = _db_mod.activate_promo_code(code, actor_id=tg_id)
        _json(self, {"ok": ok})

    def _api_admin_ban_user(self, data: dict):
        """POST /api/admin/user/ban — {telegram_id, target_id, reason} — khoá thủ
        công 1 tài khoản (GOV-010, dùng khi phát hiện fraud referral/promo qua
        cảnh báo Telegram). KHÔNG xoá tier/pro_expires_at đang có (GOV-006)."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        target = str(data.get("target_id", "")).strip()
        reason = str(data.get("reason", "")).strip()
        if not target:
            _json(self, {"error": "target_id required"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            result = _db_mod.ban_user(target, actor_id=tg_id, reason=reason)
        except Exception as e:
            _json(self, {"error": str(e)}, 400)
            return
        _json(self, {"ok": True, "user": result})

    def _api_admin_unban_user(self, data: dict):
        """POST /api/admin/user/unban — {telegram_id, target_id}."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        target = str(data.get("target_id", "")).strip()
        if not target:
            _json(self, {"error": "target_id required"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            result = _db_mod.unban_user(target, actor_id=tg_id)
        except Exception as e:
            _json(self, {"error": str(e)}, 400)
            return
        _json(self, {"ok": True, "user": result})

    def _api_admin_users(self, qs: dict):
        """GET /api/admin/users?user_id=...&q=<search> — danh sách users với tier + trade count.
        q tìm theo telegram_id (nếu là số) hoặc tên (ILIKE). Giới hạn 100 users."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"users": []})
            return
        q = (qs.get("q") or [""])[0].strip() or None
        _json(self, {"users": _db_mod.get_admin_users(q=q)})

    def _api_admin_banned_list(self, qs: dict):
        """GET /api/admin/user/banned-list?user_id=... — danh sách tài khoản đang bị khoá."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"banned": []})
            return
        _json(self, {"banned": _db_mod.list_banned_users()})

    def _api_admin_promo_edit(self, data: dict):
        """POST /api/admin/promo/edit — {telegram_id, code, days, max_uses, note}.
        Sửa số ngày/số lượt/ghi chú của mã đã tạo (không đổi mã, không reset lượt đã dùng)."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        code = str(data.get("code", "")).strip()
        if not code:
            _json(self, {"error": "code required"}, 400)
            return
        try:
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            _json(self, {"error": "days phải là số nguyên"}, 400)
            return
        if days <= 0 or days > 365:
            _json(self, {"error": "days phải trong khoảng 1-365"}, 400)
            return
        max_uses_raw = data.get("max_uses")
        max_uses = None
        if max_uses_raw not in (None, "", 0):
            try:
                max_uses = int(max_uses_raw)
                if max_uses <= 0:
                    max_uses = None
            except (TypeError, ValueError):
                max_uses = None
        note = str(data.get("note", ""))[:200]
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        promo = _db_mod.update_promo_code(code, days, max_uses, note, actor_id=tg_id)
        if not promo:
            _json(self, {"error": f"Không tìm thấy mã {code}"}, 404)
            return
        _json(self, {"ok": True, "promo": promo})

    def _parse_voucher_fields(self, data: dict):
        """Validate các field chung cho create/edit mã (GOV-017: 1 loại mã duy nhất,
        gộp Promo+Voucher cũ). Trả (fields_dict, None) nếu hợp lệ, hoặc (None, error_msg)
        nếu không. benefit_type='discount_pct' → benefit_value là % (1-100), CHỈ hợp lệ
        khi requires_purchase=true. benefit_type='bonus_days' → benefit_value là số ngày
        tặng thêm/tặng free (>=1, tối đa 365 cho an toàn)."""
        requires_purchase = bool(data.get("requires_purchase", True))
        benefit_type = str(data.get("benefit_type", "discount_pct")).strip().lower()
        if benefit_type not in ("discount_pct", "bonus_days"):
            return None, "benefit_type phải là discount_pct hoặc bonus_days"
        try:
            benefit_value = int(data.get("benefit_value"))
        except (TypeError, ValueError):
            return None, "benefit_value phải là số nguyên"
        if benefit_type == "discount_pct" and not (0 < benefit_value <= 100):
            return None, "Giảm % phải trong khoảng 1-100"
        if benefit_type == "bonus_days" and not (0 < benefit_value <= 365):
            return None, "Số ngày tặng thêm phải trong khoảng 1-365"
        auto_apply = bool(data.get("auto_apply", False))
        if not requires_purchase:
            if benefit_type != "bonus_days":
                return None, "Mã không yêu cầu mua hàng chỉ có thể tặng ngày Premium, không thể giảm giá %"
            if auto_apply:
                return None, "Mã không yêu cầu mua hàng không thể tự động áp dụng — user phải tự nhập mã"
        channel    = str(data.get("channel", "sepay")).strip().lower() or "sepay"
        if channel not in ("sepay", "stars", "all"):
            return None, "channel phải là sepay/stars/all"
        max_uses_raw = data.get("max_uses")
        max_uses = None
        if max_uses_raw not in (None, "", 0):
            try:
                max_uses = int(max_uses_raw)
                if max_uses <= 0:
                    max_uses = None
            except (TypeError, ValueError):
                max_uses = None
        valid_from  = data.get("valid_from")  or None
        valid_until = data.get("valid_until") or None
        note = str(data.get("note", ""))[:200]
        # Không cho phép cả thời gian VÀ số lượt đều "không giới hạn" cùng lúc —
        # bắt buộc ít nhất 1 điều kiện chặn để mã không thể chạy vô thời hạn/vô hạn lượt.
        if valid_until is None and max_uses is None:
            return None, "Phải giới hạn ít nhất 1: thời gian hiệu lực HOẶC số lượt — không thể để cả 2 không giới hạn"
        return {
            "benefit_type": benefit_type, "benefit_value": benefit_value,
            "auto_apply": auto_apply, "channel": channel,
            "valid_from": valid_from, "valid_until": valid_until,
            "max_uses": max_uses, "note": note, "requires_purchase": requires_purchase,
        }, None

    def _api_admin_discount_create(self, data: dict):
        """POST /api/admin/discount/create — {telegram_id, requires_purchase, benefit_type,
        benefit_value, auto_apply, channel?, valid_from?, valid_until?, max_uses?, note?, code?}.
        GOV-017: requires_purchase=true → cần giao dịch thật (giảm giá % hoặc tặng ngày
        sau khi thanh toán). requires_purchase=false → tặng ngày Premium NGAY, không cần mua
        (redeem qua /api/promo/redeem). auto_apply=true → tự động áp dụng mọi purchase
        kênh này (chỉ áp dụng khi requires_purchase=true)."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        fields, err = self._parse_voucher_fields(data)
        if err:
            _json(self, {"error": err}, 400)
            return
        custom_code = str(data.get("code", "")).strip() or None
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            discount = _db_mod.create_discount_code(
                fields["benefit_type"], fields["benefit_value"], fields["auto_apply"], fields["channel"],
                fields["valid_from"], fields["valid_until"], fields["max_uses"],
                created_by=tg_id, note=fields["note"], code=custom_code,
                requires_purchase=fields["requires_purchase"],
            )
        except Exception as e:
            log.error(f"[admin_discount_create] {e}")
            _json(self, {"error": str(e)}, 400)
            return
        _json(self, {"ok": True, "discount": discount})

    def _api_admin_discount_list(self, qs: dict):
        """GET /api/admin/discount/list?user_id=... — xem tất cả mã giảm giá đã tạo."""
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"discounts": [], "codes": []})
            return
        data = _db_mod.list_discount_codes()
        _json(self, {"discounts": data, "codes": data})

    def _api_admin_discount_set_active(self, data: dict, active: bool):
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        code = str(data.get("code", "")).strip()
        if not code:
            _json(self, {"error": "code required"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        ok = _db_mod.set_discount_code_active(code, active, actor_id=tg_id)
        _json(self, {"ok": ok})

    # ── GOV-026: 4 endpoints mới cho Harvey's web.html ──────────────────────────

    def _api_unified_history(self, qs: dict):
        """GET /api/history?user_id=... — gộp CCQ + gold trades thành 1 list.
        Response: {trades: [{...ccq, asset_type:'ccq'} | {...gold, asset_type:'gold'}]}
        """
        tg_id = _qs_tg_id(qs)
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400); return
        if not _auth_write(self, tg_id): return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, code, type, trade_date::text, units, nav, amount, note, nav_mismatch
                    FROM user_ccq_trades
                    WHERE telegram_id = %s
                    ORDER BY trade_date DESC, id DESC
                """, [tg_id])
                ccq_rows = cur.fetchall()
                cur.execute("""
                    SELECT id, product, type, trade_date::text, unit, qty, qty_luong,
                           price_per_luong, total_vnd, note,
                           COALESCE(name, '') AS name
                    FROM user_gold_trades
                    WHERE telegram_id = %s
                    ORDER BY trade_date DESC, id DESC
                """, [tg_id])
                gold_rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        trades = []
        for r in ccq_rows:
            trades.append({
                "index": r[0], "telegram_id": tg_id,
                "code": r[1], "fund_code": r[1], "type": r[2],
                "date": r[3], "trade_date": r[3],
                "units": r[4], "nav": r[5], "price_per_unit": r[5],
                "amount": r[6], "note": r[7], "nav_mismatch": r[8],
                "asset_type": "ccq",
            })
        for r in gold_rows:
            trades.append({
                "index": r[0], "telegram_id": tg_id,
                "product": r[1], "type": r[2],
                "date": r[3], "trade_date": r[3],
                "unit": r[4], "qty": r[5], "qty_luong": r[6],
                "price_per_luong": r[7], "total_vnd": r[8], "note": r[9],
                "name": r[10],
                "asset_type": "gold",
            })
        trades.sort(key=lambda t: (t["date"] or ""), reverse=True)
        _json(self, {"trades": trades})

    def _api_nav_history_chart(self, code: str, qs: dict):
        """GET /api/nav_history/<code>?limit=365 — lịch sử NAV cho chart.
        Response: {code, history:[{date, nav},...]} oldest-first.
        """
        if not code or len(code) > 12:
            _json(self, {"error": "Invalid code"}, 400); return
        try:
            limit = max(1, min(3650, int((qs.get("limit") or ["365"])[0])))
        except (ValueError, TypeError):
            limit = 365
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not set"}, 503); return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT nav_date::text, nav::float
                    FROM nav_history
                    WHERE fund_code = %s AND nav IS NOT NULL
                    ORDER BY nav_date DESC
                    LIMIT %s
                """, (code, limit))
                rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        history = [{"date": r[0], "nav": r[1]} for r in reversed(rows)]
        _json(self, {"code": code, "history": history})

    def _api_gold_price_history(self, product: str):
        """GET /api/gold/price_history/<product> — lịch sử giá vàng cho 1 sản phẩm.
        product là product code trong bảng gold_prices (VD: SJC_1L, XAUUSD).
        Response: {product, history:[{date, price},...]} oldest-first.
        Trả history:[] nếu product là tên tuỳ chỉnh không có trong gold_prices.
        """
        if not product or len(product) > 80:
            _json(self, {"error": "Invalid product"}, 400); return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not set"}, 503); return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT price_date::text,
                           COALESCE(buy_price, sell_price)::float AS price
                    FROM gold_prices
                    WHERE product = %s
                    ORDER BY price_date
                """, (product,))
                rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        history = [{"date": r[0], "price": r[1]} for r in rows]
        _json(self, {"product": product, "history": history})

    def _api_admin_payments_recent(self, qs: dict):
        """GET /api/admin/payments/recent?user_id=... — 50 giao dịch gần nhất (admin only).
        Gộp bank_transfer_orders (SePay) + processed_payments (Stars/MoMo).
        Response: {payments:[{telegram_id,name,plan,method,amount_vnd,stars,status,created_at}]}
        """
        tg_id = (qs.get("user_id") or [""])[0]
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403); return
        if not _auth_write(self, tg_id): return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"payments": []}); return
        try:
            import psycopg2
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                # SePay: lấy từ bank_transfer_orders, join bot_profiles cho tên
                cur.execute("""
                    SELECT b.telegram_id::text, b.plan_key, b.amount_vnd::float,
                           b.status, b.created_at::text,
                           COALESCE(p.name, b.telegram_id::text) AS name
                    FROM bank_transfer_orders b
                    LEFT JOIN bot_profiles p ON p.telegram_id::text = b.telegram_id::text
                    ORDER BY b.created_at DESC
                    LIMIT 30
                """)
                sepay_rows = cur.fetchall()
                # Stars/MoMo: từ processed_payments (không có amount/plan — chỉ có provider + tg_id)
                cur.execute("""
                    SELECT pp.telegram_id::text, pp.provider, pp.created_at::text,
                           COALESCE(p.name, pp.telegram_id::text) AS name
                    FROM processed_payments pp
                    LEFT JOIN bot_profiles p ON p.telegram_id::text = pp.telegram_id::text
                    WHERE pp.provider IN ('stars','momo')
                    ORDER BY pp.created_at DESC
                    LIMIT 30
                """)
                other_rows = cur.fetchall()
            conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        payments = []
        for r in sepay_rows:
            payments.append({
                "telegram_id": r[0], "plan": r[1],
                "amount_vnd": r[2], "status": r[3],
                "created_at": r[4], "name": r[5],
                "method": "sepay",
            })
        for r in other_rows:
            payments.append({
                "telegram_id": r[0], "method": r[1],
                "created_at": r[2], "name": r[3],
                "status": "paid",
            })
        payments.sort(key=lambda p: p.get("created_at") or "", reverse=True)
        _json(self, {"payments": payments[:50]})

    def _api_admin_discount_edit(self, data: dict):
        """POST /api/admin/discount/edit — sửa mã đã tạo (không đổi code, uses_count)."""
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        code = str(data.get("code", "")).strip()
        if not code:
            _json(self, {"error": "code required"}, 400)
            return
        fields, err = self._parse_voucher_fields(data)
        if err:
            _json(self, {"error": err}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        try:
            discount = _db_mod.update_discount_code(
                code, fields["benefit_type"], fields["benefit_value"], fields["auto_apply"], fields["channel"],
                fields["valid_from"], fields["valid_until"], fields["max_uses"], fields["note"], actor_id=tg_id,
                requires_purchase=fields["requires_purchase"],
            )
        except Exception as e:
            _json(self, {"error": str(e)}, 400)
            return
        if not discount:
            _json(self, {"error": f"Không tìm thấy mã {code}"}, 404)
            return
        _json(self, {"ok": True, "discount": discount})

    def _api_admin_nav_confirm(self, data: dict):
        """POST /api/admin/nav/confirm — admin chọn manual hoặc fetch cho pending NAV."""
        tg_id     = str(data.get("telegram_id", ""))
        fund_code = str(data.get("fund_code", "")).upper()
        nav_date  = str(data.get("nav_date", ""))
        choice    = str(data.get("choice", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if choice not in ("manual", "fetch"):
            _json(self, {"error": "choice phải là 'manual' hoặc 'fetch'"}, 400)
            return
        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        ok = _db_mod.resolve_nav_confirm(fund_code, nav_date, choice, actor_id=tg_id)
        if ok:
            _trigger_t2_repredict([fund_code])
            _json(self, {"ok": True, "fund_code": fund_code, "nav_date": nav_date, "choice": choice})
        else:
            _json(self, {"error": f"Không tìm thấy pending_confirm cho {fund_code} {nav_date}"}, 404)

    def _api_admin_import_trades(self, data: dict):
        """POST /api/admin/import-trades — bulk import CCQ trades vào PostgreSQL.
        Body: {telegram_id: str, trades: [{code, type, date, units, nav, amount}], replace: bool,
               admin_key?: str}. replace=true → xóa toàn bộ trades của user trước khi import.
        Dùng bởi scripts/import_tcbs_xlsx.py (chạy từ máy admin, không có phiên Telegram) —
        xác thực qua ADMIN_API_KEY (_check_admin_secret) thay vì X-Init-Data.
        """
        tg_id     = str(data.get("telegram_id", "")).strip()
        trades_in = data.get("trades", [])
        replace   = data.get("replace", False)
        if not tg_id or not trades_in:
            _json(self, {"error": "telegram_id and trades required"}, 400); return
        if not _check_admin_secret(data) and not _auth_write(self, tg_id):
            return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                if replace:
                    cur.execute("DELETE FROM user_ccq_trades WHERE telegram_id=%s", [tg_id])
                inserted = 0
                for t in trades_in:
                    code   = str(t.get("code","")).upper().strip()
                    tx     = str(t.get("type","buy")).lower()
                    dt     = str(t.get("date",""))
                    units  = float(t.get("units", 0))
                    nav    = float(t.get("nav", 0))
                    amount = float(t.get("amount", units * nav))
                    note   = str(t.get("note", ""))
                    is_div = tx == "dividend"
                    if not code or (units <= 0 and not is_div): continue
                    if is_div and units <= 0 and amount <= 0: continue
                    # Deduplicate
                    cur.execute("""
                        SELECT 1 FROM user_ccq_trades
                        WHERE telegram_id=%s AND code=%s AND trade_date=%s
                          AND type=%s AND ABS(units-%s)<0.01
                    """, [tg_id, code, dt, tx, units])
                    if cur.fetchone(): continue
                    cur.execute("""
                        INSERT INTO user_ccq_trades
                          (telegram_id, code, type, trade_date, units, nav, amount, note)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, [tg_id, code, tx, dt, round(units,4), round(nav,2), round(amount), note])
                    inserted += 1
                cur.execute("SELECT COUNT(*) FROM user_ccq_trades WHERE telegram_id=%s", [tg_id])
                total = cur.fetchone()[0]
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "inserted": inserted, "total_trade_log": total})

    def _api_admin_settoken(self, data: dict):
        """POST /api/admin/settoken — cập nhật tcbs_token rồi fetch NAV ngay."""
        admin_id = str(data.get("admin_id", ""))
        new_token = str(data.get("token", "")).strip()
        if not new_token:
            _json(self, {"error": "token required"}, 400)
            return
        if not _is_admin(admin_id):
            _json(self, {"error": "Unauthorized"}, 403)
            return
        if not _auth_write(self, admin_id):
            return
        cfg = _load_cfg()
        cfg["tcbs_token"] = new_token
        _save_cfg(cfg)
        log.info(f"[admin] tcbs_token cập nhật (len={len(new_token)}) — sẽ fetch NAV ngay")
        # Fetch full DB NAV trong background, rồi gửi 1 message tổng hợp cho admin
        if _BOT_IMPORTED:
            admin_tg_id = str(cfg.get("admin_telegram_id", ""))
            bot_tok     = cfg.get("bot_token", "")
            _new_token  = new_token  # capture cho closure

            def _bg_fetch():
                import subprocess, sys as _sys, re as _re
                try:
                    from bot import tg_send as _ts

                    script = Path(__file__).parent / "harvest_nav.py"
                    harvest_out, harvest_err = "", ""
                    ok = False
                    total_new = 0
                    needs_check = []
                    if script.exists():
                        res = subprocess.run(
                            [_sys.executable, str(script), "--daily", "--jwt", _new_token],
                            capture_output=True, text=True, timeout=300,
                            env={**__import__("os").environ},
                        )
                        harvest_out = (res.stdout or "").strip()
                        harvest_err = (res.stderr or "").strip()
                        ok = res.returncode == 0
                        log.info(f"[admin] harvest_nav: {harvest_out[-300:] if harvest_out else harvest_err[:300]}")
                        for line in harvest_out.splitlines():
                            if "Daily" in line and "records" in line:
                                m = _re.search(r"\+(\d+) records", line)
                                if m:
                                    total_new = int(m.group(1))
                            if line.startswith("NEEDS_CHECK:"):
                                needs_check = [c.strip() for c in line.split(":", 1)[1].split(",") if c.strip()]
                    else:
                        log.warning("[admin] harvest_nav.py không tìm thấy")

                    if admin_tg_id and bot_tok:
                        if not ok:
                            msg = f"❌ Cập nhật token thất bại (harvest_nav lỗi)\n{harvest_err[-300:] or 'Không rõ nguyên nhân'}"
                        elif total_new > 0:
                            msg = f"✅ Token mới OK — đã fetch NAV, +{total_new} records"
                        else:
                            msg = "✅ Token mới OK — NAV đã up-to-date, không có records mới"
                        if needs_check:
                            check_str = ", ".join(f"<code>{c}</code>" for c in needs_check)
                            msg += (f"\n⚠️ Chưa có NAV hôm nay hoặc còn bằng NAV hôm qua "
                                    f"({len(needs_check)} mã) — cần kiểm tra và nhập tay nếu cần: {check_str}")
                        _ts(bot_tok, admin_tg_id, msg)

                except Exception as _ex:
                    log.warning(f"[admin] Background fetch lỗi: {_ex}")

            threading.Thread(target=_bg_fetch, daemon=True, name="admin-nav-refresh").start()
        _json(self, {"ok": True, "msg": "tcbs_token updated, NAV fetch started in background"})

    def _api_admin_fetch_nav(self, data: dict):
        """POST /api/admin/fetch-nav — trigger fresh NAV fetch for all funds.
        Params: telegram_id (admin), skip_tcbs (bool) — bỏ qua các quỹ TCBS nếu True
        Returns token_expired error nếu token không hợp lệ (sync check trước khi background).
        """
        tg_id = str(data.get("telegram_id", ""))
        if not _is_admin(tg_id):
            _json(self, {"error": "admin_only"}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        if not _BOT_IMPORTED:
            _json(self, {"error": "bot module not available"}, 503)
            return
        cfg = _load_cfg()
        skip_tcbs = bool(data.get("skip_tcbs", False))
        import bot as _bot
        import threading

        # ── Quick token validation (sync, không fetch) ──────────────────────
        token = cfg.get("tcbs_token", "")
        if not skip_tcbs and token:
            try:
                import requests as _req
                hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                probe = _req.get(
                    "https://apipubaws.tcbs.com.vn/stock-insight/v1/fund/top-funds",
                    headers=hdr, timeout=6
                )
                if probe.status_code in (401, 403):
                    log.warning("[fetch-nav] TCBS token expired/invalid → returning token_expired")
                    _json(self, {"ok": False, "error": "token_expired",
                                 "tcbs_error": f"HTTP {probe.status_code}"})
                    return
            except Exception as ex:
                log.warning(f"[fetch-nav] token probe lỗi (bỏ qua): {ex}")

        db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
        # Luôn dùng FUND_CATALOG từ bot.py (đã có fmarket_id mới nhất),
        # fallback về config.json funds nếu không import được.
        funds_cfg = _FUND_CATALOG if _FUND_CATALOG else cfg.get("funds", {})

        def _do_fetch():
            results, errors = {}, {}
            try:
                for code, fc in funds_cfg.items():
                    pts_all = []
                    # 1. fmarket (luôn thử nếu có)
                    if fc.get("fmarket_id"):
                        try:
                            fpts = _bot.fetch_fmarket(fc["fmarket_id"])
                            if fpts:
                                pts_all.extend(fpts)
                                log.info(f"[fetch-nav] fmarket {code}: {len(fpts)} pts")
                        except Exception as ex:
                            errors[f"fmarket_{code}"] = str(ex)
                            log.warning(f"fmarket {code}: {ex}")
                    # 2. TCBS (thử thêm nếu không skip và có config)
                    if not skip_tcbs and fc.get("tcbs") and token:
                        try:
                            tpts = _bot.fetch_tcbs(code, token)
                            if tpts:
                                # Merge: dùng TCBS data cho ngày trùng (source of truth)
                                existing_dates = {p["date"] for p in pts_all}
                                new_pts = [p for p in tpts if p["date"] not in existing_dates]
                                pts_all.extend(new_pts)
                                log.info(f"[fetch-nav] tcbs {code}: {len(tpts)} pts (+{len(new_pts)} new)")
                        except Exception as ex:
                            errors[f"tcbs_{code}"] = str(ex)
                            log.warning(f"tcbs {code}: {ex}")
                    # 3. Save merged points
                    if pts_all and db_url:
                        try:
                            import psycopg2
                            _conn = psycopg2.connect(db_url)
                            _cur = _conn.cursor()
                            _saved = 0
                            _new_dates = []
                            for _pt in pts_all:
                                _cur.execute(
                                    "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                                    "VALUES (%s, %s, %s, %s) "
                                    "ON CONFLICT (fund_code, nav_date) DO NOTHING",
                                    (code, _pt['date'], float(_pt['nav']), 'tcinvest')
                                )
                                if _cur.rowcount:
                                    _new_dates.append(_pt['date'])
                                _saved += _cur.rowcount
                            _conn.commit(); _conn.close()
                            # GOV-008-part2: hash cho các dòng MỚI vừa insert trực tiếp
                            # (bỏ qua db.upsert_nav() nên chưa có row_hash)
                            if _db_mod is not None:
                                from datetime import date as _date2
                                for _d in _new_dates:
                                    try:
                                        _db_mod._update_nav_row_hash(code, _date2.fromisoformat(_d))
                                    except Exception:
                                        pass
                            results[code] = _saved
                            log.info(f"[fetch-nav] saved {code}: +{_saved}")
                        except Exception as ex:
                            errors[f"save_{code}"] = str(ex)
                            log.warning(f"save {code}: {ex}")
                log.info(f"[fetch-nav] done — results: {results}, errors: {errors}")
                _trigger_t2_repredict([c for c, n in results.items() if n > 0])
            except Exception as ex:
                log.error(f"[fetch-nav] fatal: {ex}")

        threading.Thread(target=_do_fetch, daemon=True, name="admin-fetch-nav").start()
        _json(self, {"ok": True, "msg": "NAV fetch started",
                     "skip_tcbs": skip_tcbs, "funds": list(funds_cfg.keys())})

    def _api_nav_draft(self, data: dict):
        """POST /api/nav/draft — Pro user nhập NAV tạm thời vào nav_drafts.
        Chỉ Pro/Admin. Sau khi API harvest confirm → tự động unify vào nav_history."""
        tg_id = str(data.get("tg_id", ""))
        if not _auth_write(self, tg_id):
            return
        if not _check_tier(self, tg_id, "pro"):
            return
        funds_data = data.get("funds", {})
        if not funds_data:
            _json(self, {"error": "funds required"}, 400)
            return
        if not (_db_mod and _db_mod.is_available()):
            _json(self, {"error": "DB không khả dụng"}, 503)
            return
        from datetime import date as _date
        saved, errors = {}, {}
        for code, pts in funds_data.items():
            code = code.upper()
            count = 0
            for pt in (pts or []):
                try:
                    nav_date = _date.fromisoformat(pt["date"])
                    _db_mod.save_nav_draft(tg_id, code, nav_date, float(pt["nav"]))
                    count += 1
                except Exception as e:
                    errors[f"{code}/{pt.get('date')}"] = str(e)
            if count:
                saved[code] = count
        # Recompute signal của user từ nav_history + drafts
        if saved and _BOT_IMPORTED:
            try:
                cfg = _load_cfg()
                _compute_from_nav_history(list(saved.keys()), cfg, telegram_id=tg_id)
                log.info(f"[nav-draft] {tg_id}: saved drafts={saved}, recomputed signals")
            except Exception as e:
                log.warning(f"[nav-draft] recompute: {e}")
        _json(self, {"ok": True, "saved": saved, "errors": errors,
                     "note": "NAV tạm thời. Sẽ được xác nhận khi API harvest khớp."})

    def _api_admin_import_nav(self, data: dict):
        """POST /api/admin/import-nav — Admin-only bulk import NAV vào shared nav_history."""
        # Admin-only guard — LUÔN xác thực initData thật trước, không có ngoại lệ nào
        # bỏ qua kiểm tra chữ ký chỉ vì tg_id trùng chuỗi admin_id (đã từng là lỗ hổng).
        tg_id = str(data.get("tg_id", ""))
        if not tg_id or not _is_admin(tg_id):
            _json(self, {"error": "Chỉ admin mới được import NAV trực tiếp vào DB tổng. "
                                  "Dùng /api/nav/draft nếu là tài khoản Pro."}, 403)
            return
        if not _auth_write(self, tg_id):
            return
        funds_data = data.get("funds", {})
        if not funds_data:
            _json(self, {"error": "funds required"}, 400)
            return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not configured"}, 503)
            return

        import psycopg2, psycopg2.extras

        force = bool(data.get("force", False))  # Admin xác nhận ghi đè kể cả 'fixed'

        def _insert_pg(db_url, code, points):
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            skipped = inserted = 0
            touched_dates = []
            for pt in points:
                if force:
                    # Ghi đè mọi source kể cả 'fixed' — reset về 'manual' để API re-confirm
                    cur.execute(
                        "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                        "VALUES (%s, %s, %s, 'manual') "
                        "ON CONFLICT (fund_code, nav_date) DO UPDATE "
                        "SET nav=EXCLUDED.nav, source='manual', fetched_at=NOW()",
                        (code, pt["date"], float(pt["nav"]))
                    )
                    inserted += cur.rowcount
                    if cur.rowcount:
                        touched_dates.append(pt["date"])
                else:
                    # Bình thường: chỉ ghi nếu chưa có hoặc source='manual'
                    cur.execute(
                        "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                        "VALUES (%s, %s, %s, 'manual') "
                        "ON CONFLICT (fund_code, nav_date) DO UPDATE "
                        "SET nav=EXCLUDED.nav, fetched_at=NOW() "
                        "WHERE nav_history.source = 'manual'",
                        (code, pt["date"], float(pt["nav"]))
                    )
                    if cur.rowcount:
                        inserted += 1
                        touched_dates.append(pt["date"])
                    else:
                        skipped += 1
            conn.commit()
            conn.close()
            # GOV-008-part2: cập nhật row_hash cho từng dòng vừa ghi trực tiếp bằng SQL
            # (đường ghi này bỏ qua db.upsert_nav() nên không tự có hash) — đảm bảo MỌI
            # datapoint đều có row_hash để verify_nav_integrity() không báo sai.
            if _db_mod is not None:
                from datetime import date as _date
                for d_str in touched_dates:
                    try:
                        _db_mod._update_nav_row_hash(code, _date.fromisoformat(d_str))
                    except Exception as ex:
                        log.debug(f"[import-nav] row_hash {code}/{d_str}: {ex}")
            return inserted, skipped

        results = {}
        skipped_map = {}
        errors = {}
        for code, pts in funds_data.items():
            if not pts:
                continue
            try:
                n, sk = _insert_pg(db_url, code.upper(), pts)
                results[code.upper()] = n
                if sk:
                    skipped_map[code.upper()] = sk
                log.info(f"[import-nav] {code}: +{n} inserted, {sk} skipped (force={force})")
            except Exception as ex:
                errors[code] = str(ex)
                log.warning(f"[import-nav] {code} error: {ex}")

        # Recompute buy_signals từ nav_history ngay sau import
        imported_codes = [c.upper() for c in results]
        if imported_codes and _BOT_IMPORTED:
            try:
                cfg = _load_cfg()
                _compute_from_nav_history(imported_codes, cfg)
            except Exception as ex:
                log.warning(f"[import-nav] recompute signals failed: {ex}")
            _trigger_t2_repredict(imported_codes)

        resp = {"ok": True, "inserted": results, "errors": errors,
                "total": sum(results.values()), "force": force}
        if skipped_map:
            resp["skipped"] = skipped_map
            resp["hint"] = "Một số điểm đã có source=fixed/api, bị bỏ qua. Dùng force=true để ghi đè."
        _json(self, resp)

    def _api_admin_fixportfolio(self, data: dict):
        """POST /api/admin/fixportfolio — sửa portfolio admin."""
        admin_id = str(data.get("admin_id", ""))
        code = str(data.get("code", "")).upper()
        avg_cost = data.get("avg_cost")
        units = data.get("units")
        if not code or avg_cost is None:
            _json(self, {"error": "code and avg_cost required"}, 400)
            return
        if not _is_admin(admin_id):
            _json(self, {"error": "Unauthorized"}, 403)
            return
        if not _auth_write(self, admin_id):
            return
        cfg = _load_cfg()
        cfg_admin_id = str(cfg.get("admin_telegram_id", ""))
        admin_p = next((p for p in cfg.get("profiles", []) if str(p.get("telegram_id")) == cfg_admin_id), None)
        if not admin_p:
            _json(self, {"error": "Admin profile not found"}, 404)
            return
        entry = next((e for e in admin_p.get("portfolio", []) if e.get("code") == code), None)
        if not entry:
            _json(self, {"error": f"{code} not in portfolio"}, 404)
            return
        old = {"avg_cost": entry.get("avg_cost"), "units": entry.get("units")}
        entry["avg_cost"] = float(avg_cost)
        if units is not None:
            entry["units"] = float(units)
        _save_cfg(cfg)
        log.info(f"[admin] fixportfolio {code}: avg_cost {old['avg_cost']} → {avg_cost}")
        _json(self, {"ok": True, "code": code, "old": old, "new": entry})

    def _api_create_stars_invoice(self, data: dict):
        """POST /api/payment/stars/create — tạo Telegram Stars invoice link để Mini App mở.
        Params: plan (m1/q1/h1/y1, mặc định m1 nếu không gửi hoặc gói lạ)."""
        import requests as _req
        cfg       = _load_cfg()
        bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
        if not bot_token or bot_token.startswith("NHAP"):
            _json(self, {"error": "bot_token chưa cấu hình"}, 500)
            return
        init_data = self.headers.get("X-Init-Data", "")
        user = _validate_init_data(init_data, bot_token)
        if not user and os.environ.get("MINIAPP_NO_AUTH"):
            user = {"id": 0}
        if not user:
            _json(self, {"error": "initData không hợp lệ"}, 403)
            return
        user_id = user.get("id", 0)
        plan_key = str((data or {}).get("plan", DEFAULT_PLAN))
        if plan_key not in PRO_PLANS:
            plan_key = DEFAULT_PLAN
        plan = PRO_PLANS[plan_key]
        payload = {
            "title": "Fund Tracker Pro",
            "description": (
                f"{plan['label']}: theo dõi không giới hạn quỹ, "
                "phân tích sâu RSI/MACD/Sharpe/Sortino, cảnh báo tự động, "
                "phân tích giá vàng."
            ),
            "payload": f"pro:{plan_key}:{user_id}",
            "currency": "XTR",
            "prices": [{"label": f"Fund Tracker Pro — {plan['label']}", "amount": plan["stars"]}],
        }
        try:
            r = _req.post(
                f"https://api.telegram.org/bot{bot_token}/createInvoiceLink",
                json=payload, timeout=15
            )
            d = r.json()
            if d.get("ok"):
                log.info(f"[PAY] createInvoiceLink OK for user {user_id}")
                _json(self, {"invoice_link": d["result"]})
            else:
                err = d.get("description", "Telegram API error")
                log.error(f"[PAY] createInvoiceLink fail: {err}")
                _json(self, {"error": err}, 502)
        except Exception as e:
            log.error(f"[PAY] createInvoiceLink exception: {e}")
            _json(self, {"error": str(e)}, 500)

    def _api_momo_create(self, data: dict):
        """POST /api/payment/momo/create — PAY-004: tạo MoMo v2 payment request, trả payUrl.
        Params: plan (m1/q1/h1/y1, mặc định m1 nếu không gửi hoặc gói lạ).

        Yêu cầu Mini App xác thực bằng X-Init-Data (giống /api/payment/stars/create) — không
        tin telegram_id do client gửi lên, tránh nâng cấp tier hộ người khác.
        """
        import requests as _req
        cfg       = _load_cfg()
        bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
        init_data = self.headers.get("X-Init-Data", "")
        user = _validate_init_data(init_data, bot_token)
        if not user and os.environ.get("MINIAPP_NO_AUTH"):
            user = {"id": data.get("telegram_id", 0)}
        if not user:
            _json(self, {"error": "initData không hợp lệ"}, 403)
            return
        user_id = str(user.get("id", 0))
        plan_key = str((data or {}).get("plan", DEFAULT_PLAN))
        if plan_key not in PRO_PLANS:
            plan_key = DEFAULT_PLAN
        plan = PRO_PLANS[plan_key]

        base = os.environ.get("MINIAPP_URL", f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost:8443')}")
        request_id  = f"{user_id}-{int(datetime.now().timestamp())}"
        # orderId format: FTP-<telegram_id>-<plan_key>-<ts> — plan_key cần cho IPN biết
        # cấp bao nhiêu ngày Pro (xem _api_momo_ipn).
        order_id    = f"FTP-{user_id}-{plan_key}-{int(datetime.now().timestamp())}"
        order_info  = f"Fund Tracker Pro - {plan['label']}"
        redirect_url = f"{base}?user_id={user_id}&momo_return=1"
        ipn_url      = f"{base}/api/payment/momo/ipn"
        amount       = plan["vnd"]
        request_type = "captureWallet"
        extra_data   = ""

        raw_sig = (
            f"accessKey={_MOMO_ACCESS_KEY}"
            f"&amount={amount}"
            f"&extraData={extra_data}"
            f"&ipnUrl={ipn_url}"
            f"&orderId={order_id}"
            f"&orderInfo={order_info}"
            f"&partnerCode={_MOMO_PARTNER_CODE}"
            f"&redirectUrl={redirect_url}"
            f"&requestId={request_id}"
            f"&requestType={request_type}"
        )
        signature = hmac.new(_MOMO_SECRET_KEY.encode(), raw_sig.encode(), hashlib.sha256).hexdigest()

        payload = {
            "partnerCode": _MOMO_PARTNER_CODE,
            "partnerName": "Fund Tracker Pro",
            "storeId":     "FundTrackerPro",
            "requestId":   request_id,
            "amount":      amount,
            "orderId":     order_id,
            "orderInfo":   order_info,
            "redirectUrl": redirect_url,
            "ipnUrl":      ipn_url,
            "lang":        "vi",
            "extraData":   extra_data,
            "requestType": request_type,
            "signature":   signature,
        }
        try:
            r = _req.post(_MOMO_ENDPOINT, json=payload, timeout=15)
            d = r.json()
            if d.get("resultCode") == 0 and d.get("payUrl"):
                log.info(f"[PAY][MoMo] create OK user={user_id} orderId={order_id}")
                _json(self, {"pay_url": d["payUrl"], "order_id": order_id})
            else:
                err = d.get("message", "MoMo API error")
                log.error(f"[PAY][MoMo] create fail: {err} (resultCode={d.get('resultCode')})")
                _json(self, {"error": err}, 502)
        except Exception as e:
            log.error(f"[PAY][MoMo] create exception: {e}")
            _json(self, {"error": str(e)}, 500)

    def _api_momo_ipn(self, data: dict):
        """POST /api/payment/momo/ipn — PAY-005: MoMo server-to-server callback.

        Verify chữ ký HMAC-SHA256 trước khi tin bất kỳ field nào. Khi resultCode=0
        (thanh toán thành công) → nâng cấp user_tiers lên 'pro' theo số ngày của gói
        (parse từ orderId, xem PRO_PLANS trong pricing.py).
        Luôn trả 200 (MoMo sẽ retry nếu không nhận được response) trừ khi chữ ký sai.
        """
        partner_code = str(data.get("partnerCode", ""))
        order_id     = str(data.get("orderId", ""))
        request_id   = str(data.get("requestId", ""))
        amount       = str(data.get("amount", ""))
        order_info   = str(data.get("orderInfo", ""))
        order_type   = str(data.get("orderType", ""))
        trans_id     = str(data.get("transId", ""))
        result_code  = data.get("resultCode")
        message      = str(data.get("message", ""))
        pay_type     = str(data.get("payType", ""))
        response_time = str(data.get("responseTime", ""))
        extra_data   = str(data.get("extraData", ""))
        signature    = str(data.get("signature", ""))

        raw_sig = (
            f"accessKey={_MOMO_ACCESS_KEY}"
            f"&amount={amount}"
            f"&extraData={extra_data}"
            f"&message={message}"
            f"&orderId={order_id}"
            f"&orderInfo={order_info}"
            f"&orderType={order_type}"
            f"&partnerCode={partner_code}"
            f"&payType={pay_type}"
            f"&requestId={request_id}"
            f"&responseTime={response_time}"
            f"&resultCode={result_code}"
            f"&transId={trans_id}"
        )
        computed = hmac.new(_MOMO_SECRET_KEY.encode(), raw_sig.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, signature):
            log.error(f"[PAY][MoMo] IPN chữ ký không hợp lệ, orderId={order_id}")
            _json(self, {"error": "invalid signature"}, 400)
            return

        log.info(f"[PAY][MoMo] IPN orderId={order_id} resultCode={result_code} transId={trans_id}")

        if result_code == 0:
            # orderId format mới: FTP-<telegram_id>-<plan_key>-<ts>
            # (cũ, trước multi-tier: FTP-<telegram_id>-<ts> — coi như gói tháng)
            parts = order_id.split("-")
            tg_id = parts[1] if len(parts) >= 3 and parts[0] == "FTP" else ""
            plan_key = parts[2] if len(parts) >= 4 and parts[0] == "FTP" and parts[2] in PRO_PLANS else DEFAULT_PLAN
            plan_days = PRO_PLANS[plan_key]["days"]
            if tg_id and _db_mod is not None and _db_mod.is_available():
                # GOV-003: MoMo có thể gửi lại IPN nếu không nhận response đủ nhanh —
                # chặn xử lý trùng bằng transId (unique per giao dịch từ MoMo).
                if not _db_mod.record_payment_once("momo", trans_id or order_id, tg_id):
                    log.warning(f"[PAY][MoMo][DUP] transId={trans_id} orderId={order_id} đã xử lý trước đó — bỏ qua")
                    _db_mod.log_audit(None, "duplicate_payment_blocked", "processed_payments",
                                       trans_id or order_id, note=f"momo orderId={order_id} amount={amount}")
                    cfg_dup = _load_cfg()
                    dup_admin = str(cfg_dup.get("admin_telegram_id") or os.environ.get("ADMIN_TELEGRAM_ID", "")).strip()
                    dup_token = cfg_dup.get("bot_token") or os.environ.get("BOT_TOKEN", "")
                    if dup_admin and dup_token and not dup_token.startswith("NHAP"):
                        try:
                            import requests as _req
                            _req.post(
                                f"https://api.telegram.org/bot{dup_token}/sendMessage",
                                json={"chat_id": dup_admin, "text": f"⚠️ Thanh toán MoMo trùng lặp bị chặn: orderId={order_id} transId={trans_id}"},
                                timeout=8,
                            )
                        except Exception:
                            pass
                    _json(self, {"resultCode": 0, "message": "duplicate ignored"})
                    return
                expires_at = None
                try:
                    result = _db_mod.extend_pro(tg_id, plan_days, note=f"momo {PRO_PLANS[plan_key]['label']} ({amount}đ)")
                    expires_at = result.get("pro_expires_at")
                    log.info(f"[PAY][MoMo] tier=pro extended {plan_days}d for {tg_id}, expires {expires_at}")
                    try:
                        _db_mod.grant_referral_purchase_bonus(tg_id)
                    except Exception as _rbe:
                        log.warning(f"[PAY][MoMo] grant_referral_purchase_bonus lỗi: {_rbe}")
                except Exception as e:
                    log.error(f"[PAY][MoMo] extend_pro error: {e}")
                    expires_at = datetime.now(timezone.utc) + timedelta(days=plan_days)
                cfg = _load_cfg()
                bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
                if bot_token and not bot_token.startswith("NHAP"):
                    try:
                        import requests as _req
                        exp_str = expires_at.strftime("%d/%m/%Y")
                        _req.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={
                                "chat_id": tg_id,
                                "parse_mode": "HTML",
                                "text": (
                                    f"🌟 <b>Chào mừng bạn đến với Fund Tracker Pro!</b>\n\n"
                                    f"✅ Thanh toán MoMo {int(amount):,} đ thành công — gói <b>{PRO_PLANS[plan_key]['label']}</b>\n"
                                    f"📅 Gói Pro có hiệu lực đến: <b>{exp_str}</b>\n\n"
                                    f"Gõ /app để mở Mini App ngay. 🚀"
                                ),
                            },
                            timeout=8,
                        )
                    except Exception as e:
                        log.error(f"[PAY][MoMo] sendMessage exception: {e}")
            elif not tg_id:
                log.error(f"[PAY][MoMo] Không parse được telegram_id từ orderId={order_id}")

        _json(self, {"resultCode": 0, "message": "success"})

    def _api_sepay_create(self, data: dict):
        """POST /api/payment/sepay/create — PAY-009: tạo đơn chuyển khoản VietQR.

        Không cần merchant/business license (SePay hoạt động với tài khoản ngân
        hàng cá nhân). Trả về URL ảnh QR + ref_code (nội dung CK) — app ngân hàng
        HOẶC app MoMo (hỗ trợ quét VietQR) đều quét trả tiền được. SePay sẽ tự
        bắn webhook khi tiền về khớp nội dung, không cần user tự nhập mã.
        """
        cfg       = _load_cfg()
        bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
        init_data = self.headers.get("X-Init-Data", "")
        user = _validate_init_data(init_data, bot_token)
        if not user and os.environ.get("MINIAPP_NO_AUTH"):
            user = {"id": data.get("telegram_id", 0)}
        if not user:
            _json(self, {"error": "initData không hợp lệ"}, 403)
            return
        if not _SEPAY_ACCOUNT_NUMBER or not _SEPAY_BANK_CODE:
            _json(self, {"error": "Chưa cấu hình SEPAY_ACCOUNT_NUMBER/SEPAY_BANK_CODE trên server"}, 503)
            return
        user_id = str(user.get("id", 0))
        plan_key = str((data or {}).get("plan", DEFAULT_PLAN))
        if plan_key not in PRO_PLANS:
            plan_key = DEFAULT_PLAN
        plan = PRO_PLANS[plan_key]

        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return

        # Voucher (GOV-012/GOV-012-part2, 2026-07-16) — 2 loại benefit, CHỈ áp dụng
        # khi có giao dịch thật (khác Mã Promo, cấp free không cần mua):
        #  - discount_pct: giảm % ngay trên số tiền cần chuyển khoản (dưới đây).
        #  - bonus_days:   KHÔNG giảm giá — thu đủ giá gốc, nhưng ghi nhận lại để
        #    webhook xác nhận thanh toán cộng thêm ngày Pro (xem _api_sepay_webhook).
        #  - auto_apply: tự động tìm mã đang hiệu lực cho kênh 'sepay', không cần user
        #    nhập gì (get_active_auto_discount).
        #  - manual: nếu user có nhập discount_code trong request, ưu tiên validate mã
        #    đó (validate_discount_code) — cho phép dùng mã cụ thể thay vì auto.
        discount_code = str((data or {}).get("discount_code", "")).strip().upper()
        voucher = None
        if discount_code:
            v = _db_mod.validate_discount_code(discount_code, "sepay")
            if not v.get("ok"):
                _json(self, {"error": v.get("error", "Mã voucher không hợp lệ")}, 400)
                return
            voucher = v["discount"]
        else:
            voucher = _db_mod.get_active_auto_discount("sepay")

        is_discount = bool(voucher) and voucher["benefit_type"] == "discount_pct"
        discount_pct = voucher["benefit_value"] if is_discount else 0
        amount_vnd = int(plan["vnd"] * (1 - discount_pct / 100) // 1000 * 1000) if discount_pct else plan["vnd"]

        ref_code = _db_mod.create_bank_transfer_order(user_id, plan_key, amount_vnd)
        if voucher:
            try:
                _db_mod.apply_discount_code(voucher["code"], user_id, ref_code,
                                             voucher["benefit_type"], voucher["benefit_value"])
            except Exception as e:
                log.warning(f"[PAY][SePay] apply_discount_code lỗi (không chặn tạo đơn): {e}")
        qr_url = (
            f"{_SEPAY_QR_BASE}?acc={_SEPAY_ACCOUNT_NUMBER}&bank={_SEPAY_BANK_CODE}"
            f"&amount={amount_vnd}&des={ref_code}"
        )
        voucher_log = ""
        if voucher:
            voucher_log = (f" (mã {voucher['code']} -{discount_pct}%)" if is_discount
                            else f" (mã {voucher['code']} +{voucher['benefit_value']} ngày, cấp lúc thanh toán)")
        log.info(f"[PAY][SePay] order created ref={ref_code} user={user_id} plan={plan_key} "
                 f"amount={amount_vnd}{voucher_log}")
        _json(self, {
            "ref_code": ref_code, "qr_url": qr_url,
            "amount_vnd": amount_vnd, "original_vnd": plan["vnd"],
            "promo_pct": discount_pct,
            "bonus_days": voucher["benefit_value"] if (voucher and not is_discount) else 0,
            "discount_code": voucher["code"] if voucher else None,
            "plan_label": plan["label"],
            "account_number": _SEPAY_ACCOUNT_NUMBER, "bank_code": _SEPAY_BANK_CODE,
        })

    def _api_sepay_status(self, qs: dict):
        """GET /api/payment/sepay/status?ref=<ref_code> — Mini App poll để biết
        đơn CK đã được webhook xác nhận thanh toán chưa (không cần user tự refresh)."""
        ref = (qs.get("ref") or [""])[0]
        if not ref or _db_mod is None or not _db_mod.is_available():
            _json(self, {"status": "unknown"})
            return
        order = _db_mod.get_bank_transfer_order(ref)
        if not order:
            _json(self, {"status": "not_found"})
            return
        _json(self, {"status": order["status"]})

    def _verify_sepay_hmac(self) -> bool:
        """Xác thực chữ ký HMAC-SHA256 của SePay — công thức lấy TRỰC TIẾP từ
        trang "Hướng dẫn xác thực trên server" trong dashboard SePay (đã đọc
        code mẫu Python 2026-07-15, khớp chính xác):
            X-SePay-Signature: "sha256=" + hexdigest(HMAC-SHA256(secret, f"{timestamp}.{raw_body}"))
            X-SePay-Timestamp: unix seconds
        Trả False nếu thiếu header, sai chữ ký, hoặc timestamp quá cũ (>5 phút
        — chống replay: 1 webhook cũ bị chặn lại và gửi lại sau không được
        chấp nhận lần 2)."""
        signature = self.headers.get("X-SePay-Signature", "")
        timestamp = self.headers.get("X-SePay-Timestamp", "")
        if not signature or not timestamp:
            log.error("[PAY][SePay] webhook thiếu X-SePay-Signature/X-SePay-Timestamp")
            return False
        try:
            ts_int = int(timestamp)
        except ValueError:
            log.error(f"[PAY][SePay] X-SePay-Timestamp không hợp lệ: {timestamp!r}")
            return False
        if abs(time.time() - ts_int) > _SEPAY_HMAC_MAX_AGE_S:
            log.error(f"[PAY][SePay] webhook timestamp quá cũ/tương lai (chống replay): {timestamp!r}")
            return False

        raw_body = getattr(self, "_raw_body", b"")
        payload = raw_body.decode("utf-8", errors="replace")
        signed_str = f"{timestamp}.{payload}"
        expected = "sha256=" + hmac.new(
            _SEPAY_HMAC_SECRET.encode("utf-8"), signed_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            log.error("[PAY][SePay] webhook chữ ký HMAC không khớp")
            return False
        return True

    def _api_sepay_webhook(self, data: dict):
        """POST /api/payment/sepay/webhook — PAY-009: SePay bắn khi có biến động
        số dư khớp giao dịch chuyển khoản vào tài khoản đã cấu hình.

        LƯU Ý: tên field payload bên dưới (id/gateway/transferAmount/
        transferType/content) theo định dạng webhook phổ biến của SePay — CHƯA
        verify field-level với tài khoản thật, log toàn bộ payload thô để dễ
        chỉnh nếu field không khớp thực tế.

        Xác thực (2026-07-15, Harvey chọn HMAC-SHA256 thay vì Apikey tĩnh để an
        toàn hơn — xem SEPAY_HMAC_SECRET): ưu tiên HMAC-SHA256 nếu đã cấu hình
        secret, tự động fallback về Apikey tĩnh nếu chưa (không phá server cũ).
        """
        if _SEPAY_HMAC_SECRET:
            if not self._verify_sepay_hmac():
                _json(self, {"error": "invalid signature"}, 401)
                return
        else:
            auth_header = self.headers.get("Authorization", "")
            expected = f"Apikey {_SEPAY_API_KEY}"
            if not _SEPAY_API_KEY or not hmac.compare_digest(auth_header, expected):
                log.error("[PAY][SePay] webhook Authorization không hợp lệ")
                _json(self, {"error": "invalid api key"}, 401)
                return

        log.info(f"[PAY][SePay] webhook payload: {json.dumps(data, ensure_ascii=False)[:500]}")

        transfer_type = str(data.get("transferType", "in")).lower()
        if transfer_type != "in":
            _json(self, {"success": True})  # tiền ra khỏi tài khoản — bỏ qua
            return

        content       = str(data.get("content", "") or data.get("description", ""))
        amount        = data.get("transferAmount") or data.get("amount") or 0
        txn_id        = str(data.get("id") or data.get("referenceCode") or "")

        if _db_mod is None or not _db_mod.is_available():
            _json(self, {"error": "DB không khả dụng"}, 503)
            return

        order = _db_mod.find_pending_order_by_content(content)
        if not order:
            log.warning(f"[PAY][SePay] Không khớp đơn pending nào với content={content!r}")
            _json(self, {"success": True, "matched": False})
            return

        if float(amount) < order["amount_vnd"]:
            log.warning(f"[PAY][SePay] Số tiền thiếu: nhận {amount}, cần {order['amount_vnd']} (ref={order['ref_code']})")
            _json(self, {"success": True, "matched": False, "reason": "amount_mismatch"})
            return

        # GOV-003: SePay có thể gọi lại webhook — chặn xử lý trùng bằng txn_id.
        if not _db_mod.record_payment_once("sepay", txn_id or order["ref_code"], order["telegram_id"]):
            log.warning(f"[PAY][SePay][DUP] txn={txn_id} ref={order['ref_code']} đã xử lý trước đó — bỏ qua")
            _json(self, {"success": True, "matched": True, "duplicate": True})
            return

        paid_order = _db_mod.mark_bank_transfer_order_paid(order["ref_code"])
        if not paid_order:
            # Đơn đã được đánh dấu paid trước đó (race với dedup ở trên) — an toàn, bỏ qua.
            _json(self, {"success": True, "matched": True, "already_paid": True})
            return

        tg_id    = str(paid_order["telegram_id"])
        plan_key = paid_order["plan_key"] if paid_order["plan_key"] in PRO_PLANS else DEFAULT_PLAN
        plan     = PRO_PLANS[plan_key]

        # Voucher benefit_type='bonus_days' KHÔNG giảm giá lúc tạo đơn — cấp thêm
        # ngày ở ĐÚNG lúc này (thanh toán đã xác nhận thật), cộng dồn vào gói vừa mua.
        bonus_days = 0
        try:
            bonus_days = _db_mod.grant_voucher_bonus_days(order["ref_code"]) or 0
        except Exception as e:
            log.warning(f"[PAY][SePay] grant_voucher_bonus_days lỗi (không chặn cấp Pro): {e}")

        expires_at = None
        try:
            total_days = plan["days"] + bonus_days
            note = f"sepay {plan['label']} (ref={order['ref_code']}, {amount}đ)"
            if bonus_days:
                note += f" + voucher {bonus_days} ngày"
            result = _db_mod.extend_pro(tg_id, total_days, note=note)
            expires_at = result.get("pro_expires_at")
            log.info(f"[PAY][SePay] tier=pro extended {total_days}d ({plan['days']}+{bonus_days} bonus) for {tg_id}, expires {expires_at}")
            try:
                _db_mod.grant_referral_purchase_bonus(tg_id)
            except Exception as _rbe:
                log.warning(f"[PAY][SePay] grant_referral_purchase_bonus lỗi: {_rbe}")
        except Exception as e:
            log.error(f"[PAY][SePay] extend_pro error: {e}")

        cfg = _load_cfg()
        bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
        if bot_token and not bot_token.startswith("NHAP"):
            try:
                import requests as _req
                exp_str = expires_at.strftime("%d/%m/%Y") if expires_at else "?"
                _req.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": tg_id,
                        "parse_mode": "HTML",
                        "text": (
                            f"🌟 <b>Chào mừng bạn đến với Fund Tracker Pro!</b>\n\n"
                            f"✅ Thanh toán chuyển khoản {int(amount):,} đ thành công — gói <b>{plan['label']}</b>\n"
                            + (f"🎁 Tặng thêm <b>{bonus_days} ngày</b> từ voucher!\n" if bonus_days else "")
                            + f"📅 Gói Pro có hiệu lực đến: <b>{exp_str}</b>\n\n"
                            f"Gõ /app để mở Mini App ngay. 🚀"
                        ),
                    },
                    timeout=8,
                )
            except Exception as e:
                log.error(f"[PAY][SePay] sendMessage exception: {e}")

        _json(self, {"success": True, "matched": True})


# ── Start ──────────────────────────────────────────────────────────────────────

def _ensure_buy_signal_cols():
    """Thêm các cột mới vào buy_signals nếu chưa có (idempotent)."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=6)
        with conn.cursor() as cur:
            for col, typ in [("chg_pct","NUMERIC"), ("chg7d","NUMERIC"),
                              ("chg30d","NUMERIC"), ("details","JSONB"),
                              ("nav_date","DATE")]:
                cur.execute(f"ALTER TABLE buy_signals ADD COLUMN IF NOT EXISTS {col} {typ}")
        conn.commit(); conn.close()
        log.info("[miniapp] buy_signals schema ensured")
    except Exception as e:
        log.warning(f"[miniapp] buy_signals schema: {e}")


def start_miniapp_server():
    # Khởi tạo bảng PostgreSQL cho trades khi server start
    try:
        _init_trade_tables()
    except Exception as e:
        log.warning(f"[miniapp] trade tables init skipped: {e}")
    try:
        _ensure_buy_signal_cols()
    except Exception as e:
        log.warning(f"[miniapp] buy_signals cols init skipped: {e}")
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    server = ThreadingHTTPServer(("0.0.0.0", PORT_MINIAPP), MiniAppHandler)
    log.info(f"[miniapp] HTTP server started on :{PORT_MINIAPP}")
    server.serve_forever()


def start_in_thread():
    t = threading.Thread(target=start_miniapp_server, daemon=True, name="miniapp-server")
    t.start()
    return t
