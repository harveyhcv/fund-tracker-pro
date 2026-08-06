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

# Fix Unicode print trên Windows (cp1252 không encode được tiếng Việt)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import threading
import urllib.parse
import urllib.request
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
NAV_DB      = ROOT.parent.parent / "core_data" / "nav.db"
USER_DB     = ROOT / "local_users.db"
LOCAL_CFG   = ROOT / "local_config.json"
PORT        = int(os.environ.get("PORT", 8080))

# ── Fetch config ──────────────────────────────────────────────────────────────
PROTECTED_SOURCES = {"fixed", "manual", "confirmed", "tcinvest"}

# fmarket_id cho các quỹ có trên fmarket (None = chỉ dùng TCInvest)
FUND_FMARKET: dict = {
    "SSISCA": 11, "VCBFBCF": 32, "VCBFFIF": 33, "VCBFAIF": 82,
    "VESAF": 23, "VEOF": 20, "VDEF": 80, "VIBF": 22, "VMEEF": 68,
    "UVDIF": 78, "UVEEF": 58, "DCAF": 29, "DCDE": 25, "DCBF": 49,
    "DCDS": 43, "MBVF": 77, "MBBF": 37, "BVPF": 47, "DFIX": 66,
    "ESBF": 71, "ESSCF": 72, "KDEF": 64, "LHCDF": 63, "MAGEF": 73,
    "MAFPF1": 69, "MIRAEF": 57, "NTPPF": 62, "PHVSF": 59, "MABF": 84,
}
TCINVEST_ALIASES = {"VMEEF": "VMPF", "NTPPF": "TVPF"}

def _load_local_cfg() -> dict:
    if LOCAL_CFG.exists():
        try: return json.loads(LOCAL_CFG.read_text("utf-8"))
        except: pass
    return {}

def _save_local_cfg(data: dict):
    LOCAL_CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

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

# ── Fund type classification ──────────────────────────────────────────────────
_FUND_TYPE_CACHE: dict = {}

_BOND_KEYWORDS    = ['trái phiếu', 'tích lũy', 'hưu trí', 'thu nhập cố định', 'bền vững',
                     'fixed income', 'tpdn', 'có bảo đảm', 'tiền tệ']
_EQUITY_KEYWORDS  = ['cổ phiếu', 'tăng trưởng toàn cầu', 'năng động', 'emerging', 'tăng trưởng cổ phiếu']
_BALANCED_KEYWORDS= ['cân bằng']

def get_fund_type(code: str) -> str:
    """Trả về 'bond' | 'equity' | 'balanced'. Cache từ DB."""
    if code in _FUND_TYPE_CACHE:
        return _FUND_TYPE_CACHE[code]
    conn = _nav_conn()
    row = conn.execute("SELECT name, fund_type FROM funds WHERE code=?", (code,)).fetchone()
    conn.close()
    if row:
        stored_type = (row[1] or '').lower()
        if stored_type in ('bond', 'equity', 'balanced', 'money_market'):
            _FUND_TYPE_CACHE[code] = stored_type
            return stored_type
        name = (row[0] or '').lower()
        if any(k in name for k in _BOND_KEYWORDS):
            t = 'bond'
        elif any(k in name for k in _BALANCED_KEYWORDS):
            t = 'balanced'
        else:
            t = 'equity'
    else:
        t = 'equity'
    _FUND_TYPE_CACHE[code] = t
    return t

def filter_nav_anomalies(pts: list, fund_type: str = 'equity') -> list:
    """Lọc điểm NAV bất thường (spike/drop đột ngột). Bond: ±5%, Equity: ±20%."""
    if len(pts) < 3:
        return pts
    threshold = 5.0 if fund_type == 'bond' else 20.0
    clean = [pts[0]]
    for i in range(1, len(pts)):
        prev = clean[-1]['nav']
        curr = pts[i]['nav']
        if prev > 0:
            chg = abs(curr - prev) / prev * 100
            if chg > threshold:
                # Check if next point confirms (real move) or reverts (bad data)
                if i + 1 < len(pts):
                    nxt = pts[i + 1]['nav']
                    # If next is close to prev → curr is a spike → skip
                    if prev > 0 and abs(nxt - prev) / prev * 100 < threshold:
                        continue
        clean.append(pts[i])
    return clean

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
    """RSI theo Wilder's exponential smoothing — đồng nhất với bot.py."""
    if len(navs) < period + 1: return None
    deltas = [navs[i] - navs[i-1] for i in range(1, len(navs))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0: return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)

def calc_bb(navs, period=20):
    if len(navs) < period: return None
    w = navs[-period:]
    m = _avg(w)
    std = math.sqrt(_avg([(x-m)**2 for x in w]))
    upper, lower = m + 2*std, m - 2*std
    pct = (navs[-1]-lower)/(upper-lower)*100 if upper != lower else 50.0
    return {"upper": upper, "lower": lower, "mid": m, "pct": round(pct, 1)}

