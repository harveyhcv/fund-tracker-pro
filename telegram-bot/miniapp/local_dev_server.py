"""local_dev_server.py — Chạy web.html với dữ liệu thật từ core_data/nav.db (SQLite).

Usage:
    cd telegram-bot/miniapp
    python local_dev_server.py

Mở: http://localhost:8080/web?user_id=1&name=Harvey
"""

import json
import math
import os
import sqlite3
import sys
import time
import threading
import urllib.parse
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent
NAV_DB  = ROOT.parent.parent / "core_data" / "nav.db"
USER_DB = ROOT / "local_users.db"
PORT    = int(os.environ.get("PORT", 8080))

# ── Local user DB (SQLite) ────────────────────────────────────────────────────
def _user_conn():
    conn = sqlite3.connect(str(USER_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _init_user_db():
    conn = _user_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        tier TEXT NOT NULL DEFAULT 'pro',
        is_admin INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        asset_type TEXT NOT NULL DEFAULT 'ccq',
        fund_code TEXT,
        trade_type TEXT NOT NULL,
        amount REAL,
        nav REAL,
        units REAL,
        trade_date TEXT,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS gold_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        gold_product TEXT NOT NULL,
        trade_type TEXT NOT NULL,
        units REAL NOT NULL,
        price REAL,
        trade_date TEXT,
        name TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

_db_lock = threading.Lock()

# ── NAV helpers ───────────────────────────────────────────────────────────────
def _nav_conn():
    return sqlite3.connect(str(NAV_DB), check_same_thread=False)

def get_nav_series(code: str, days: int = 400) -> list:
    conn = _nav_conn()
    cur = conn.execute(
        "SELECT date, nav FROM nav_history WHERE fund_code=? AND nav IS NOT NULL ORDER BY date DESC LIMIT ?",
        (code, days)
    )
    rows = [{"date": r[0], "nav": float(r[1])} for r in cur.fetchall()]
    conn.close()
    return list(reversed(rows))

def get_all_fund_codes() -> list:
    conn = _nav_conn()
    cur = conn.execute("SELECT code FROM funds ORDER BY code")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()
    return codes

def get_latest_nav(code: str):
    conn = _nav_conn()
    cur = conn.execute(
        "SELECT date, nav FROM nav_history WHERE fund_code=? ORDER BY date DESC LIMIT 1",
        (code,)
    )
    r = cur.fetchone()
    conn.close()
    return (r[0], float(r[1])) if r else (None, None)

# ── Indicator math (copied from bot.py) ──────────────────────────────────────
def _avg(lst): return sum(lst) / len(lst) if lst else 0

def _ema(series, period):
    if not series: return 0
    k = 2 / (period + 1)
    v = series[0]
    for x in series[1:]:
        v = x * k + v * (1 - k)
    return v

def calc_rsi(navs, period=14):
    if len(navs) < period + 1: return None
    window = navs[-(period + 1):]
    gains = losses = 0.0
    for i in range(1, len(window)):
        diff = window[i] - window[i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    if losses == 0: return 100.0
    return round(100 - 100 / (1 + gains / losses), 2)

def calc_bb(navs, period=20):
    if len(navs) < period: return None
    w = navs[-period:]
    m = _avg(w)
    std = math.sqrt(_avg([(x-m)**2 for x in w]))
    upper, lower = m + 2*std, m - 2*std
    pct = (navs[-1]-lower)/(upper-lower)*100 if upper != lower else 50.0
    return {"upper": upper, "lower": lower, "mid": m, "pct": round(pct, 1)}

def calc_macd(navs, fast=12, slow=26, signal_p=9):
    if len(navs) < slow + signal_p + 5: return None
    macd_line = _ema(navs[-fast-5:], fast) - _ema(navs[-slow-5:], slow)
    n = len(navs)
    macd_series = [
        _ema(navs[max(0,i-fast-4):i+1], fast) - _ema(navs[max(0,i-slow-4):i+1], slow)
        for i in range(n-signal_p-1, n)
    ]
    sig_line = _ema(macd_series, signal_p)
    return {"macd": round(macd_line, 4), "signal": round(sig_line, 4), "hist": round(macd_line - sig_line, 4)}

def calc_signal(code: str, pts: list) -> dict:
    if not pts or len(pts) < 30:
        return {"signal":"N/A","score":0,"rsi":None,"bb_pct":None,"macd_hist":None,
                "nav":0,"nav_date":"","chg_pct":0,"chg7":None,"chg30":None,"details":[]}
    navs = [p["nav"] for p in pts]
    last = navs[-1]; prev = navs[-2] if len(navs)>=2 else last
    chg_pct = round((last-prev)/prev*100, 2) if prev else 0
    chg7 = round((last/navs[-6]-1)*100, 2) if len(navs)>=6 else None
    chg30 = round((last/navs[-23]-1)*100, 2) if len(navs)>=23 else None
    score = 0; details = []

    rsi = calc_rsi(navs)
    bb = calc_bb(navs); bb_pct = bb["pct"] if bb else None
    macd = calc_macd(navs); macd_hist = macd["hist"] if macd else None

    if rsi is not None:
        if rsi < 30: score += 3; details.append(f"RSI {rsi:.0f} quá bán mạnh")
        elif rsi < 40: score += 2; details.append(f"RSI {rsi:.0f} quá bán")
        elif rsi < 48: score += 1; details.append(f"RSI {rsi:.0f} tích cực")
        elif rsi > 75: score -= 3; details.append(f"RSI {rsi:.0f} quá mua mạnh")
        elif rsi > 65: score -= 2; details.append(f"RSI {rsi:.0f} quá mua")
        else: details.append(f"RSI {rsi:.0f}")

    if macd_hist is not None:
        if macd_hist > 0: score += 1; details.append("MACD ▲")
        else: score -= 1; details.append("MACD ▼")

    if bb_pct is not None:
        if bb_pct < 10: score += 3; details.append(f"BB {bb_pct:.0f}% đáy dải")
        elif bb_pct < 20: score += 2; details.append(f"BB {bb_pct:.0f}% gần đáy")
        elif bb_pct > 90: score -= 3; details.append(f"BB {bb_pct:.0f}% đỉnh dải")
        elif bb_pct > 80: score -= 2; details.append(f"BB {bb_pct:.0f}% gần đỉnh")
        else: details.append(f"BB {bb_pct:.0f}%")

    if score >= 4: sig = "MUA MANH"
    elif score >= 2: sig = "MUA"
    elif score <= -4: sig = "BAN MANH"
    elif score <= -2: sig = "BAN"
    else: sig = "TRUNG LAP"

    return {"signal":sig, "score":score, "rsi":rsi, "bb_pct":bb_pct, "macd_hist":macd_hist,
            "nav":last, "nav_date":pts[-1]["date"], "chg_pct":chg_pct,
            "chg7":chg7, "chg30":chg30, "details":details}

# ── Portfolio calculation ─────────────────────────────────────────────────────
def _calc_portfolio(telegram_id: int) -> dict:
    conn = _user_conn()
    rows = conn.execute(
        "SELECT fund_code, trade_type, amount, nav, units, trade_date FROM trades WHERE telegram_id=? ORDER BY trade_date",
        (telegram_id,)
    ).fetchall()
    conn.close()

    holdings = {}
    for r in rows:
        code = r["fund_code"]
        if code not in holdings:
            holdings[code] = {"units": 0.0, "cost": 0.0}
        if r["trade_type"] == "buy":
            units = r["units"] or (r["amount"] / r["nav"] if r["nav"] else 0)
            holdings[code]["units"] += units
            holdings[code]["cost"] += r["amount"] or 0
        elif r["trade_type"] == "sell":
            units = r["units"] or (r["amount"] / r["nav"] if r["nav"] else 0)
            holdings[code]["units"] -= units
            holdings[code]["cost"] -= r["amount"] or 0
        elif r["trade_type"] == "div":
            holdings[code]["cost"] -= r["amount"] or 0

    items = []
    total_cost = total_value = 0.0
    for code, h in holdings.items():
        if h["units"] <= 0.001: continue
        nav_date, nav = get_latest_nav(code)
        if nav is None: continue
        value = h["units"] * nav
        avg_cost = h["cost"] / h["units"] if h["units"] else 0
        pnl = value - h["cost"]
        pnl_pct = pnl / h["cost"] * 100 if h["cost"] else 0
        pts = get_nav_series(code, 60)
        sig = calc_signal(code, pts)
        items.append({
            "code": code, "nav": nav, "units": round(h["units"], 4),
            "avg_cost": round(avg_cost, 0), "cost": round(h["cost"], 0),
            "value": round(value, 0), "pnl": round(pnl, 0),
            "pnl_pct": round(pnl_pct, 2), "chg_pct": sig["chg_pct"],
            "signal": sig["signal"]
        })
        total_cost += h["cost"]; total_value += value

    total_pnl = total_value - total_cost
    return {
        "total_cost": round(total_cost, 0),
        "total_value": round(total_value, 0),
        "total_pnl": round(total_pnl, 0),
        "total_pnl_pct": round(total_pnl/total_cost*100, 2) if total_cost else 0,
        "items": items
    }

def _calc_gold_portfolio(telegram_id: int) -> dict:
    conn = _user_conn()
    rows = conn.execute(
        "SELECT gold_product, trade_type, units, price FROM gold_trades WHERE telegram_id=?",
        (telegram_id,)
    ).fetchall()
    conn.close()
    by_product = {}
    for r in rows:
        prod = r["gold_product"]
        if prod not in by_product:
            by_product[prod] = {"luong": 0.0, "cost": 0.0}
        if r["trade_type"] == "buy":
            by_product[prod]["luong"] += r["units"]
            by_product[prod]["cost"] += (r["units"] * r["price"]) if r["price"] else 0
        elif r["trade_type"] == "sell":
            by_product[prod]["luong"] -= r["units"]
            by_product[prod]["cost"] -= (r["units"] * r["price"]) if r["price"] else 0
    total_luong = sum(v["luong"] for v in by_product.values() if v["luong"] > 0)
    total_cost = sum(v["cost"] for v in by_product.values() if v["luong"] > 0)
    return {
        "portfolio": {
            "total_luong": round(total_luong, 3),
            "total_cost": round(total_cost, 0),
            "current_value": 0, "pnl": 0, "pnl_pct": 0,
            "by_product": {p: {"label": p, "luong": round(v["luong"],3),
                               "avg_cost": round(v["cost"]/v["luong"],0) if v["luong"] else 0,
                               "price_buy": None, "value": 0, "pnl": 0, "pnl_pct": 0,
                               "price_missing": True}
                           for p, v in by_product.items() if v["luong"] > 0}
        }
    }

# ── User helper ───────────────────────────────────────────────────────────────
def _get_or_create_user(telegram_id: int, name: str) -> dict:
    with _db_lock:
        conn = _user_conn()
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO users (telegram_id, name, tier, is_admin) VALUES (?,?,?,?)",
                         (telegram_id, name or f"User{telegram_id}", "pro", 1))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        conn.close()
        return dict(row)

# ── HTTP Handler ──────────────────────────────────────────────────────────────
_signals_cache = {}
_signals_ts = 0
SIGNALS_TTL = 300  # 5 min cache

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # tắt log mặc định

    def _qs(self) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _path(self) -> str:
        return urllib.parse.urlparse(self.path).path

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, ct: str):
        if not path.exists():
            self.send_response(404); self.end_headers(); return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _user_id(self) -> int:
        try: return int(self._qs().get("user_id", 1))
        except: return 1

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET_inner()
        except Exception as e:
            import traceback
            print(f"[ERROR] GET {self.path}: {e}", flush=True)
            traceback.print_exc()
            try: self._json({"error": str(e)}, 500)
            except: pass

    def _do_GET_inner(self):
        path = self._path(); qs = self._qs()
        uid = self._user_id()
        name = qs.get("name", "Harvey")
        print(f"[DBG] GET {path} uid={uid}", flush=True)

        # ── Static files ──
        if path in ("/", "/web", "/web.html"):
            return self._serve_file(ROOT / "web.html", "text/html; charset=utf-8")
        if path == "/web_js.js":
            return self._serve_file(ROOT / "web_js.js", "application/javascript; charset=utf-8")
        if path == "/index.html":
            return self._serve_file(ROOT / "index.html", "text/html; charset=utf-8")

        # ── API: me ──
        if path == "/api/me":
            user = _get_or_create_user(uid, name)
            pf = _calc_portfolio(uid)
            return self._json({
                "telegram_id": uid, "name": user["name"], "tier": user["tier"],
                "is_admin": bool(user["is_admin"]),
                "pro_expires_at": "2099-01-01T00:00:00",
                "portfolio": pf
            })

        # ── API: gold ──
        if path == "/api/gold":
            return self._json(_calc_gold_portfolio(uid))

        # ── API: signals ──
        if path == "/api/signals":
            global _signals_cache, _signals_ts
            now = time.time()
            if now - _signals_ts > SIGNALS_TTL:
                codes = get_all_fund_codes()
                sigs = {}
                conn_u = _user_conn()
                held = {r[0] for r in conn_u.execute(
                    "SELECT DISTINCT fund_code FROM trades WHERE telegram_id=? AND trade_type='buy'", (uid,)
                ).fetchall()}
                conn_u.close()
                for code in codes:
                    pts = get_nav_series(code, 200)
                    s = calc_signal(code, pts)
                    sigs[code] = {**s, "has_position": code in held}
                _signals_cache = sigs; _signals_ts = now
            # merge has_position với uid hiện tại
            conn_u = _user_conn()
            held = {r[0] for r in conn_u.execute(
                "SELECT DISTINCT fund_code FROM trades WHERE telegram_id=?", (uid,)
            ).fetchall()}
            conn_u.close()
            merged = {k: {**v, "has_position": k in held} for k, v in _signals_cache.items()}
            return self._json({"signals": merged})

        # ── API: research/<code> ──
        if path.startswith("/api/research/"):
            code = path.split("/")[-1].upper()
            pts = get_nav_series(code, 400)
            s = calc_signal(code, pts)
            nav_hist = [{"date": p["date"], "nav": p["nav"]} for p in pts[-90:]]
            rsi = s["rsi"] or 50; bb = s["bb_pct"] or 50; score = s["score"]

            conclusion = f"Score {score:+d} — "
            if score >= 4: conclusion += "Tín hiệu MUA MẠNH. RSI và BB đều ở vùng quá bán, MACD đang tăng."
            elif score >= 2: conclusion += "Tín hiệu MUA. Nhiều chỉ báo kỹ thuật tích cực."
            elif score <= -4: conclusion += "Tín hiệu BÁN MẠNH. RSI và BB ở vùng quá mua."
            elif score <= -2: conclusion += "Tín hiệu BÁN. Áp lực bán đang tăng."
            else: conclusion += "Trung lập. Chưa có tín hiệu rõ ràng, theo dõi thêm."

            return self._json({
                "code": code, "name": code,
                "signal": s["signal"], "score": score,
                "nav": s["nav"], "nav_date": s["nav_date"],
                "chg_pct": s["chg_pct"], "rsi": rsi, "bb": bb,
                "macd": s["macd_hist"],
                "conclusion": conclusion,
                "nav_history": nav_hist,
                "schools": []
            })

        # ── API: history ──
        if path == "/api/history":
            conn = _user_conn()
            rows = conn.execute(
                "SELECT id,'ccq' as asset_type, fund_code, trade_type, amount, nav, units, trade_date, note FROM trades WHERE telegram_id=? ORDER BY trade_date DESC LIMIT 100",
                (uid,)
            ).fetchall()
            gold = conn.execute(
                "SELECT id,'gold' as asset_type, gold_product, trade_type, units, price, trade_date, name FROM gold_trades WHERE telegram_id=? ORDER BY trade_date DESC LIMIT 50",
                (uid,)
            ).fetchall()
            conn.close()
            trades = [dict(r) for r in rows] + [dict(r) for r in gold]
            trades.sort(key=lambda x: x.get("trade_date",""), reverse=True)
            return self._json({"trades": trades})

        # ── API: referral ──
        if path == "/api/referral/mine":
            return self._json({"code": f"LOCAL{uid}", "uses_count": 0})

        # ── Stubs ──
        if path.startswith("/api/"):
            return self._json({"ok": True, "msg": "local stub"})

        self.send_response(404); self.end_headers()

    def do_POST(self):
        path = self._path()
        length = int(self.headers.get("Content-Length", 0))
        body = {}
        if length:
            try: body = json.loads(self.rfile.read(length))
            except: pass

        uid = body.get("telegram_id") or self._user_id()
        try: uid = int(uid)
        except: uid = 1

        if path == "/api/trade":
            fund = body.get("fund_code","").upper()
            ttype = body.get("trade_type","buy")
            amount = body.get("amount") or 0
            nav = body.get("nav") or 0
            units = float(amount) / float(nav) if nav and amount and not body.get("units") else body.get("units") or 0
            trade_date = body.get("trade_date") or date.today().isoformat()
            note = body.get("note","")
            if not fund:
                return self._json({"error": "Thiếu fund_code"}, 400)
            with _db_lock:
                conn = _user_conn()
                conn.execute(
                    "INSERT INTO trades (telegram_id,asset_type,fund_code,trade_type,amount,nav,units,trade_date,note) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, "ccq", fund, ttype, amount, nav, round(float(units),4), trade_date, note)
                )
                conn.commit(); conn.close()
            _signals_ts = 0  # invalidate cache
            return self._json({"ok": True})

        if path == "/api/gold/trade":
            prod = body.get("product","").upper()
            ttype = body.get("trade_type","buy")
            units = body.get("units", 0)
            price = body.get("price")
            trade_date = body.get("trade_date") or date.today().isoformat()
            name = body.get("name","")
            if not prod:
                return self._json({"error": "Thiếu product"}, 400)
            with _db_lock:
                conn = _user_conn()
                conn.execute(
                    "INSERT INTO gold_trades (telegram_id,gold_product,trade_type,units,price,trade_date,name) VALUES (?,?,?,?,?,?,?)",
                    (uid, prod, ttype, units, price, trade_date, name)
                )
                conn.commit(); conn.close()
            return self._json({"ok": True})

        if path == "/api/dca":
            budget = float(body.get("budget", 0))
            uid_i = uid
            # tính DCA từ signals + portfolio
            conn_u = _user_conn()
            held = {r[0] for r in conn_u.execute(
                "SELECT DISTINCT fund_code FROM trades WHERE telegram_id=?", (uid_i,)
            ).fetchall()}
            conn_u.close()
            targets = list(held) or get_all_fund_codes()[:10]
            sigs = {}
            for code in targets:
                pts = get_nav_series(code, 100)
                sigs[code] = calc_signal(code, pts)
            total_w = sum(max(0, s["score"]+6) for s in sigs.values()) or 1
            allocs = []
            for code, s in sigs.items():
                w = max(0, s["score"]+6) / total_w
                amt = round(budget * w, 0)
                pct = round(w*100, 1)
                allocs.append({"code":code, "amount":amt, "pct":pct, "signal":s["signal"],
                                "reason":f"Score {s['score']:+d} · RSI {s['rsi'] or '—'}"})
            allocs.sort(key=lambda x: -x["amount"])
            return self._json({"allocations": allocs})

        # stubs
        if path.startswith("/api/"):
            return self._json({"ok": True})

        self.send_response(404); self.end_headers()

    def do_DELETE(self):
        if self._path().startswith("/api/"):
            return self._json({"ok": True})
        self.send_response(404); self.end_headers()


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not NAV_DB.exists():
        print(f"[ERROR] Không tìm thấy {NAV_DB}")
        print("        Chạy từ đúng thư mục: cd telegram-bot/miniapp && python local_dev_server.py")
        sys.exit(1)
    _init_user_db()
    print(f"[local_dev_server] NAV DB: {NAV_DB} ({NAV_DB.stat().st_size//1024}KB)")
    print(f"[local_dev_server] User DB: {USER_DB}")
    print(f"[local_dev_server] Serving on http://localhost:{PORT}")
    print(f"[local_dev_server] Mo trong browser: http://localhost:{PORT}/web?user_id=1&name=Harvey")
    print(f"[local_dev_server] Ctrl+C de dung")
    # Pre-warm signals cache SYNCHRONOUSLY before starting server
    print("[local_dev_server] Tinh toan signals cho 43 quy...")
    codes = get_all_fund_codes()
    _warm_sigs = {}
    for code in codes:
        pts = get_nav_series(code, 200)
        _warm_sigs[code] = calc_signal(code, pts)
    _signals_cache = _warm_sigs; _signals_ts = time.time()
    print(f"[local_dev_server] Xong! {len(_warm_sigs)} quy co tin hieu.")

    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
