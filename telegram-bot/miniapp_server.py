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
import sys
import threading
import urllib.parse as _uparse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("miniapp")

ROOT      = Path(__file__).parent.parent
DATA_DIR  = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
CFG_FILE  = DATA_DIR / "config.json"
HTML_FILE = Path(__file__).parent / "miniapp" / "index.html"

# Railway inject PORT; fallback PORT_MINIAPP cho local dev
PORT_MINIAPP = int(os.environ.get("PORT_MINIAPP") or os.environ.get("PORT") or 8443)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    try:
        return json.loads(CFG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cfg(cfg: dict) -> None:
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _json(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _find_profile(cfg: dict, telegram_id: str):
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
}

def _gold_product_label(source: str, product: str) -> str:
    return _GOLD_LABELS.get(f"{source}:{product}", f"{source} {product}")


def _unit_to_luong(unit: str) -> float:
    """Quy đổi đơn vị về lượng. 1 lượng = 10 chỉ = 37.5g."""
    return {"luong": 1.0, "chi": 0.1, "gram": 1.0 / 37.5}.get(unit, 1.0)


def _calc_gold_signals(db_url: str) -> dict:
    """Tính RSI, BB, MA cho giá SJC từ 60 ngày gần nhất."""
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=6)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT price_date::text, sell_price::float
                FROM gold_prices WHERE source='SJC'
                ORDER BY price_date DESC LIMIT 60
            """)
            rows = cur.fetchall()
        conn.close()
        if len(rows) < 10:
            return {}
        rows = list(reversed(rows))
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
        # Signal score
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


def _calc_gold_portfolio(cfg: dict, tg_id: str, sjc_price: dict | None) -> dict:
    """Tính portfolio vàng: tổng lượng, avg cost, current value, P&L — đọc từ PostgreSQL."""
    total_luong  = 0.0
    total_cost   = 0.0
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, qty_luong, total_vnd FROM user_gold_trades "
                "WHERE telegram_id=%s ORDER BY trade_date, id",
                [tg_id]
            )
            rows = cur.fetchall()
        conn.close()
    except Exception as _e:
        log.warning(f"[gold_portfolio] DB error: {_e}")
        rows = []
    for (tx_type, qty_luong, total_vnd) in rows:
        ql = float(qty_luong or 0)
        tv = float(total_vnd or 0)
        if tx_type == "buy":
            total_luong += ql
            total_cost  += tv
        elif tx_type == "sell":
            sell_frac    = ql / total_luong if total_luong > 0 else 0
            total_cost  -= total_cost * sell_frac
            total_luong -= ql
    if total_luong < 0.001:
        return {"total_luong": 0.0, "avg_cost": 0, "current_value": 0, "pnl": 0, "pnl_pct": 0}
    avg_cost = total_cost / total_luong
    cur_sell = sjc_price["sell"] if sjc_price else 0
    cur_val  = total_luong * cur_sell
    pnl      = cur_val - total_cost
    pnl_pct  = pnl / total_cost * 100 if total_cost else 0
    return {
        "total_luong":    round(total_luong, 4),
        "avg_cost":       round(avg_cost, 0),
        "current_value":  round(cur_val, 0),
        "total_cost":     round(total_cost, 0),
        "pnl":            round(pnl, 0),
        "pnl_pct":        round(pnl_pct, 2),
        "current_price":  cur_sell,
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
     nav, signal_date, chg_pct, chg7d, chg30d, details_raw, nav_date) = row
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
    }

_SIGNAL_SELECT = """
    SELECT DISTINCT ON (fund_code)
        fund_code, strength, score,
        rsi, bb_pct, macd_hist,
        nav_at_signal, signal_date::text,
        chg_pct, chg7d, chg30d, details,
        nav_date::text
    FROM buy_signals
    WHERE fund_code IN ({ph})
    ORDER BY fund_code, signal_date DESC