def calc_macd(navs, fast=12, slow=26, signal_p=9):
    """MACD với full-history EMA warm-up — đồng nhất với bot.py."""
    if len(navs) < slow + signal_p: return None
    k_f = 2.0/(fast+1); k_s = 2.0/(slow+1); k_g = 2.0/(signal_p+1)
    ef = sum(navs[:fast])/fast; es = sum(navs[:slow])/slow
    for v in navs[fast:slow]: ef = v*k_f + ef*(1-k_f)
    macd_vals = []
    for v in navs[slow:]:
        ef = v*k_f + ef*(1-k_f); es = v*k_s + es*(1-k_s)
        macd_vals.append(ef - es)
    if len(macd_vals) < signal_p: return None
    sg = sum(macd_vals[:signal_p])/signal_p
    for v in macd_vals[signal_p:]: sg = v*k_g + sg*(1-k_g)
    macd_r = round(macd_vals[-1], 4); sg_r = round(sg, 4)
    return {"macd": macd_r, "signal": sg_r, "hist": round(macd_r - sg_r, 4)}

def calc_ensemble_predict(navs: list, horizon: int = 2, fund_type: str = "equity") -> dict | None:
    """
    Ensemble prediction, điều chỉnh theo loại quỹ:
    - Equity:       LinReg(30d)×40% + Mom5×35% + Mom3×25%  — phản ứng nhanh với momentum
    - Bond:         LinReg(60d)×70% + Mom10×20% + Mom5×10% — xu hướng dài, bỏ qua spike coupon
    - Balanced:     LinReg(45d)×55% + Mom5×28% + Mom3×17%
    - Money market: Trả về None (NAV gần như cố định, dự báo vô nghĩa)
    """
    if not navs or len(navs) < 10:
        return None
    if fund_type == "money_market":
        return None  # Quỹ tiền tệ không cần dự báo — NAV tăng tuyến tính ổn định

    if fund_type == "bond":
        window, w_reg, w_m5, w_m3 = 60, 0.70, 0.20, 0.10
        mom_fast, mom_slow = 5, 10
    elif fund_type == "balanced":
        window, w_reg, w_m5, w_m3 = 45, 0.55, 0.28, 0.17
        mom_fast, mom_slow = 3, 5
    else:  # equity (default)
        window, w_reg, w_m5, w_m3 = 30, 0.40, 0.35, 0.25
        mom_fast, mom_slow = 3, 5

    tail = navs[-window:] if len(navs) >= window else navs
    n = len(tail)
    xs = list(range(n)); ys = tail
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    vx  = sum((x-mx)**2 for x in xs)
    slope = cov/vx if vx else 0
    reg_nav = my + slope*(n - 1 + horizon - mx)

    mom_s = tail[-1] + (tail[-1]-tail[-mom_slow-1])/mom_slow*horizon if n > mom_slow else reg_nav
    mom_f = tail[-1] + (tail[-1]-tail[-mom_fast-1])/mom_fast*horizon if n > mom_fast else reg_nav

    pred = round(reg_nav*w_reg + mom_s*w_m5 + mom_f*w_m3, 0)
    curr = tail[-1]
    pct  = round((pred - curr)/curr*100, 3) if curr else 0

    # Confidence: thấp nếu regression slope gần 0 (quỹ đứng yên) hoặc window nhỏ
    r_squared = None
    if vx > 0 and n > 5:
        ss_res = sum((ys[i]-(my+slope*(xs[i]-mx)))**2 for i in range(n))
        ss_tot = sum((y-my)**2 for y in ys)
        r_squared = round(1 - ss_res/ss_tot, 3) if ss_tot > 0 else None

    return {"nav": pred, "pct": pct, "horizon": horizon,
            "window": window, "r2": r_squared, "fund_type": fund_type}

