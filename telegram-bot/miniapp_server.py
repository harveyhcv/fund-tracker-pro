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


def _calc_dca(profile: dict, signals: dict, budget: float = 0) -> dict:
    """
    Intelligent DCA: phân bổ ngân sách DCA theo tín hiệu.
    Quỹ RSI thấp / score cao → nhận % cao hơn.
    """
    holdings  = {h["code"]: h for h in profile.get("portfolio", []) if h.get("units", 0) > 0}
    watched   = profile.get("watched_funds", [])
    monthly   = budget or float(profile.get("monthly_dca", 0) or 0)

    if monthly <= 0:
        return {"error": "Chưa cấu hình ngân sách DCA", "budget": 0, "items": []}

    # Tính điểm ưu tiên mỗi quỹ
    priority = {}
    for code in watched:
        s = signals.get(code, {})
        score = s.get("score", 0)
        rsi   = s.get("rsi") or 50
        # Điểm ưu tiên: score kỹ thuật + bonus RSI thấp
        p = max(0, score + 1)  # score có thể âm
        if rsi < 35: p += 3
        elif rsi < 45: p += 2
        elif rsi < 55: p += 1
        priority[code] = max(p, 0.5)  # tối thiểu 0.5 để luôn có allocation

    total_p = sum(priority.values()) or 1
    items   = []
    for code in watched:
        s = signals.get(code, {})
        nav_now = s.get("nav", 0)
        pct     = priority[code] / total_p
        amount  = round(monthly * pct)
        units   = round(amount / nav_now, 4) if nav_now else 0
        h       = holdings.get(code, {})
        items.append({
            "code": code,
            "amount": amount,
            "pct_alloc": round(pct * 100, 1),
            "units_est": units,
            "nav": nav_now,
            "nav_date": s.get("nav_date", ""),
            "signal": s.get("signal", "N/A"),
            "rsi": s.get("rsi"),
            "score": s.get("score", 0),
            "current_units": float(h.get("units", 0)),
            "avg_cost": float(h.get("avg_cost", 0)),
        })
    # Sắp xếp theo ưu tiên giảm dần
    items.sort(key=lambda x: x["pct_alloc"], reverse=True)
    return {"budget": round(monthly), "items": items}


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
        cfg    = _load_cfg()
        profile = _find_profile(cfg, tg_id) if tg_id else None
        if not profile:
            _json(self, {"error": "Profile không tìm thấy"}, 404)
            return
        watched  = profile.get("watched_funds", [])
        signals  = _get_signals_for_codes(watched, cfg)
        result   = _calc_dca(profile, signals, budget)
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