"""


def _compute_and_save(missing_codes: list, cfg: dict):
    """Tính tín hiệu on-demand cho các quỹ chưa có trong buy_signals hôm nay."""
    if not _BOT_IMPORTED or not missing_codes:
        return
    from datetime import date as _date
    today = _date.today()
    strength_map = {
        "MUA MẠNH": "strong_buy", "MUA": "buy",
        "BÁN MẠNH": "strong_reduce", "BÁN": "reduce",
    }
    for code in missing_codes:
        try:
            fund_cfg = _FUND_CATALOG.get(code, cfg.get("funds", {}).get(code, {}))
            pts = _get_nav_series_bot(code, fund_cfg, cfg)
            if not pts:
                continue
            d = _calc_signal_bot(code, pts)
            sig = d.get("signal", "")
            strength = next((v for k, v in strength_map.items() if k in sig), "hold")
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
                        "momentum_30d": d.get("chg30"),
                        "chg_pct":      d.get("chg_pct"),
                        "chg7d":        d.get("chg7"),
                        "chg30d":       d.get("chg30"),
                        "details":      d.get("details", []),
                        "nav_date":     d.get("nav_date"),
                    },
                    settlement_rule=settle,
                )
                log.info(f"[miniapp] on-demand signal {code}: {sig}")
        except Exception as e:
            log.warning(f"[miniapp] _compute_and_save {code}: {e}")


def _get_signals_for_codes(codes: list, cfg: dict) -> dict:
    """Đọc tín hiệu từ buy_signals. Quỹ thiếu → tính on-demand rồi đọc lại."""
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
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=8)
        with conn.cursor() as cur:
            rows = _query(cur, codes)
        conn.close()
    except Exception as e:
        log.warning(f"[miniapp] _get_signals_for_codes DB: {e}")
        return results

    for row in rows:
        results[row[0]] = _row_to_signal(row)

    # Quỹ chưa có signal nào → tính on-demand
    missing = [c for c in codes if c not in results]
    if missing:
        _compute_and_save(missing, cfg)
        # Đọc lại sau khi đã save
        try:
            conn = psycopg2.connect(db_url, connect_timeout=8)
            with conn.cursor() as cur:
                rows2 = _query(cur, missing)
            conn.close()
            for row in rows2:
                results[row[0]] = _row_to_signal(row)
        except Exception as e:
            log.warning(f"[miniapp] re-query after compute: {e}")

    # Fallback cho quỹ vẫn không có data (không đủ NAV)
    for code in codes:
        if code not in results:
            results[code] = {"signal": "N/A", "score": 0, "nav": 0, "nav_date": "",
                             "rsi": None, "bb_pct": None, "chg_pct": 0, "details": []}
    return results


def _db_get_ccq_holdings(tg_id: str) -> list:
    """Tính holdings CCQ từ user_ccq_trades — luôn fresh từ DB."""
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT code, type, units, nav
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
    for code, tx_type, units, nav in rows:
        units = float(units or 0); nav = float(nav or 0)
        if tx_type == "buy":
            if code not in h: h[code] = {"units": 0.0, "total_cost": 0.0}
            h[code]["units"]      += units
            h[code]["total_cost"] += units * nav
        elif tx_type == "dividend":
            if code not in h: h[code] = {"units": 0.0, "total_cost": 0.0}
            h[code]["units"] += units
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


def _calc_portfolio(profile: dict, signals: dict) -> dict:
    """Tính P&L từng quỹ — holdings đọc thẳng từ DB (không dùng snapshot config)."""
    tg_id = str(profile.get("telegram_id", ""))
    holdings = _db_get_ccq_holdings(tg_id) if tg_id else profile.get("portfolio", [])
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
        vol   = s.get("vol_30d") or 10  # % annualized volatility
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

def _validate_init_data(init_data_str: str, bot_token: str):
    """Xác thực chữ ký HMAC của Telegram WebApp initData.
    Returns parsed user dict nếu hợp lệ, None nếu không hợp lệ hoặc thiếu.
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
        return json.loads(params.get("user", "{}"))
    except Exception:
        return None