def calc_signal(code: str, pts: list) -> dict:
    if not pts or len(pts) < 30:
        return {"signal":"N/A","score":0,"rsi":None,"bb_pct":None,"macd_hist":None,
                "nav":0,"nav_date":"","chg_pct":0,"chg7":None,"chg30":None,"details":[],
                "fund_type":"equity"}
    fund_type = get_fund_type(code)

    # Lọc anomaly trước khi tính chỉ số
    pts_clean = filter_nav_anomalies(pts, fund_type)
    if len(pts_clean) < 30:
        pts_clean = pts  # fallback nếu lọc quá nhiều

    navs = [p["nav"] for p in pts_clean]
    last = navs[-1]; prev = navs[-2] if len(navs)>=2 else last
    chg_pct = round((last-prev)/prev*100, 2) if prev else 0
    # chg7: 7 trading days = index -8 (8th from last = 7 intervals)
    chg7   = round((last/navs[-8]  -1)*100, 2) if len(navs)>=8   else None
    chg30  = round((last/navs[-22] -1)*100, 2) if len(navs)>=22  else None
    chg90  = round((last/navs[-65] -1)*100, 2) if len(navs)>=65  else None
    chg180 = round((last/navs[-130]-1)*100, 2) if len(navs)>=130 else None
    chg1y  = round((last/navs[-252]-1)*100, 2) if len(navs)>=252 else None

    # Volatility (annualized 20-day std of daily returns)
    vol_ann = None
    if len(navs) >= 22:
        rets = [(navs[i]-navs[i-1])/navs[i-1] for i in range(max(1,len(navs)-21),len(navs)) if navs[i-1]>0]
        if len(rets)>=10:
            mean_r = sum(rets)/len(rets)
            var_r  = sum((r-mean_r)**2 for r in rets)/len(rets)
            vol_ann = round((var_r**0.5)*(252**0.5)*100, 2)

    # Tech reliability — equity: HIGH, balanced: MEDIUM, bond: LOW, money_market: N/A
    tech_reliability = {"equity":"HIGH","balanced":"MEDIUM","bond":"LOW","money_market":"N/A"}.get(fund_type,"MEDIUM")

    # Money market: NAV tăng tuyến tính, kỹ thuật vô nghĩa
    if fund_type == "money_market":
        return {"signal":"TRUNG LẬP","score":0,"rsi":None,"bb_pct":None,"macd_hist":None,
                "nav":last,"nav_date":pts_clean[-1]["date"],"chg_pct":chg_pct,
                "chg7":chg7,"chg30":chg30,"chg90":chg90,"chg180":chg180,"chg1y":chg1y,
                "vol_ann":vol_ann,"tech_reliability":"N/A","fund_type":fund_type,
                "details":["Quỹ tiền tệ — NAV tăng ổn định, phân tích kỹ thuật không áp dụng"]}

    # Dùng ngưỡng anomaly theo fund type (equity 15%, bond 8%)
    anomaly_threshold = 8.0 if fund_type == 'bond' else 15.0
    if prev > 0 and abs(chg_pct) > anomaly_threshold:
        return {"signal":"N/A","score":0,"rsi":None,"bb_pct":None,"macd_hist":None,
                "nav":last,"nav_date":pts_clean[-1]["date"],"chg_pct":chg_pct,
                "chg7":chg7,"chg30":chg30,"chg90":chg90,"chg180":chg180,"chg1y":chg1y,
                "vol_ann":vol_ann,"tech_reliability":tech_reliability,"fund_type":fund_type,
                "nav_jump_anomaly":True,"details":[f"NAV jump {chg_pct:+.1f}% — có thể do sáp nhập/chia tách"]}
    score = 0; details = []

    rsi = calc_rsi(navs)
    bb = calc_bb(navs); bb_pct = bb["pct"] if bb else None
    macd = calc_macd(navs); macd_hist = macd["hist"] if macd else None

    is_bond = fund_type in ('bond',)

    # RSI scoring — quỹ trái phiếu: RSI cao là bình thường (trend tăng đều)
    if rsi is not None:
        if is_bond:
            # Bond: chỉ score khi RSI rất thấp (dấu hiệu đột biến)
            if rsi < 30: score += 2; details.append(f"RSI {rsi:.0f} bán tháo (bond)")
            else: details.append(f"RSI {rsi:.0f} (bond — bình thường)")
        else:
            if rsi < 30: score += 3; details.append(f"RSI {rsi:.0f} quá bán mạnh")
            elif rsi < 40: score += 2; details.append(f"RSI {rsi:.0f} quá bán")
            elif rsi < 48: score += 1; details.append(f"RSI {rsi:.0f} tích cực")
            elif rsi > 75: score -= 3; details.append(f"RSI {rsi:.0f} quá mua mạnh")
            elif rsi > 65: score -= 2; details.append(f"RSI {rsi:.0f} quá mua")
            else: details.append(f"RSI {rsi:.0f}")

    # MACD scoring — áp dụng cho cả 2 loại
    if macd_hist is not None:
        if is_bond:
            # Bond MACD nhỏ hơn nhiều — chỉ dùng chiều
            if macd_hist > 0: score += 1; details.append("MACD ▲")
            else: score -= 1; details.append("MACD ▼")
        else:
            if macd_hist > 0: score += 1; details.append("MACD ▲")
            else: score -= 1; details.append("MACD ▼")

    # BB% scoring — quỹ trái phiếu: BB cao là bình thường (trend tăng đều)
    if bb_pct is not None:
        if is_bond:
            # Bond: chỉ score khi BB rất thấp (đột biến giảm)
            if bb_pct < 0:    score += 3; details.append(f"BB {bb_pct:.0f}% dưới band (bond)")
            elif bb_pct < 10: score += 2; details.append(f"BB {bb_pct:.0f}% đáy (bond)")
            else: details.append(f"BB {bb_pct:.0f}% (bond — bình thường)")
        else:
            if bb_pct < 0:    score += 4; details.append(f"BB {bb_pct:.0f}% dưới band")
            elif bb_pct < 10: score += 3; details.append(f"BB {bb_pct:.0f}% đáy dải")
            elif bb_pct < 20: score += 2; details.append(f"BB {bb_pct:.0f}% gần đáy")
            elif bb_pct > 100: score -= 4; details.append(f"BB {bb_pct:.0f}% trên band")
            elif bb_pct > 90: score -= 3; details.append(f"BB {bb_pct:.0f}% đỉnh dải")
            elif bb_pct > 80: score -= 2; details.append(f"BB {bb_pct:.0f}% gần đỉnh")
            else: details.append(f"BB {bb_pct:.0f}%")

    if score >= 6: sig = "MUA MẠNH"
    elif score >= 3: sig = "MUA"
    elif score <= -6: sig = "BÁN MẠNH"
    elif score <= -3: sig = "BÁN"
    else: sig = "TRUNG LẬP"

    return {"signal":sig, "score":score, "rsi":rsi, "bb_pct":bb_pct, "macd_hist":macd_hist,
            "nav":last, "nav_date":pts_clean[-1]["date"], "chg_pct":chg_pct,
            "chg7":chg7, "chg30":chg30, "chg90":chg90, "chg180":chg180, "chg1y":chg1y,
            "vol_ann":vol_ann, "tech_reliability":tech_reliability,
            "details":details, "fund_type":fund_type}

