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

import json
import logging
import os
import sys
import threading
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


# Import calc_signal + get_nav_series từ bot.py để dùng cùng logic tính tín hiệu
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from bot import calc_signal as _calc_signal_bot, get_nav_series as _get_nav_series_bot
    _BOT_IMPORTED = True
except Exception as _e:
    log.warning(f"[miniapp] Không import được bot.py: {_e}")
    _BOT_IMPORTED = False


def _get_signals_for_codes(codes: list, cfg: dict) -> dict:
    """Tính tín hiệu dùng đúng hàm calc_signal từ bot.py."""
    results = {}
    funds_cfg = cfg.get("funds", {})
    if _BOT_IMPORTED:
        for code in codes:
            try:
                pts = _get_nav_series_bot(code, funds_cfg.get(code, {}), cfg)
                if pts:
                    sig = _calc_signal_bot(code, pts)
                    results[code] = sig
                else:
                    results[code] = {"signal": "N/A", "score": 0, "nav": 0, "nav_date": "",
                                     "rsi": None, "bb_pct": None, "chg_pct": 0}
            except Exception as e:
                log.warning(f"[miniapp] calc_signal {code}: {e}")
                results[code] = {"signal": "N/A", "score": 0, "nav": 0, "nav_date": "",
                                 "rsi": None, "bb_pct": None, "chg_pct": 0}
    else:
        # Fallback: lấy NAV mới nhất từ DB, trả N/A signal
        db_url = os.environ.get("DATABASE_URL", cfg.get("database_url", ""))
        if db_url:
            try:
                import psycopg2
                conn = psycopg2.connect(db_url, connect_timeout=8)
                with conn.cursor() as cur:
                    ph = ",".join(["%s"] * len(codes))
                    cur.execute(f"""
                        SELECT DISTINCT ON (fund_code) fund_code, nav_date::text, nav::float
                        FROM nav_history WHERE fund_code IN ({ph})
                        ORDER BY fund_code, nav_date DESC
                    """, codes)
                    for code, nav_date, nav in cur.fetchall():
                        results[code] = {"signal": "N/A", "score": 0,
                                         "nav": nav, "nav_date": nav_date,
                                         "rsi": None, "bb_pct": None, "chg_pct": 0}
                conn.close()
            except Exception as e:
                log.warning(f"[miniapp] DB fallback: {e}")
    return results


def _calc_portfolio(profile: dict, signals: dict) -> dict:
    """Tính P&L từng quỹ và tổng danh mục."""
    holdings = profile.get("portfolio", [])
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


# ── Request Handler ────────────────────────────────────────────────────────────

class MiniAppHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.debug(fmt % args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        elif path == "/health":
            _json(self, {"ok": True, "ts": datetime.now().isoformat()})
        else:
            _json(self, {"error": "Not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        if path == "/api/trade":
            self._api_add_trade(data)
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
        # Lấy NAV + signals dùng cùng logic với bot.py
        watched  = profile.get("watched_funds", [])
        signals  = _get_signals_for_codes(watched, cfg)
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
        _json(self, {"signals": signals, "updated": datetime.now().isoformat()})

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
                pts = _gnv(code, cfg.get("funds", {}).get(code, {}), cfg)
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
        tg_id   = str(data.get("telegram_id", ""))
        code    = str(data.get("code", "")).upper()
        tx_type = str(data.get("type", "")).lower()
        units   = float(data.get("units", 0))
        amount  = float(data.get("amount", 0))
        tx_date = str(data.get("date", date.today().isoformat()))

        if not all([tg_id, code, tx_type in ("buy", "sell"), units > 0, amount > 0]):
            _json(self, {"error": "Thiếu hoặc sai thông tin giao dịch"}, 400)
            return

        cfg     = _load_cfg()
        profile = _find_profile(cfg, tg_id)
        if not profile:
            _json(self, {"error": "Profile không tìm thấy"}, 404)
            return

        if "portfolio" not in profile:
            profile["portfolio"] = []

        # Tìm holding hiện tại
        holding = next((h for h in profile["portfolio"] if h.get("code") == code), None)

        if tx_type == "buy":
            if holding:
                old_units = float(holding["units"])
                old_cost  = float(holding["avg_cost"])
                new_units = old_units + units
                new_cost  = (old_units * old_cost + amount) / new_units
                holding["units"]    = round(new_units, 4)
                holding["avg_cost"] = round(new_cost, 0)
            else:
                profile["portfolio"].append({
                    "code": code,
                    "units": round(units, 4),
                    "avg_cost": round(amount / units, 0),
                })
        elif tx_type == "sell":
            if not holding:
                _json(self, {"error": f"Không có {code} trong danh mục"}, 400)
                return
            new_units = float(holding["units"]) - units
            if new_units < 0:
                _json(self, {"error": f"Bán vượt số CCQ hiện có ({holding['units']})"}, 400)
                return
            if new_units < 0.001:
                profile["portfolio"] = [h for h in profile["portfolio"] if h.get("code") != code]
            else:
                holding["units"] = round(new_units, 4)

        _save_cfg(cfg)
        _json(self, {"ok": True, "code": code, "type": tx_type, "units": units, "amount": amount})


# ── Start ──────────────────────────────────────────────────────────────────────

def start_miniapp_server():
    server = HTTPServer(("0.0.0.0", PORT_MINIAPP), MiniAppHandler)
    log.info(f"[miniapp] HTTP server started on :{PORT_MINIAPP}")
    server.serve_forever()


def start_in_thread():
    t = threading.Thread(target=start_miniapp_server, daemon=True, name="miniapp-server")
    t.start()
    return t