def _auth_write(handler, claimed_tg_id: str) -> bool:
    """Kiểm tra quyền ghi: initData phải hợp lệ và user.id phải khớp claimed_tg_id.
    Cho phép admin (admin_telegram_id trong config) bypass mọi user.
    Trả về True nếu được phép, False và tự gửi 403 nếu bị từ chối.
    """
    cfg       = _load_cfg()
    bot_token = cfg.get("bot_token") or os.environ.get("BOT_TOKEN", "")
    admin_id  = str(cfg.get("admin_telegram_id", ""))

    # Admin luôn được phép (dùng cho import script)
    if claimed_tg_id and claimed_tg_id == admin_id:
        return True

    init_data = handler.headers.get("X-Init-Data", "")
    if not init_data:
        # Dev/local mode: nếu không có initData, kiểm tra môi trường
        if os.environ.get("MINIAPP_NO_AUTH"):
            return True
        _json(handler, {"error": "Yêu cầu xác thực Telegram"}, 403)
        return False

    user = _validate_init_data(init_data, bot_token)
    if not user:
        _json(handler, {"error": "initData không hợp lệ"}, 403)
        return False

    if str(user.get("id", "")) != str(claimed_tg_id):
        _json(handler, {"error": "Không có quyền thao tác trên tài khoản này"}, 403)
        return False

    return True


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
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_gold_tg ON user_gold_trades(telegram_id);
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-HTTP-Method-Override, X-Init-Data")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"
        qs     = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_html()
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
        elif path == "/health":
            _json(self, {"ok": True, "ts": datetime.now().isoformat()})
        else:
            _json(self, {"error": "Not found"}, 404)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
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
        else:
            _json(self, {"error": "Not found"}, 404)

    def do_POST(self):
        data   = self._read_body()
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/api/me/watched_funds":
            self._api_update_watched(data)
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
        elif path == "/api/admin/fixportfolio":
            self._api_admin_fixportfolio(data)
        elif path == "/api/admin/import-trades":
            self._api_admin_import_trades(data)
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

    def _api_me(self, qs: dict):
        tg_id = (qs.get("user_id") or qs.get("telegram_id") or [""])[0]
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400)
            return
        cfg     = _load_cfg()
        profile = _find_profile(cfg, tg_id)
        if not profile:
            _json(self, {"error": "Profile không tìm thấy", "telegram_id": tg_id}, 404)
            return
        # Lấy signals cho watched_funds + tất cả quỹ trong portfolio
        watched  = profile.get("watched_funds", [])
        holdings = _db_get_ccq_holdings(tg_id)
        portfolio_codes = [h["code"] for h in holdings]
        all_codes = list(dict.fromkeys(watched + portfolio_codes))  # dedup, preserve order
        signals  = _get_signals_for_codes(all_codes, cfg)
        portfolio = _calc_portfolio(profile, signals)
        _json(self, {
            "name": profile.get("name", ""),
            "telegram_id": tg_id,
            "watched_funds": watched,
            "monthly_dca": profile.get("monthly_dca", 0),
            "portfolio": portfolio,
            "signals": signals,
        })

    def _api_signals(self, qs: dict):
        tg_id   = (qs.get("user_id") or [""])[0]
        cfg     = _load_cfg()
        profile = _find_profile(cfg, tg_id) if tg_id else None
        watched = profile.get("watched_funds", []) if profile else list(cfg.get("funds", {}).keys())[:10]
        signals = _get_signals_for_codes(watched, cfg)
        all_funds = {code: info.get("name", code) for code, info in cfg.get("funds", {}).items()}
        _json(self, {"signals": signals, "updated": datetime.now().isoformat(),
                     "watched": watched, "all_funds": all_funds})

    def _api_update_watched(self, data: dict):
        """POST /api/me/watched_funds — cập nhật danh sách quỹ theo dõi."""
        tg_id   = str(data.get("telegram_id", ""))
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
        profile["watched_funds"] = valid
        _save_cfg(cfg)
        _json(self, {"ok": True, "watched_funds": valid})

    def _api_research(self, code: str, qs: dict):
        """Phân tích sâu 5 trường phái cho 1 quỹ — dùng msg_research logic từ bot."""
        if not code or len(code) > 10:
            _json(self, {"error": "Invalid code"}, 400)
            return
        cfg = _load_cfg()
        sigs = _get_signals_for_codes([code], cfg)
        d    = sigs.get(code, {})
        if not d or not d.get("nav"):
            _json(self, {"error": f"Không có dữ liệu cho {code}"}, 404)
            return

        # Tính extended stats (52w high/low, vol, drawdown) nếu import được bot
        stats = {}
        if _BOT_IMPORTED:
            try:
                from bot import get_nav_series as _gnv, _extended_stats
                pts = _gnv(code, _FUND_CATALOG.get(code, cfg.get("funds", {}).get(code, {})), cfg)
                if pts:
                    stats = _extended_stats(pts)
            except Exception as e:
                log.debug(f"[research] extended_stats {code}: {e}")

        nav  = d.get("nav", 0)
        rsi  = d.get("rsi")
        bb   = d.get("bb_pct")
        sc   = d.get("score", 0)
        ma20 = d.get("ma20") or 0
        ma50 = d.get("ma50") or 0
        chg30 = d.get("chg30")
        macd  = d.get("macd_hist")
        sig   = d.get("signal", "N/A")

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
        _json(self, {
            "code": code, "fund_name": fund_name,
            "nav": nav, "nav_date": d.get("nav_date",""),
            "signal": sig, "score": sc, "chg_pct": d.get("chg_pct", 0),
            "technical": {
                "verdict": ta_v, "score": sc,
                "rsi": rsi_note(rsi), "bb": bb_note(bb),
                "macd": ("Dương — Đà tăng 🟢" if macd and macd>0 else "Âm — Đà giảm ⚠️") if macd is not None else None,
                "ma": (f"MA20 {'>' if ma20>ma50 else '<'} MA50 → {'Xu hướng tăng ↑' if ma20>ma50 else 'Xu hướng giảm ↓'}") if ma20 and ma50 else None,
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
        tg_id  = (qs.get("user_id") or [""])[0]
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
        """POST /api/trade — thêm CCQ trade vào PostgreSQL."""
        tg_id    = str(data.get("telegram_id", ""))
        code     = str(data.get("code", "")).upper()
        tx_type  = str(data.get("type", "")).lower()
        units    = float(data.get("units", 0))
        amount   = float(data.get("amount", 0))
        tx_date  = str(data.get("date", date.today().isoformat()))
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
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "id": new_id, "code": code, "type": tx_type,
                     "units": units, "amount": amount, "nav_mismatch": nav_mm})

    def _api_get_trades(self, qs: dict):
        """GET /api/trades?user_id=... — trả về CCQ trades từ DB."""
        tg_id = (qs.get("user_id") or qs.get("telegram_id") or [""])[0]
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400); return
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
        cfg = _load_cfg()
        _db_recalc_portfolio(cfg, tg_id)
        _json(self, {"ok": True, "id": trade_id})

    # ── Gold APIs ────────────────────────────────────────────────────────────────

    def _api_gold(self, qs: dict):
        """GET /api/gold?user_id=... — giá vàng mới nhất + tín hiệu + portfolio."""
        tg_id = (qs.get("user_id") or [""])[0]
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

        # Tính signals từ lịch sử SJC (30 ngày gần nhất)
        signals = _calc_gold_signals(db_url) if db_url else {}

        # Portfolio vàng — tìm SJC_1L từ bất kỳ source nào
        sjc_price_entry = (
            prices.get("SJC:SJC_1L")
            or prices.get("VANGTODAYAPI:SJC_1L")
            or next((v for v in prices.values() if v.get("product") == "SJC_1L"), None)
        )
        portfolio = None
        if tg_id:
            cfg = _load_cfg()
            portfolio = _calc_gold_portfolio(cfg, tg_id, sjc_price_entry)

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
                if days > 0:
                    cur.execute("""
                        SELECT source, product, price_date::text, buy_price::float, sell_price::float, extra
                        FROM gold_prices
                        WHERE price_date >= CURRENT_DATE - INTERVAL %s
                          AND source IN ('SJC','GIAVANG_ORG','INTERNATIONAL')
                        ORDER BY price_date
                    """, (f"{days} days",))
                else:
                    cur.execute("""
                        SELECT source, product, price_date::text, buy_price::float, sell_price::float, extra
                        FROM gold_prices
                        WHERE source IN ('SJC','GIAVANG_ORG','INTERNATIONAL')
                        ORDER BY price_date
                    """)
                rows = cur.fetchall()
            conn.close()
            # SJC data: merge GIAVANG_ORG (monthly, long history) + SJC (daily, 1yr)
            # SJC source takes priority over GIAVANG_ORG for same date
            sjc_map = {}   # date -> {buy, sell, priority}
            xau_usd_pts, xau_vnd_pts = [], []
            usd_vnd_latest = None
            for src, prod, dt, buy, sell, extra in rows:
                if prod == "SJC_1L" and src in ("GIAVANG_ORG", "SJC"):
                    priority = 1 if src == "SJC" else 0
                    if dt not in sjc_map or priority > sjc_map[dt]["p"]:
                        sjc_map[dt] = {"buy": buy, "sell": sell, "p": priority}
                elif src == "INTERNATIONAL" and prod == "XAU_USD":
                    xau_usd_pts.append({"date": dt, "val": buy})
                    if extra and "usd_vnd" in extra:
                        usd_vnd_latest = extra["usd_vnd"]
                elif src == "INTERNATIONAL" and prod == "XAU_VND_LUONG":
                    xau_vnd_pts.append({"date": dt, "val": buy})
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
        tg_id = (qs.get("user_id") or [""])[0]
        if not tg_id:
            _json(self, {"error": "user_id required"}, 400); return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, product, type, trade_date::text, unit, qty, qty_luong,
                           price_per_luong, total_vnd, note
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
             "price_per_luong": r[7], "total_vnd": r[8], "note": r[9]}
            for r in rows
        ]
        _json(self, {"trades": trades})

    def _api_add_gold_trade(self, data: dict):
        """POST /api/gold/trade — thêm giao dịch vàng vào PostgreSQL."""
        tg_id   = str(data.get("telegram_id", ""))
        tx_type = str(data.get("type", "")).lower()
        unit    = str(data.get("unit", "luong")).lower()
        product = str(data.get("product", "SJC_1L"))
        qty     = float(data.get("qty", 0))
        price   = float(data.get("price_per_luong", 0))
        total   = float(data.get("total_vnd", 0)) or round(qty * price * _unit_to_luong(unit))
        tx_date = str(data.get("date", date.today().isoformat()))
        note    = str(data.get("note", ""))
        if not all([tg_id, tx_type in ("buy", "sell"), qty > 0, price > 0]):
            _json(self, {"error": "Thiếu hoặc sai thông tin"}, 400); return
        if not _auth_write(self, tg_id): return
        _init_trade_tables()
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_gold_trades
                      (telegram_id, product, type, trade_date, unit, qty, qty_luong,
                       price_per_luong, total_vnd, note)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, [tg_id, product, tx_type, tx_date, unit,
                      round(qty,4), round(qty * _unit_to_luong(unit),4),
                      round(price), round(total), note])
                new_id = cur.fetchone()[0]
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
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
                cur.execute("SELECT telegram_id, unit, qty, price_per_luong, total_vnd, trade_date::text, type, note FROM user_gold_trades WHERE id=%s", [trade_id])
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
        try:
            conn = _get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_gold_trades
                    SET unit=%s, qty=%s, qty_luong=%s, price_per_luong=%s,
                        total_vnd=%s, trade_date=%s, type=%s, note=%s
                    WHERE id=%s
                """, [unit, round(qty,4), round(qty*_unit_to_luong(unit),4),
                      round(price), round(total), tx_date, tx_type, note, trade_id])
            conn.commit(); conn.close()
        except Exception as e:
            _json(self, {"error": str(e)}, 500); return
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

    def _api_admin_import_trades(self, data: dict):
        """POST /api/admin/import-trades — bulk import CCQ trades vào PostgreSQL.
        Body: {telegram_id: str, trades: [{code, type, date, units, nav, amount}], replace: bool}
        replace=true → xóa toàn bộ trades của user trước khi import (dùng khi import lần đầu).
        """
        tg_id     = str(data.get("telegram_id", "")).strip()
        trades_in = data.get("trades", [])
        replace   = data.get("replace", False)
        if not tg_id or not trades_in:
            _json(self, {"error": "telegram_id and trades required"}, 400); return
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
                    if not code or units <= 0: continue
                    # Deduplicate
                    cur.execute("""
                        SELECT 1 FROM user_ccq_trades
                        WHERE telegram_id=%s AND code=%s AND trade_date=%s
                          AND ABS(units-%s)<0.01
                    """, [tg_id, code, dt, units])
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
        cfg = _load_cfg()
        if admin_id and admin_id != str(cfg.get("admin_telegram_id", "")):
            _json(self, {"error": "Unauthorized"}, 403)
            return
        cfg["tcbs_token"] = new_token
        _save_cfg(cfg)
        log.info(f"[admin] tcbs_token cập nhật (len={len(new_token)}) — sẽ fetch NAV ngay")
        # Fetch full DB NAV trong background, rồi gửi 1 message tổng hợp cho admin
        if _BOT_IMPORTED:
            admin_tg_id = str(cfg.get("admin_telegram_id", ""))
            bot_tok     = cfg.get("bot_token", "")
            _new_token  = new_token  # capture cho closure

            def _bg_fetch():
                import subprocess, sys as _sys
                try:
                    from bot import load_config as _lc, all_watched_codes as _awc
                    from bot import fetch_all as _fa, tg_send as _ts

                    # ── 1. harvest_nav.py --daily --jwt TOKEN (toàn bộ funds_master) ──
                    script = Path(__file__).parent.parent / "scripts" / "harvest_nav.py"
                    harvest_out, harvest_err = "", ""
                    total_new, updated_funds = 0, []
                    if script.exists():
                        res = subprocess.run(
                            [_sys.executable, str(script), "--daily", "--jwt", _new_token],
                            capture_output=True, text=True, timeout=300,
                            env={**__import__("os").environ},
                        )
                        harvest_out = (res.stdout or "").strip()
                        harvest_err = (res.stderr or "").strip()
                        log.info(f"[admin] harvest_nav: {harvest_out[-200:] if harvest_out else harvest_err[:200]}")
                        # Parse dòng summary "✅ Daily: +N records — TCBF(+1), TCFF(+3), ..."
                        for line in harvest_out.splitlines():
                            if "Daily:" in line and "+" in line:
                                import re
                                m = re.search(r"\+(\d+) records", line)
                                if m:
                                    total_new = int(m.group(1))
                                updated_funds = re.findall(r"([A-Z]+)\(\+\d+\)", line)
                    else:
                        log.warning("[admin] harvest_nav.py không tìm thấy")

                    # ── 2. Đếm tổng số quỹ trong funds_master từ harvest output ──
                    # Parse "X/Y funds checked" hoặc đếm từ updated_funds + skipped
                    total_funds = 0
                    fail_funds  = []
                    for line in harvest_out.splitlines():
                        # harvest log dạng: "⚠ X funds bỏ qua (không có JWT)"
                        import re
                        m_total = re.search(r"(\d+) quỹ", line)
                        if m_total and total_funds == 0:
                            total_funds = int(m_total.group(1))
                        # Tìm mã bị skip/lỗi
                        if "bỏ qua" in line or "lỗi" in line.lower():
                            skipped = re.findall(r"\b([A-Z]{3,8})\b", line)
                            fail_funds.extend(skipped)

                    ok_n   = len(updated_funds) if updated_funds else (total_funds - len(fail_funds))
                    total  = total_funds or ok_n

                    # ── 3. 1 message ngắn gọn dựa trên harvest_nav result ──
                    if admin_tg_id and bot_tok:
                        if total_new > 0:
                            msg = f"✅ NAV đã cập nhật ({ok_n}/{total} mã) — +{total_new} records"
                        else:
                            msg = f"✅ NAV đã up-to-date ({total} mã, không có records mới)"
                        if fail_funds:
                            fail_str = ", ".join(f"<code>{c}</code>" for c in sorted(set(fail_funds)))
                            msg += f"\n❌ Chưa lấy được ({len(set(fail_funds))} mã): {fail_str}"
                        _ts(bot_tok, admin_tg_id, msg)

                except Exception as _ex:
                    log.warning(f"[admin] Background fetch lỗi: {_ex}")

            threading.Thread(target=_bg_fetch, daemon=True, name="admin-nav-refresh").start()
        _json(self, {"ok": True, "msg": "tcbs_token updated, NAV fetch started in background"})

    def _api_admin_fetch_nav(self, data: dict):
        """POST /api/admin/fetch-nav — trigger fresh NAV fetch for all funds.
        Params: skip_tcbs (bool) — bỏ qua các quỹ TCBS nếu True
        Returns token_expired error nếu token không hợp lệ (sync check trước khi background).
        """
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
        funds_cfg = cfg.get("funds", {})

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
                            for _pt in pts_all:
                                _cur.execute(
                                    "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                                    "VALUES (%s, %s, %s, %s) "
                                    "ON CONFLICT (fund_code, nav_date) DO NOTHING",
                                    (code, _pt['date'], float(_pt['nav']), 'tcinvest')
                                )
                                _saved += _cur.rowcount
                            _conn.commit(); _conn.close()
                            results[code] = _saved
                            log.info(f"[fetch-nav] saved {code}: +{_saved}")
                        except Exception as ex:
                            errors[f"save_{code}"] = str(ex)
                            log.warning(f"save {code}: {ex}")
                log.info(f"[fetch-nav] done — results: {results}, errors: {errors}")
            except Exception as ex:
                log.error(f"[fetch-nav] fatal: {ex}")

        threading.Thread(target=_do_fetch, daemon=True, name="admin-fetch-nav").start()
        _json(self, {"ok": True, "msg": "NAV fetch started",
                     "skip_tcbs": skip_tcbs, "funds": list(funds_cfg.keys())})

    def _api_admin_import_nav(self, data: dict):
        """POST /api/admin/import-nav — bulk import NAV data {funds: {CODE: [{date, nav}]}}."""
        funds_data = data.get("funds", {})
        if not funds_data:
            _json(self, {"error": "funds required"}, 400)
            return
        db_url = os.environ.get("DATABASE_URL", _load_cfg().get("database_url", ""))
        if not db_url:
            _json(self, {"error": "DATABASE_URL not configured"}, 503)
            return

        import psycopg2, psycopg2.extras

        def _insert_pg(db_url, code, points, source='manual'):
            """Insert NAV points to PostgreSQL nav_history, return count inserted."""
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            inserted = 0
            for pt in points:
                cur.execute(
                    "INSERT INTO nav_history (fund_code, nav_date, nav, source) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (fund_code, nav_date) DO NOTHING",
                    (code, pt["date"], float(pt["nav"]), source)
                )
                inserted += cur.rowcount
            conn.commit()
            conn.close()
            return inserted

        results = {}
        errors = {}
        for code, pts in funds_data.items():
            if not pts:
                continue
            try:
                n = _insert_pg(db_url, code.upper(), pts)
                results[code.upper()] = n
                log.info(f"[import-nav] {code}: +{n} records")
            except Exception as ex:
                errors[code] = str(ex)
                log.warning(f"[import-nav] {code} error: {ex}")

        _json(self, {"ok": True, "inserted": results, "errors": errors,
                     "total": sum(results.values())})

    def _api_admin_fixportfolio(self, data: dict):
        """POST /api/admin/fixportfolio — sửa portfolio admin."""
        admin_id = str(data.get("admin_id", ""))
        code = str(data.get("code", "")).upper()
        avg_cost = data.get("avg_cost")
        units = data.get("units")
        if not code or avg_cost is None:
            _json(self, {"error": "code and avg_cost required"}, 400)
            return
        cfg = _load_cfg()
        if admin_id and admin_id != str(cfg.get("admin_telegram_id", "")):
            _json(self, {"error": "Unauthorized"}, 403)
            return
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
    server = HTTPServer(("0.0.0.0", PORT_MINIAPP), MiniAppHandler)
    log.info(f"[miniapp] HTTP server started on :{PORT_MINIAPP}")
    server.serve_forever()


def start_in_thread():
    t = threading.Thread(target=start_miniapp_server, daemon=True, name="miniapp-server")
    t.start()
    return t