# ── NAV fetch helpers ─────────────────────────────────────────────────────────
def _http_json(url: str, headers: dict = None, body: bytes = None, method: str = None) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[HTTP] {url}: {e}", flush=True)
        return {}

def fetch_tcinvest_nav(code: str, token: str) -> list:
    """Returns [{date, nav}] sorted ascending."""
    alias = TCINVEST_ALIASES.get(code, code)
    url = f"https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={alias}&timeline=ALL"
    hdrs = {
        "Accept": "application/json", "Accept-language": "vi",
        "Origin": "https://tcinvest.tcbs.com.vn",
        "Referer": "https://tcinvest.tcbs.com.vn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    if token: hdrs["Authorization"] = f"Bearer {token}"
    data = _http_json(url, hdrs)
    rows = data if isinstance(data, list) else (data.get("data") or [])
    pts = []
    for r in rows:
        d = r.get("matchedDate") or r.get("date") or ""
        n = r.get("navCurrent") or r.get("nav")
        if d and n:
            pts.append({"date": str(d)[:10], "nav": float(n)})
    pts.sort(key=lambda x: x["date"])
    return pts

def fetch_fmarket_nav(fmarket_id: int) -> list:
    """Returns [{date, nav}] sorted ascending."""
    today = date.today().strftime("%Y%m%d")
    url = "https://api.fmarket.vn/res/product/get-nav-history"
    body = json.dumps({"isAllData": 1, "productId": fmarket_id, "fromDate": None, "toDate": today}).encode()
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    data = _http_json(url, hdrs, body)
    # parse nhiều kiểu response từ fmarket (list / dict / nested)
    if isinstance(data, list):
        items = data
    else:
        inner = data.get("data")
        if isinstance(inner, list):
            items = inner
        elif isinstance(inner, dict):
            items = inner.get("navHistories") or []
        else:
            items = data.get("navHistories") or []
    pts = []
    for r in items:
        d = r.get("navDate") or r.get("date") or ""
        n = r.get("nav") or r.get("navValue")
        if d and n:
            pts.append({"date": str(d)[:10], "nav": float(n)})
    pts.sort(key=lambda x: x["date"])
    return pts

def upsert_nav_safe(code: str, pts: list, source: str):
    """Upsert NAV vào nav.db — không ghi đè PROTECTED_SOURCES."""
    if not pts: return 0
    conn = _nav_conn()
    written = 0
    for p in pts:
        d, n = p["date"], p["nav"]
        existing = conn.execute(
            "SELECT source, status FROM nav_history WHERE fund_code=? AND date=?", (code, d)
        ).fetchone()
        if existing and (existing[0] in PROTECTED_SOURCES or existing[1] == 'verified'):
            continue
        conn.execute(
            """INSERT INTO nav_history (fund_code, date, nav, source, status, updated_at)
               VALUES (?, ?, ?, ?, 'verified', datetime('now'))
               ON CONFLICT(fund_code, date) DO UPDATE SET
                 nav=excluded.nav, source=excluded.source, updated_at=datetime('now')
               WHERE status != 'verified'""",
            (code, d, n, source)
        )
        written += 1
    conn.commit(); conn.close()
    return written

_fetch_log: list = []  # audit trail for admin UI

def _run_fetch_all(token: str, skip_tcbs: bool = False):
    """Chạy trong background thread — fetch NAV từ TCInvest + fmarket."""
    global _fetch_log, _signals_ts
    conn = _nav_conn()
    codes = [r[0] for r in conn.execute("SELECT code FROM funds ORDER BY code").fetchall()]
    conn.close()
    log = []
    print(f"[FETCH] Bắt đầu fetch {len(codes)} quỹ (skip_tcbs={skip_tcbs})", flush=True)
    for code in codes:
        written = 0
        source = None
        if not skip_tcbs:
            pts = fetch_tcinvest_nav(code, token)
            if pts:
                written = upsert_nav_safe(code, pts, "tcinvest")
                source = "tcinvest"
        if not written:
            fid = FUND_FMARKET.get(code)
            if fid:
                pts = fetch_fmarket_nav(fid)
                if pts:
                    written = upsert_nav_safe(code, pts, "fmarket")
                    source = "fmarket"
        entry = {"code": code, "written": written, "source": source or "—", "ts": datetime.now().isoformat()[:16]}
        log.append(entry)
        print(f"[FETCH] {code}: {written} rows ({source or 'skip'})", flush=True)
    _fetch_log = log
    _signals_ts = 0  # invalidate signals cache
    print(f"[FETCH] Hoàn thành. Tổng rows mới: {sum(x['written'] for x in log)}", flush=True)

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

# ── Local gold price cache (vang.today → SQLite) ─────────────────────────────

_VANGTODAY_MAP = {
    "SJL1L10":     "SJC_1L",       "DOHNL":       "DOJI_NHAN_9999",
    "DOHCML":      "DOJI_NHAN_HCM","DOJINHTV":    "DOJI_JEWELRY",
    "SJ9999":      "SJC_NHAN",     "PQHNVM":      "PNJ_HN",
    "PQHN24NTT":   "PNJ_24K",      "BT9999NTT":   "BAOTINNGUYEN",
    "BTSJC":       "BAOTINSJC",    "VNGSJC":       "VNGOLD_SJC",
    "VIETTINMSJC": "VIETTIN_SJC",  "XAUUSD":      "XAUUSD",
}
_GOLD_LABELS = {
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

def _ensure_gold_prices_sqlite(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_prices (
            price_date TEXT NOT NULL, source TEXT NOT NULL, product TEXT NOT NULL,
            buy_price REAL, sell_price REAL, currency TEXT DEFAULT 'VND', extra TEXT,
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            PRIMARY KEY (price_date, source, product)
        )
    """)
    conn.commit()

def _fetch_gold_to_sqlite_local() -> int:
    """Fetch từ vang.today và lưu vào local SQLite. Trả về số bản ghi đã lưu."""
    url = "https://www.vang.today/api/prices"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            envelope = json.loads(resp.read().decode())
        raw = envelope.get("prices", envelope) if isinstance(envelope, dict) else {}
    except Exception as e:
        print(f"[gold] fetch vang.today failed: {e}")
        return 0
    today = str(date.today())
    conn = sqlite3.connect(str(USER_DB))
    _ensure_gold_prices_sqlite(conn)
    saved = 0
    for type_code, product in _VANGTODAY_MAP.items():
        item = raw.get(type_code)
        if not item:
            continue
        buy  = float(item.get("buy")  or 0)
        sell = float(item.get("sell") or 0)
        curr = item.get("currency", "VND")
        extra_str = json.dumps({"name": item.get("name", ""), "type_code": type_code,
                                 "change_buy": item.get("change_buy", 0)})
        conn.execute("""
            INSERT INTO gold_prices (price_date, source, product, buy_price, sell_price, currency, extra)
            VALUES (?, 'VANGTODAYAPI', ?, ?, ?, ?, ?)
            ON CONFLICT(price_date, source, product) DO UPDATE SET
                buy_price=excluded.buy_price, sell_price=excluded.sell_price,
                extra=excluded.extra, updated_at=strftime('%Y-%m-%d %H:%M:%S','now')
        """, (today, product, buy, sell, curr, extra_str))
        saved += 1
    conn.commit(); conn.close()
    print(f"[gold] saved {saved} prices to SQLite ({today})")
    return saved

def _get_gold_prices_local() -> dict:
    """Đọc giá vàng hôm nay từ SQLite, auto-fetch nếu chưa có."""
    from datetime import timedelta
    conn = sqlite3.connect(str(USER_DB))
    _ensure_gold_prices_sqlite(conn)
    today = str(date.today())
    count = conn.execute(
        "SELECT COUNT(*) FROM gold_prices WHERE price_date=? AND source='VANGTODAYAPI'", (today,)
    ).fetchone()[0]
    conn.close()
    if count == 0:
        _fetch_gold_to_sqlite_local()
    conn = sqlite3.connect(str(USER_DB))
    _ensure_gold_prices_sqlite(conn)
    cutoff = str(date.today() - timedelta(days=7))
    rows = conn.execute("""
        SELECT source, product, buy_price, sell_price, price_date, currency, extra
        FROM gold_prices WHERE price_date >= ?
        GROUP BY source, product HAVING price_date = MAX(price_date)
        ORDER BY source, product
    """, (cutoff,)).fetchall()
    conn.close()
    prices = {}
    for src, prod, buy, sell, dt, curr, extra_str in rows:
        key = f"{src}:{prod}"
        extra = json.loads(extra_str) if extra_str else {}
        prices[key] = {"source": src, "product": prod, "buy": buy, "sell": sell,
                       "date": dt, "currency": curr or "VND", "extra": extra,
                       "label": _GOLD_LABELS.get(key, f"{src} {prod}")}
    return prices

def _gold_rsi_local(prices: list, period: int = 14):
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[:period]) / period; al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    return 100 - 100 / (1 + ag/al) if al else 100

def _calc_gold_signals_local() -> dict:
    """Tính RSI/BB/MA từ lịch sử SJC trong local SQLite."""
    conn = sqlite3.connect(str(USER_DB))
    _ensure_gold_prices_sqlite(conn)
    rows = conn.execute("""
        SELECT price_date, sell_price FROM gold_prices
        WHERE product='SJC_1L' AND sell_price > 0
        GROUP BY price_date HAVING sell_price = MAX(sell_price)
        ORDER BY price_date ASC LIMIT 300
    """).fetchall()
    conn.close()
    if not rows:
        return {}
    dates = [r[0] for r in rows]; prices = [r[1] for r in rows]
    if len(rows) < 10:
        return {"price": prices[-1], "date": dates[-1], "n_points": len(rows), "signal": "—", "score": 0}
    rsi  = _gold_rsi_local(prices)
    ma20 = sum(prices[-20:]) / min(len(prices), 20)
    ma50 = sum(prices[-50:]) / min(len(prices), 50) if len(prices) >= 20 else None
    cur_p = prices[-1]; prev_p = prices[-2] if len(prices) >= 2 else cur_p
    chg   = (cur_p - prev_p) / prev_p * 100 if prev_p else 0
    win   = prices[-20:] if len(prices) >= 20 else prices
    mean  = sum(win)/len(win)
    std   = (sum((x-mean)**2 for x in win)/len(win))**0.5
    bb_pct = (cur_p - (mean - 2*std)) / (4*std) * 100 if std else 50
    score = 0
    if rsi is not None:
        if rsi < 33: score += 2
        elif rsi < 48: score += 1
        elif rsi > 70: score -= 2
    if bb_pct < 25: score += 1
    elif bb_pct > 75: score -= 1
    if ma50 and cur_p > ma50: score += 1
    if score >= 3:    sig = "MUA 🟢"
    elif score >= 1:  sig = "TÍCH LŨY 🟡"
    elif score <= -2: sig = "THẬN TRỌNG 🔴"
    else:             sig = "HOLD ⚪"
    return {"signal": sig, "score": score, "rsi": round(rsi,1) if rsi else None,
            "bb_pct": round(bb_pct,1), "ma20": round(ma20,0),
            "ma50": round(ma50,0) if ma50 else None,
            "price": cur_p, "chg_pct": round(chg,2),
            "date": dates[-1], "n_points": len(prices)}


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
            prices  = _get_gold_prices_local()
            signals = _calc_gold_signals_local()
            return self._json({"portfolio": _calc_gold_portfolio(uid), "signals": signals, "prices": prices})

        if path.startswith("/api/gold/price_history/"):
            raw_key = urllib.parse.unquote(path[len("/api/gold/price_history/"):])
            if ":" in raw_key:
                src_filter, prod_filter = raw_key.split(":", 1)
            else:
                src_filter, prod_filter = None, raw_key
            conn_gp = sqlite3.connect(str(USER_DB))
            _ensure_gold_prices_sqlite(conn_gp)
            if src_filter:
                rows_gp = conn_gp.execute(
                    "SELECT price_date, COALESCE(sell_price,buy_price) FROM gold_prices WHERE source=? AND product=? ORDER BY price_date",
                    (src_filter, prod_filter)
                ).fetchall()
            else:
                rows_gp = conn_gp.execute(
                    "SELECT price_date, COALESCE(sell_price,buy_price) FROM gold_prices WHERE product=? ORDER BY price_date",
                    (prod_filter,)
                ).fetchall()
            conn_gp.close()
            return self._json({"product": raw_key,
                               "history": [{"date": r[0], "sell": r[1], "buy": r[1]} for r in rows_gp]})

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
                    ft_s = s.get("fund_type","equity")
                    t2 = calc_ensemble_predict([p["nav"] for p in pts], 2, ft_s) if len(pts)>=10 else None
                    sigs[code] = {**s, "has_position": code in held, "t2_prediction": t2}
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
            pts_all = get_nav_series(code, 99999)   # full history cho chart
            ft = get_fund_type(code)
            pts_all = filter_nav_anomalies(pts_all, ft)  # lọc spike trước khi hiện chart
            pts_sig = pts_all[-400:] if len(pts_all) > 400 else pts_all
            s = calc_signal(code, pts_sig)
            nav_hist = [{"date": p["date"], "nav": p["nav"]} for p in pts_all]
            rsi = s["rsi"] or 50; bb = s["bb_pct"] or 50; score = s["score"]

            # Khởi tạo fund_type_str sớm (DB lookup bên dưới sẽ refine nếu có)
            fund_type_str = ft or s.get("fund_type", "equity") or "equity"

            # Fund-type-aware conclusion
            ft_label = {"equity":"Quỹ CP","bond":"Quỹ TP","balanced":"Quỹ CB","money_market":"Tiền tệ"}.get(fund_type_str,"—")
            tech_rel = s.get("tech_reliability","MEDIUM")
            if fund_type_str == "money_market":
                conclusion = "Quỹ tiền tệ (Money Market) — NAV tăng ổn định như gửi tiết kiệm. Phân tích kỹ thuật RSI/MACD không áp dụng. Phù hợp để đậu tiền ngắn hạn, không kỳ vọng tăng mạnh."
            elif fund_type_str == "bond":
                if score >= 2: conclusion = f"Score {score:+d} (quỹ TP) — NAV đang ở vùng hồi phục sau đợt giảm bất thường. Có thể cân nhắc mua vào. Lưu ý: độ tin cậy RSI/BB với quỹ TP thấp hơn quỹ cổ phiếu."
                elif score <= -2: conclusion = f"Score {score:+d} (quỹ TP) — NAV đang ở vùng cao bất thường so với band. Cân nhắc chờ điều chỉnh trước khi mua thêm."
                else: conclusion = f"Score {score:+d} (quỹ TP) — NAV tăng đều đặn, đúng bản chất quỹ trái phiếu. Không cần lo ngại. Tiếp tục DCA theo kế hoạch."
            else:
                if score >= 6: conclusion = f"Score {score:+d} — Tín hiệu MUA MẠNH. Cả RSI, BB và MACD đều chỉ vùng quá bán — đây là cơ hội mua vào tốt theo phân tích kỹ thuật. Tuy nhiên luôn cần kết hợp với phân tích cơ bản."
                elif score >= 3: conclusion = f"Score {score:+d} — Tín hiệu MUA. Nhiều chỉ báo kỹ thuật tích cực. Phù hợp tăng tỷ trọng hoặc mua thêm theo lịch DCA."
                elif score <= -6: conclusion = f"Score {score:+d} — Tín hiệu BÁN MẠNH. RSI và BB ở vùng quá mua cao, rủi ro điều chỉnh lớn. Cân nhắc chốt lời một phần."
                elif score <= -3: conclusion = f"Score {score:+d} — Tín hiệu BÁN. Áp lực bán đang tăng. Nên theo dõi sát, hạn chế mua thêm."
                else: conclusion = f"Score {score:+d} — Trung lập. Chưa có tín hiệu rõ ràng. Tiếp tục DCA theo kế hoạch, không cần hành động đột xuất."

            # T+2 and T+5 ensemble prediction (fund-type-aware)
            navs_raw = [p["nav"] for p in pts_all]
            ft_r = s.get("fund_type", "equity")
            t2 = calc_ensemble_predict(navs_raw, 2, ft_r)
            t5 = calc_ensemble_predict(navs_raw, 5, ft_r)

            # Fund metadata from DB
            nav_conn = _nav_conn()
            fund_row = nav_conn.execute(
                "SELECT name, fund_type FROM funds WHERE code=?", (code,)
            ).fetchone()
            nav_conn.close()
            fund_name = fund_row[0] if fund_row else code
            fund_type_str = (fund_row[1] if fund_row else None) or s.get("fund_type","equity")

            return self._json({
                "code": code, "name": fund_name,
                "fund_type": fund_type_str,
                "signal": s["signal"], "score": score,
                "nav": s["nav"], "nav_date": s["nav_date"],
                "chg_pct": s["chg_pct"],
                "chg7": s.get("chg7"), "chg30": s.get("chg30"),
                "chg90": s.get("chg90"), "chg180": s.get("chg180"), "chg1y": s.get("chg1y"),
                "vol_ann": s.get("vol_ann"),
                "tech_reliability": s.get("tech_reliability","MEDIUM"),
                "rsi": rsi, "bb": bb, "macd": s["macd_hist"],
                "t2_prediction": t2, "t5_prediction": t5,
                "conclusion": conclusion,
                "details": s.get("details",[]),
                "nav_history": nav_hist,
                "nav_history_count": len(nav_hist),
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

        # ── API: admin summary ──
        if path == "/api/admin/summary":
            nav_conn = _nav_conn()
            total_nav = nav_conn.execute("SELECT COUNT(*) FROM nav_history").fetchone()[0]
            today_str = date.today().isoformat()
            today_nav = nav_conn.execute(
                "SELECT COUNT(DISTINCT fund_code) FROM nav_history WHERE date=?", (today_str,)
            ).fetchone()[0]
            total_funds = nav_conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0]
            missing = [r[0] for r in nav_conn.execute(
                "SELECT f.code FROM funds f WHERE f.code NOT IN (SELECT DISTINCT fund_code FROM nav_history WHERE date=?)", (today_str,)
            ).fetchall()]
            nav_conn.close()
            u_conn = _user_conn()
            user_total = u_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            user_pro = u_conn.execute("SELECT COUNT(*) FROM users WHERE tier='pro'").fetchone()[0]
            u_conn.close()
            return self._json({
                "users": {"total": user_total, "pro": user_pro, "free": user_total - user_pro},
                "nav_total_rows": total_nav, "total_funds": total_funds,
                "funds_with_nav_today": today_nav, "funds_missing_today": missing,
                "last_fetch_log": _fetch_log[-5:] if _fetch_log else []
            })

        # ── API: admin users ──
        if path == "/api/admin/users":
            q = qs.get("q", "").lower()
            u_conn = _user_conn()
            rows = u_conn.execute(
                "SELECT telegram_id, name, tier, is_admin, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
            u_conn.close()
            users = []
            for r in rows:
                u = dict(r)
                # trade count
                uc = _user_conn()
                u["trade_count"] = uc.execute(
                    "SELECT COUNT(*) FROM trades WHERE telegram_id=?", (r["telegram_id"],)
                ).fetchone()[0]
                uc.close()
                if not q or q in u["name"].lower() or q in str(u["telegram_id"]):
                    users.append(u)
            return self._json({"users": users, "total": len(users)})

        # ── API: admin nav pending ──
        if path == "/api/admin/nav/pending":
            return self._json({"pending": []})

        # ── API: admin audit ──
        if path == "/api/admin/audit":
            entries = []
            for e in reversed(_fetch_log):
                entries.append({"action": f"fetch_nav:{e['code']}", "detail": f"{e['written']} rows ({e['source']})", "ts": e["ts"]})
            return self._json({"log": entries[:50]})

        # ── API: admin discount ──
        if path == "/api/admin/discount/list":
            return self._json({"codes": []})

        # ── API: nav_history/<code> ──
        if path.startswith("/api/nav_history/"):
            code = path.split("/")[-1].upper()
            qs = self._qs()
            raw_limit = qs.get("limit", ["0"])[0]
            limit = int(raw_limit) if raw_limit else 0
            # limit=0 hoặc không có → trả ALL (dùng số rất lớn)
            pts = get_nav_series(code, limit if limit > 0 else 99999)
            pts = filter_nav_anomalies(pts, get_fund_type(code))
            return self._json({"code": code, "history": pts})

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

        # ── POST: admin settoken ──
        if path == "/api/admin/settoken":
            token = body.get("token", "").strip()
            if not token:
                return self._json({"error": "Token rỗng"}, 400)
            cfg = _load_local_cfg()
            cfg["tcbs_token"] = token
            _save_local_cfg(cfg)
            print(f"[ADMIN] Đã lưu token ({len(token)} chars)", flush=True)
            return self._json({"ok": True, "msg": "✓ Token đã lưu vào local_config.json"})

        # ── POST: admin fetch-nav ──
        if path == "/api/admin/fetch-nav":
            cfg = _load_local_cfg()
            token = cfg.get("tcbs_token", "")
            skip_tcbs = bool(body.get("skip_tcbs"))
            if not token and not skip_tcbs:
                return self._json({"error": "Chưa có TCInvest token. Lưu token trước."}, 400)
            t = threading.Thread(target=_run_fetch_all, args=(token, skip_tcbs), daemon=True)
            t.start()
            return self._json({"ok": True, "msg": "Đang fetch NAV ở background — xem log terminal"})

        # ── POST: admin nav confirm (stub) ──
        if path == "/api/admin/nav/confirm":
            return self._json({"ok": True})

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
    # Safety guard: local_dev_server.py KHÔNG được deploy lên server công khai.
    # Nó không có auth thật — dùng ?user_id bypass cho local dev.
    # Nếu vô tình chạy trên server, set FUND_TRACKER_DEV=1 để override (nhưng biết rủi ro).
    import socket as _socket
    _hostname = _socket.gethostname().lower()
    _is_likely_server = not any(h in _hostname for h in ['localhost','local','macbook','imac','desktop','laptop','harvey','windows','surface','pc'])
    if _is_likely_server and not os.environ.get('FUND_TRACKER_DEV'):
        print("=" * 60)
        print("[SECURITY] local_dev_server.py CHỈ DÙNG CHO LOCAL DEV.")
        print("           Không deploy file này lên server công khai.")
        print("           Trên production: dùng miniapp_server.py thay thế.")
        print("           Nếu chắc chắn muốn chạy, set FUND_TRACKER_DEV=1")
        print("=" * 60)
        sys.exit(1)

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
