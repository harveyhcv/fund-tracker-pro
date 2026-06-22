#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║         QUỸ TRACKER BOT  v1.0  —  Telegram          ║
╠══════════════════════════════════════════════════════╣
║  Lịch gửi:                                          ║
║    • 08:00 T2–T6 → Báo cáo buổi sáng               ║
║    • 17:30 T2–T6 → Báo cáo cuối ngày               ║
║    • Mỗi 60 phút → Kiểm tra tín hiệu,              ║
║      chỉ gửi khi có thay đổi MUA/BÁN               ║
║  Lệnh:  /nav  /signal  /morning  /evening  /help    ║
╚══════════════════════════════════════════════════════╝
"""

import json
import math
import os
import time
import logging
import threading
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    raise SystemExit("❌ Thiếu thư viện. Chạy: pip install requests schedule")

from token_alert_patch import send_token_alert_once, reset_token_alert

try:
    import schedule
except ImportError:
    raise SystemExit("❌ Thiếu thư viện. Chạy: pip install requests schedule")

try:
    import db as _db
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False

try:
    import crypto as _crypto
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

# ═══════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════
_log_file = Path(__file__).parent / "bot.log"
_rotating_handler = RotatingFileHandler(
    _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[_rotating_handler, logging.StreamHandler()],
)
log = logging.getLogger("quy_bot")

# ═══════════════════════════════════════
# PATHS & CONFIG
# ═══════════════════════════════════════
BASE     = Path(__file__).parent                                      # = telegram-bot/
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE)))               # /data in Docker, ./telegram-bot/ locally
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE  = DATA_DIR / "state.json"

# Tập hợp mã quỹ bị 401/403 trong chu kỳ fetch hiện tại.
# Được reset trước mỗi job, kiểm tra sau fetch_all để gửi cảnh báo.
_tcbs_auth_fail_codes: set = set()

# Trạng thái OTP đang chờ xác nhận: {chat_id: {"phone": str, "ts": float}}
# TTL 5 phút — sau đó user phải gửi /otp lại từ đầu.
_otp_pending: dict[str, dict] = {}
_OTP_TTL = 300  # giây


def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError:
            # File bị corrupt (truncated write) — log và trả {} để bot vẫn chạy
            log.error("[load_config] config.json bị lỗi JSON — bỏ qua, dùng config rỗng")
            cfg = {}
    # ENV override — ưu tiên hơn config.json (cho cloud deployment)
    for env_key, cfg_key in [
        ("BOT_TOKEN",         "bot_token"),
        ("ADMIN_TELEGRAM_ID", "admin_telegram_id"),
        ("LOCAL_SERVER_URL",  "local_server_url"),
    ]:
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    return cfg


def _ensure_config_exists():
    """Tạo config.json tối thiểu từ ENV nếu chưa có (first-run trên cloud)."""
    if CONFIG_FILE.exists():
        return
    bot_token = os.environ.get("BOT_TOKEN", "")
    if not bot_token:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {
        "bot_token": bot_token,
        "admin_telegram_id": os.environ.get("ADMIN_TELEGRAM_ID", ""),
        "default_watched_funds": ["TCBF", "SSISCA", "VCBFBCF"],
        "profiles": [],
        "funds": {
            # ── Techcom Capital (TCinvest only) ──
            "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",           "fmarket_id": 22,   "tcbs": True},
            "TCFF":    {"name": "Quỹ Tăng Trưởng Techcombank",          "fmarket_id": None, "tcbs": True},
            "TCGF":    {"name": "Quỹ Tăng Trưởng Toàn Cầu Techcombank","fmarket_id": None, "tcbs": True},
            "TCSME":   {"name": "Quỹ Cổ Phiếu SME Techcombank",         "fmarket_id": None, "tcbs": True},
            "TCEF":    {"name": "Quỹ Cổ Phiếu Techcombank",             "fmarket_id": None, "tcbs": True},
            "TCRES":   {"name": "Quỹ Bất Động Sản Techcombank",         "fmarket_id": None, "tcbs": True},
            "TCFIN":   {"name": "Quỹ Tài Chính Techcombank",            "fmarket_id": None, "tcbs": True},
            # ── VCB Fund ──
            "VCBFTBF": {"name": "Quỹ TPDN Có Bảo Đảm VCB Fund",        "fmarket_id": 31,   "tcbs": True},
            "VCBFBCF": {"name": "Quỹ Trái Phiếu Bền Vững VCB Fund",    "fmarket_id": 32,   "tcbs": True},
            "VCBFFIF": {"name": "Quỹ Thu Nhập Cố Định VCB Fund",        "fmarket_id": None, "tcbs": True},
            "VCBFMGF": {"name": "Quỹ Tăng Trưởng VCB Fund",            "fmarket_id": None, "tcbs": True},
            "VCBFAIF": {"name": "Quỹ Cổ Phiếu VCB Fund",               "fmarket_id": None, "tcbs": True},
            # ── VinaCapital ──
            "VCAMDF":  {"name": "Quỹ Cân Bằng VinaCapital",            "fmarket_id": None, "tcbs": True},
            "VCAMBF":  {"name": "Quỹ Trái Phiếu VinaCapital",          "fmarket_id": None, "tcbs": True},
            # ── SSIAM ──
            "SSISCA":  {"name": "Quỹ Tích Lũy Bền Vững SSI",           "fmarket_id": 11,   "tcbs": True},
            # ── VietFund Management ──
            "VDEF":    {"name": "Quỹ Đầu Tư Tăng Trưởng VietFund",     "fmarket_id": None, "tcbs": True},
            "VEOF":    {"name": "Quỹ Cổ Phiếu Tăng Trưởng VietFund",   "fmarket_id": None, "tcbs": True},
            "VESAF":   {"name": "Quỹ Cổ Phiếu VietFund",               "fmarket_id": None, "tcbs": True},
            "VIBF":    {"name": "Quỹ Trái Phiếu VietFund",             "fmarket_id": None, "tcbs": True},
            "VMEEF":   {"name": "Quỹ Cổ Phiếu VietFund Emerging",      "fmarket_id": None, "tcbs": True},
            "VMPF":    {"name": "Quỹ Cổ Phiếu VietFund Emerging (mã cũ)", "fmarket_id": None, "tcbs": True},
            # ── UOB ──
            "UVDIF":   {"name": "Quỹ Đầu Tư Cổ Phiếu UOB",            "fmarket_id": None, "tcbs": True},
            "UVEEF":   {"name": "Quỹ Cổ Phiếu Tăng Trưởng UOB",       "fmarket_id": None, "tcbs": True},
            # ── Dragon Capital ──
            "DCAF":    {"name": "Quỹ Cân Bằng Dragon Capital",          "fmarket_id": None, "tcbs": True},
            "DCDE":    {"name": "Quỹ Cổ Phiếu Dragon Capital",          "fmarket_id": None, "tcbs": True},
            "DCDS":    {"name": "Quỹ Tăng Trưởng Dragon Capital",       "fmarket_id": 6,    "tcbs": True},
            "DFIX":    {"name": "Quỹ Trái Phiếu Dragon Capital",        "fmarket_id": None, "tcbs": True},
            # ── KIM Vietnam ──
            "KDEF":    {"name": "Quỹ Cổ Phiếu KIM",                    "fmarket_id": None, "tcbs": True},
            # ── Others ──
            "LHCDF":   {"name": "Quỹ Cân Bằng Liên Hiệp",              "fmarket_id": None, "tcbs": True},
            "MAGEF":   {"name": "Quỹ Cổ Phiếu Manulife",               "fmarket_id": 34,   "tcbs": True},
            "PHVSF":   {"name": "Quỹ Cổ Phiếu Phú Hưng",              "fmarket_id": None, "tcbs": True},
            "NTPPF":   {"name": "Quỹ Cổ Phiếu NTP",                    "fmarket_id": None, "tcbs": True},
            "TVPF":    {"name": "Quỹ Cổ Phiếu NTP (mã cũ)",           "fmarket_id": None, "tcbs": True},
            # ── Non-TCinvest (fmarket only) ──
            "MAFPF1":  {"name": "Quỹ Tích Lũy Hưu Trí Manulife",       "fmarket_id": 45},
            "MBBF":    {"name": "Quỹ Trái Phiếu MB Capital",            "fmarket_id": 40},
            "MBVF":    {"name": "Quỹ Cổ Phiếu MB Capital",             "fmarket_id": 35},
            "ESSCF":   {"name": "Quỹ Cổ Phiếu Eastspring VN",          "fmarket_id": 47},
            "ESBF":    {"name": "Quỹ Trái Phiếu Eastspring VN",        "fmarket_id": 46},
            "BVPF":    {"name": "Quỹ Tăng Trưởng Bảo Việt",            "fmarket_id": 20},
            "MIRAEF":  {"name": "Quỹ Cổ Phiếu Mirae Asset VN",         "fmarket_id": 38},
            "VNDAF":   {"name": "Quỹ Cổ Phiếu Năng Động VinaCapital",  "fmarket_id": 1},
            "VNDBF":   {"name": "Quỹ Trái Phiếu VinaCapital",          "fmarket_id": 2},
        },
        "schedule": {
            "morning_report":               os.environ.get("MORNING_TIME", "08:00"),
            "evening_report":               os.environ.get("EVENING_TIME", "17:30"),
            "signal_check_interval_minutes": int(os.environ.get("SIGNAL_INTERVAL", "60")),
        },
    }
    save_config(cfg)
    log.info(f"[BOOTSTRAP] config.json tạo từ ENV (admin={cfg['admin_telegram_id']})")


def save_config(cfg: dict):
    """Atomic write: ghi vào file tạm rồi rename để tránh corrupted JSON khi crash."""
    import tempfile
    tmp = CONFIG_FILE.parent / (CONFIG_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(CONFIG_FILE)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.error("[load_state] state.json bị lỗi JSON — reset state")
    return {}


def save_state(state: dict):
    import tempfile
    tmp = STATE_FILE.parent / (STATE_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(STATE_FILE)


# ═══════════════════════════════════════
# NAV FETCHING  (Fmarket → TCBS fallback)
# ═══════════════════════════════════════
_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://fmarket.vn",
    "Referer": "https://fmarket.vn/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _parse_fmarket_response(data: dict) -> list:
    inner = data.get("data") or {}
    if isinstance(inner, dict):
        navs = inner.get("navHistories") or []
    elif isinstance(inner, list):
        navs = inner
    else:
        navs = data.get("navHistories") or []
    return navs if isinstance(navs, list) else []


def fetch_fmarket(fund_id: int, from_date: str = None) -> list:
    today_ymd = date.today().strftime("%Y%m%d")
    url = "https://api.fmarket.vn/res/product/get-nav-history"
    payload = {
        "isAllData": 1,
        "productId": fund_id,
        "fromDate": None,
        "toDate": today_ymd,
    }
    try:
        r = requests.post(url, json=payload, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        navs = _parse_fmarket_response(r.json())
        pts = []
        for n in navs:
            d = (n.get("navDate") or n.get("date") or "")[:10]
            v = float(n.get("nav") or n.get("navValue") or 0)
            if d and v > 0:
                pts.append({"date": d, "nav": v})
        return sorted(pts, key=lambda x: x["date"])
    except Exception as e:
        log.warning(f"[Fmarket] fund_id={fund_id}: {e}")
        return []


_TCINVEST_URL = "https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={code}&timeline=ALL"
_TCINVEST_HEADERS_BASE = {
    "Content-Type":    "application/json",
    "Accept":          "application/json",
    "Accept-language": "vi",
    "Origin":          "https://tcinvest.tcbs.com.vn",
    "Referer":         "https://tcinvest.tcbs.com.vn/",
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
# Các mã alias: TCinvest đôi khi dùng mã khác với fmarket
_TCINVEST_ALIASES: dict[str, list[str]] = {
    "VMEEF": ["VMPF"],   # VietFund Emerging — TCinvest dùng VMPF
    "NTPPF": ["TVPF"],   # NTP Fund — TCinvest dùng TVPF
    "VMPF":  ["VMEEF"],  # reverse alias
    "TVPF":  ["NTPPF"],  # reverse alias
}


def fetch_tcinvest(code: str, token: str = "", from_date: str = None) -> list:
    """Fetch NAV từ TCinvest API (endpoint đúng được xác nhận bằng Network tab).

    URL:  https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={CODE}&timeline=ALL
    Response: list trực tiếp [{fundCode, navCurrent, matchedDate}, ...]
    """
    hdrs = dict(_TCINVEST_HEADERS_BASE)
    if token:
        hdrs["Authorization"] = f"Bearer {token}"

    codes_to_try = [code] + _TCINVEST_ALIASES.get(code, [])
    for try_code in codes_to_try:
        url = _TCINVEST_URL.format(code=try_code)
        try:
            r = requests.get(url, headers=hdrs, timeout=15)
            if r.status_code in (401, 403):
                log.warning(f"[TCinvest] {try_code} HTTP {r.status_code} — Token hết hạn")
                _tcbs_auth_fail_codes.add(code)
                return []
            if not r.ok:
                log.warning(f"[TCinvest] {try_code} HTTP {r.status_code}")
                continue
            raw = r.json()
            rows = raw if isinstance(raw, list) else (raw.get("data") or [])
            pts = []
            for row in rows:
                d = (row.get("matchedDate") or row.get("navDate") or row.get("date") or "")[:10]
                v_raw = row.get("navCurrent") or row.get("nav") or row.get("navValue") or 0
                try:
                    v = float(v_raw)
                except (TypeError, ValueError):
                    continue
                if d and v > 0:
                    if from_date and d <= from_date:
                        continue
                    pts.append({"date": d, "nav": v})
            if pts:
                pts = sorted(pts, key=lambda x: x["date"])
                if try_code != code:
                    log.info(f"[TCinvest] {code} → alias {try_code}: {len(pts)} pts, last={pts[-1]['date']}")
                else:
                    log.info(f"[TCinvest] {code}: {len(pts)} pts, last={pts[-1]['date']}")
                return pts
        except Exception as e:
            log.warning(f"[TCinvest] {try_code}: {e}")
    return []


def fetch_tcbs(code: str, token: str = "", from_date: str = None) -> list:
    """Wrapper: thử TCinvest API mới trước, fallback về endpoint cũ.

    from_date: "yyyy-mm-dd" — nếu không truyền thì lấy toàn bộ history.
    """
    # Thử TCinvest API (endpoint đúng được confirm 2026-06-21)
    pts = fetch_tcinvest(code, token, from_date)
    if pts:
        return pts

    # Fallback: old TCBS endpoints (cho các quỹ không nằm trong TCinvest)
    today = date.today().isoformat()
    start = from_date or "2023-01-01"
    hdrs = {"Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    urls = [
        f"https://apiextaws.tcbs.com.vn/fund/v1/fund-nav/{code}?startDate={start}&endDate={today}",
        f"https://apiextaws.tcbs.com.vn/fund/v1/nav-history/{code}?page=0&size=600",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=hdrs, timeout=12)
            if r.status_code in (401, 403):
                log.warning(f"[TCBS-old] {code} HTTP {r.status_code} — Token hết hạn")
                _tcbs_auth_fail_codes.add(code)
                break
            if not r.ok:
                continue
            data = r.json()
            navs = data.get("data") or data.get("navHistory") or data.get("list") or []
            pts2 = []
            for n in navs:
                d = (n.get("navDate") or n.get("tradingDate") or n.get("date") or "")[:10]
                v = float(n.get("nav") or n.get("navValue") or n.get("close") or 0)
                if d and v > 0 and (not from_date or d > from_date):
                    pts2.append({"date": d, "nav": v})
            if pts2:
                return sorted(pts2, key=lambda x: x["date"])
        except Exception as e:
            log.warning(f"[TCBS-old] {code} {url}: {e}")
    return []


def get_nav_series(code: str, fund_cfg: dict, config: dict = None) -> list:
    fid = fund_cfg.get("fmarket_id")
    pts = fetch_fmarket(fid) if fid else []
    if not pts and fund_cfg.get("tcbs"):
        tcbs_token = (config or {}).get("tcbs_token", "")
        # Không truyền from_date → full history → đủ điểm cho RSI/MACD/BB
        # fetch_tcbs() sẽ thử TCinvest endpoint mới trước, fallback về old nếu cần
        log.info(f"[Nav] {code} fetch full history (token={'yes' if tcbs_token else 'no'})")
        pts = fetch_tcbs(code, tcbs_token)
    # Fallback cuối: đọc từ master NAV DB (nav_history) khi fetch live thất bại
    # — giúp quỹ TCinvest-only (vd TCFF) vẫn hiển thị khi token hết hạn.
    if not pts and _DB_AVAILABLE and _db.is_available():
        try:
            rows = _db.get_nav_series(code, days=400)  # đủ cho RSI/MACD/BB
            pts = sorted(
                ({"date": r["nav_date"].isoformat(), "nav": float(r["nav"])} for r in rows),
                key=lambda x: x["date"],
            )
            if pts:
                log.info(f"[Nav] {code} fallback DB nav_history: {len(pts)} điểm")
        except Exception as e:
            log.warning(f"[Nav] {code} DB fallback lỗi: {e}")
    return pts


# ═══════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════

def _avg(arr: list) -> float:
    return sum(arr) / len(arr) if arr else 0.0


def _ema(arr: list, period: int) -> float:
    if not arr:
        return 0.0
    k = 2.0 / (period + 1)
    e = arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def calc_rsi(navs: list, period: int = 14) -> Optional[float]:
    if len(navs) < period + 1:
        return None
    window = navs[-(period + 1):]
    gains = losses = 0.0
    for i in range(1, len(window)):
        diff = window[i] - window[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    return round(100 - 100 / (1 + gains / losses), 2)


def calc_ma(navs: list, period: int) -> Optional[float]:
    if len(navs) < period:
        return None
    return _avg(navs[-period:])


def calc_bb(navs: list, period: int = 20) -> Optional[dict]:
    if len(navs) < period:
        return None
    w = navs[-period:]
    m = _avg(w)
    std = math.sqrt(_avg([(x - m) ** 2 for x in w]))
    upper, lower = m + 2 * std, m - 2 * std
    pct = (navs[-1] - lower) / (upper - lower) * 100 if upper != lower else 50.0
    return {"upper": upper, "lower": lower, "mid": m, "pct": round(pct, 1)}


def calc_macd(navs: list, fast=12, slow=26, signal_p=9) -> Optional[dict]:
    if len(navs) < slow + signal_p + 5:
        return None
    macd_line = _ema(navs[-fast - 5:], fast) - _ema(navs[-slow - 5:], slow)
    n = len(navs)
    macd_series = [
        _ema(navs[max(0, i - fast - 4): i + 1], fast)
        - _ema(navs[max(0, i - slow - 4): i + 1], slow)
        for i in range(n - signal_p - 1, n)
    ]
    sig_line = _ema(macd_series, signal_p)
    return {
        "macd": round(macd_line, 4),
        "signal": round(sig_line, 4),
        "hist": round(macd_line - sig_line, 4),
    }


def calc_signal(code: str, pts: list) -> dict:
    if not pts or len(pts) < 60:
        return {
            "signal": "N/A", "score": 0, "rsi": None,
            "bb_pct": None, "macd_hist": None,
            "nav": 0, "nav_date": "", "details": [],
            "nav_prev": 0, "chg_pct": 0,
            "chg7": None, "chg30": None,
        }

    navs = [p["nav"] for p in pts]
    last = navs[-1]
    prev = navs[-2] if len(navs) >= 2 else last
    chg_pct = (last - prev) / prev * 100 if prev else 0
    nav7_ref  = navs[-6]  if len(navs) >= 6  else navs[0]
    nav30_ref = navs[-23] if len(navs) >= 23 else navs[0]
    chg7  = round((last / nav7_ref  - 1) * 100, 2) if nav7_ref  else None
    chg30 = round((last / nav30_ref - 1) * 100, 2) if nav30_ref else None

    score = 0
    details = []

    rsi = calc_rsi(navs)
    if rsi is not None:
        if rsi < 30:
            score += 3; details.append(f"RSI {rsi:.0f} 🟢🟢 quá bán mạnh")
        elif rsi < 40:
            score += 2; details.append(f"RSI {rsi:.0f} 🟢 quá bán")
        elif rsi < 48:
            score += 1; details.append(f"RSI {rsi:.0f} tích cực")
        elif rsi > 75:
            score -= 3; details.append(f"RSI {rsi:.0f} 🔴🔴 quá mua mạnh")
        elif rsi > 65:
            score -= 2; details.append(f"RSI {rsi:.0f} 🔴 quá mua")
        else:
            details.append(f"RSI {rsi:.0f}")

    macd = calc_macd(navs)
    macd_hist = None
    if macd:
        macd_hist = macd["hist"]
        if macd_hist > 0:
            score += 1; details.append("MACD ▲")
        else:
            score -= 1; details.append("MACD ▼")

    bb = calc_bb(navs)
    bb_pct = None
    if bb:
        bb_pct = bb["pct"]
        if bb_pct < 10:
            score += 3; details.append(f"BB {bb_pct:.0f}% 🟢🟢 đáy dải")
        elif bb_pct < 20:
            score += 2; details.append(f"BB {bb_pct:.0f}% 🟢 gần đáy")
        elif bb_pct > 90:
            score -= 3; details.append(f"BB {bb_pct:.0f}% 🔴🔴 đỉnh dải")
        elif bb_pct > 80:
            score -= 2; details.append(f"BB {bb_pct:.0f}% 🔴 gần đỉnh")
        else:
            details.append(f"BB {bb_pct:.0f}%")

    ma20 = calc_ma(navs, 20)
    ma50 = calc_ma(navs, 50)
    if ma20 and ma50:
        if ma20 > ma50:
            score += 1; details.append("MA✅")
        else:
            details.append("MA⬇")

    if len(navs) >= 31:
        mom = (last - navs[-31]) / navs[-31] * 100
        if mom < -6:
            score += 2; details.append(f"Dip {mom:.1f}%")
        elif mom < -3:
            score += 1; details.append(f"Dip {mom:.1f}%")
        elif mom > 6:
            score -= 1; details.append(f"Mom +{mom:.1f}%")

    if score >= 6:
        sig = "MUA MẠNH 🟢🟢"
    elif score >= 3:
        sig = "MUA 🟢"
    elif score <= -6:
        sig = "BÁN MẠNH 🔴🔴"
    elif score <= -3:
        sig = "BÁN 🔴"
    else:
        sig = "HOLD ⚪"

    return {
        "signal": sig, "score": score, "rsi": rsi,
        "bb_pct": bb_pct, "macd_hist": macd_hist,
        "nav": last, "nav_prev": prev, "chg_pct": round(chg_pct, 3),
        "nav_date": pts[-1]["date"],
        "details": details[:4],
        "ma20": ma20, "ma50": ma50,
        "chg7": chg7, "chg30": chg30,
    }


# ═══════════════════════════════════════
# TELEGRAM HELPERS
# ═══════════════════════════════════════

def tg_send(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        if not r.ok:
            log.error(f"[Telegram] {r.status_code} → {r.text[:200]}")
            # Fallback: HTML parse lỗi (vd ký tự < thô) → gửi lại dạng plain-text
            # để message không bị mất im lặng. Strip thẻ HTML + unescape entity.
            if r.status_code == 400:
                import re as _re
                from html import unescape as _unescape
                plain = _unescape(_re.sub(r"<[^>]+>", "", text))
                r2 = requests.post(
                    url,
                    json={"chat_id": chat_id, "text": plain,
                          "disable_web_page_preview": True},
                    timeout=15,
                )
                if r2.ok:
                    log.warning("[Telegram] Đã gửi fallback plain-text")
                    return True
                log.error(f"[Telegram] fallback fail {r2.status_code} → {r2.text[:200]}")
        return r.ok
    except Exception as e:
        log.error(f"[Telegram] send error: {e}")
        return False


def fmt_nav(n: float) -> str:
    return f"{int(n):,}đ".replace(",", ".")


def fmt_date(d: str) -> str:
    p = d.split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else d


def fmt_chg(pct: float) -> str:
    sign = "▲" if pct > 0.02 else "▼" if pct < -0.02 else "─"
    return f"{sign} {'+' if pct >= 0 else ''}{pct:.2f}%"


# ═══════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════
LINE = "─" * 30


def msg_morning(profile: dict, nav_data: dict) -> str:
    now = datetime.now()
    weekday = ["Thứ Hai","Thứ Ba","Thứ Tư","Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ Nhật"][now.weekday()]
    lines = [
        f"🌅 <b>Báo Cáo Sáng — {weekday} {now.strftime('%d/%m/%Y')}</b>",
        f"👤 <b>{profile['name']}</b>",
        LINE,
    ]
    action_funds = []
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{code}</code>  Chưa có dữ liệu")
            continue
        sig = d["signal"]
        emoji = "🟢" if "MUA" in sig else "🔴" if "BÁN" in sig else "⚪"
        rsi_s = f"{d['rsi']:.0f}" if d["rsi"] is not None else "—"
        bb_s  = f"{d['bb_pct']:.0f}%" if d["bb_pct"] is not None else "—"
        lines.append(
            f"{emoji} <code>{code}</code>  <b>{fmt_nav(d['nav'])}</b>  "
            f"<i>{fmt_date(d['nav_date'])}</i>\n"
            f"     {sig}  ·  RSI {rsi_s}  ·  BB {bb_s}"
        )
        if "MUA" in sig or "BÁN" in sig:
            action_funds.append(code)
    lines.append(LINE)
    if action_funds:
        lines.append(f"⚡ <b>Tín hiệu hành động:</b> {', '.join(action_funds)}")
    else:
        lines.append("💤 Không có tín hiệu đặc biệt — duy trì danh mục hiện tại")
    lines.append(f"\n<i>Quỹ Tracker Pro · {now.strftime('%H:%M')}</i>")
    return "\n".join(lines)


def msg_evening(profile: dict, nav_data: dict, morning_nav: dict) -> str:
    now = datetime.now()
    lines = [
        f"🌆 <b>Báo Cáo Chiều — {now.strftime('%d/%m/%Y')}</b>",
        f"👤 <b>{profile['name']}</b>",
        LINE,
    ]
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if not d or d["nav"] == 0:
            continue
        nav_now = d["nav"]
        nav_am  = morning_nav.get(code, {}).get("nav", nav_now)
        chg = (nav_now - nav_am) / nav_am * 100 if nav_am else 0
        lines.append(
            f"{fmt_chg(chg)} <code>{code}</code>  "
            f"<b>{fmt_nav(nav_now)}</b>  "
            f"<i>{'+' if chg>=0 else ''}{chg:.2f}% so sáng</i>"
        )
    lines.append(LINE)
    lines.append(f"<i>Quỹ Tracker Pro · {now.strftime('%H:%M')}</i>")
    return "\n".join(lines)


def msg_signal_alert(profile: dict, code: str, old_sig: str, new_sig: str, d: dict) -> str:
    is_buy = "MUA" in new_sig
    header = "🚨🟢 TÍN HIỆU MUA" if is_buy else "🚨🔴 TÍN HIỆU BÁN"
    lines = [
        f"<b>{header} — <code>{code}</code></b>",
        f"👤 {profile['name']}",
        LINE,
        f"💰 NAV: <b>{fmt_nav(d['nav'])}</b>  <i>{fmt_date(d['nav_date'])}</i>",
        f"📶 Tín hiệu mới: <b>{new_sig}</b>",
        f"↩️ Trước: {old_sig}",
    ]
    if d.get("rsi") is not None:
        lines.append(f"📊 RSI: {d['rsi']:.1f}")
    if d.get("bb_pct") is not None:
        lines.append(f"📏 BB%: {d['bb_pct']:.1f}%")
    if d.get("details"):
        lines.append(f"🔍 {' · '.join(d['details'][:3])}")
    lines.append(LINE)
    note = (
        "💡 Cân nhắc tích lũy thêm (DCA) nếu phù hợp kế hoạch của bạn."
        if is_buy else
        "💡 Cân nhắc giảm tỷ trọng nếu cần bảo toàn vốn."
    )
    lines.append(note)
    lines.append("<i>⚠️ Không phải khuyến nghị đầu tư — hãy tự quyết định.</i>")
    return "\n".join(lines)


def msg_nav_query(profile: dict, nav_data: dict) -> str:
    now = datetime.now()
    lines = [
        f"📈 <b>NAV — {now.strftime('%d/%m/%Y %H:%M')}</b>",
        f"👤 <b>{profile['name']}</b>",
        LINE,
    ]
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if d and d["nav"]:
            emoji = "🟢" if "MUA" in d["signal"] else "🔴" if "BÁN" in d["signal"] else "⚪"
            chg = fmt_chg(d.get("chg_pct", 0))
            lines.append(
                f"{emoji} <code>{code}</code>  <b>{fmt_nav(d['nav'])}</b>  "
                f"{chg}  →  {d['signal']}"
            )
        else:
            lines.append(f"⚠️ <code>{code}</code>  Không có dữ liệu")
    return "\n".join(lines)


def msg_signal_summary(profile: dict, nav_data: dict) -> str:
    now = datetime.now()
    lines = [
        f"📊 <b>Tín Hiệu Kỹ Thuật — {now.strftime('%d/%m/%Y %H:%M')}</b>",
        f"👤 <b>{profile['name']}</b>",
        LINE,
    ]
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{code}</code>  N/A")
            continue
        rsi_s = f"{d['rsi']:.0f}" if d["rsi"] is not None else "—"
        bb_s  = f"{d['bb_pct']:.0f}%" if d["bb_pct"] is not None else "—"
        score_s = f"{'+' if d['score']>=0 else ''}{d['score']}"
        lines.append(
            f"• <code>{code}</code>  {d['signal']}\n"
            f"  RSI {rsi_s} · BB {bb_s} · Score {score_s}"
        )
    return "\n".join(lines)


def msg_portfolio(profile: dict, nav_data: dict) -> str:
    """Hiển thị danh mục đầu tư.

    Nếu profile có field 'portfolio' (list of {code, units, avg_cost})
    → hiển thị P&L đầy đủ (giá vốn, giá trị, lãi/lỗ, tổng).
    Nếu không có portfolio data → fallback về view 7/30 ngày.
    """
    now = datetime.now()
    portfolio_holdings = {
        h["code"]: h
        for h in profile.get("portfolio", [])
        if h.get("code") and h.get("units", 0) > 0 and h.get("avg_cost", 0) > 0
    }

    if portfolio_holdings:
        return _msg_portfolio_detail(profile, nav_data, portfolio_holdings, now)

    # Fallback: không có portfolio data → hiện 7/30 day change
    lines = [
        f"📊 <b>DANH MỤC — {profile['name']}</b>",
        f"📅 {now.strftime('%d/%m/%Y %H:%M')}",
        LINE,
    ]
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{code}</code>  N/A")
            continue
        emoji = "🟢" if "MUA" in d["signal"] else "🔴" if "BÁN" in d["signal"] else "⚪"
        chg7_s  = (f"{'+' if d['chg7']>=0 else ''}{d['chg7']:.1f}%" ) if d.get("chg7")  is not None else "—"
        chg30_s = (f"{'+' if d['chg30']>=0 else ''}{d['chg30']:.1f}%") if d.get("chg30") is not None else "—"
        lines.append(
            f"{emoji} <code>{code}</code>  {fmt_nav(d['nav'])}\n"
            f"   7 ngày: {chg7_s} · 30 ngày: {chg30_s}\n"
            f"   {d['signal']}"
        )
    lines.append(LINE)
    lines.append("<i>Bot không cung cấp khuyến nghị đầu tư.</i>")
    return "\n".join(lines)


def _msg_portfolio_detail(profile: dict, nav_data: dict,
                          holdings: dict, now: datetime) -> str:
    """Hiển thị P&L đầy đủ khi có portfolio holdings."""
    lines = [
        f"📊 <b>DANH MỤC — {profile['name']}</b>",
        f"📅 {now.strftime('%d/%m/%Y %H:%M')}",
        LINE,
    ]
    total_value   = 0.0
    total_cost    = 0.0

    for code, holding in holdings.items():
        units     = float(holding["units"])
        avg_cost  = float(holding["avg_cost"])
        d         = nav_data.get(code)

        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{code}</code>  N/A (chưa có dữ liệu NAV)")
            continue

        nav_now   = d["nav"]
        cost_val  = units * avg_cost
        cur_val   = units * nav_now
        pnl       = cur_val - cost_val
        pnl_pct   = (nav_now - avg_cost) / avg_cost * 100
        emoji     = "🟢" if "MUA" in d["signal"] else "🔴" if "BÁN" in d["signal"] else "⚪"
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_sign  = "+" if pnl >= 0 else ""
        pct_sign  = "+" if pnl_pct >= 0 else ""

        lines.append(
            f"{emoji} <b><code>{code}</code></b>  {units:,.3f} CCQ\n"
            f"   Giá vốn: {int(avg_cost):,}đ → Hiện: {int(nav_now):,}đ "
            f"({pct_sign}{pnl_pct:.2f}%)  {d['signal']}\n"
            f"   {pnl_emoji} Giá trị: {int(cur_val):,}đ  |  "
            f"{'Lãi' if pnl >= 0 else 'Lỗ'}: <b>{pnl_sign}{int(pnl):,}đ</b>"
        )

        total_value += cur_val
        total_cost  += cost_val

    total_pnl     = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    pnl_sign      = "+" if total_pnl >= 0 else ""
    pct_sign      = "+" if total_pnl_pct >= 0 else ""

    lines.append(LINE)
    lines.append(
        f"💰 <b>Tổng: {int(total_value):,}đ</b>  |  "
        f"{'Lãi' if total_pnl >= 0 else 'Lỗ'}: "
        f"<b>{pnl_sign}{int(total_pnl):,}đ ({pct_sign}{total_pnl_pct:.2f}%)</b>"
    )
    lines.append("<i>Bot không cung cấp khuyến nghị đầu tư.</i>")
    return "\n".join(lines)


def msg_explain(profile: dict, nav_data: dict, target_code: str = None) -> str:
    now = datetime.now()
    title = f"🔍 <b>PHÂN TÍCH KỸ THUẬT{' — ' + target_code if target_code else ''}</b>"
    lines = [title, f"📅 {now.strftime('%d/%m/%Y %H:%M')}", LINE]
    items = (
        {target_code: nav_data[target_code]}
        if target_code and target_code in nav_data
        else {c: nav_data.get(c) for c in profile.get("watched_funds", [])}
    )
    for code, d in items.items():
        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{code}</code>  Không đủ dữ liệu")
            continue
        rsi_val = d.get("rsi")
        bb_val  = d.get("bb_pct")
        score   = d.get("score", 0)
        sig     = d.get("signal", "—")
        rsi_s   = f"{rsi_val:.1f}" if rsi_val is not None else "—"
        bb_s    = f"{bb_val:.0f}%" if bb_val  is not None else "—"
        score_s = f"{'+' if score >= 0 else ''}{score}"
        if rsi_val is not None:
            rsi_note = "Quá bán 🟢🟢" if rsi_val < 30 else ("Quá bán nhẹ 🟢" if rsi_val < 40 else ("Quá mua 🔴🔴" if rsi_val > 75 else ("Quá mua nhẹ 🔴" if rsi_val > 65 else "Trung tính ⚪")))
        else:
            rsi_note = "—"
        bb_note = "Gần đáy 🟢" if bb_val is not None and bb_val < 20 else ("Gần đỉnh 🔴" if bb_val is not None and bb_val > 80 else "Vùng giữa ⚪")
        ma_note = "MA20 &gt; MA50 ↑" if d.get("ma20") and d.get("ma50") and d["ma20"] > d["ma50"] else "MA20 &lt; MA50 ↓"
        lines.append(
            f"<b>{code}</b>  {sig}\n"
            f"  RSI(14): {rsi_s} → {rsi_note}\n"
            f"  Bollinger: {bb_s} (0%=đáy, 100%=đỉnh) → {bb_note}\n"
            f"  {ma_note}\n"
            f"  Tổng điểm: <b>{score_s}</b>"
        )
    lines.append(LINE)
    lines.append("📌 ≥+6: MUA MẠNH · ≥+3: MUA · ≤-3: BÁN · ≤-6: BÁN MẠNH")
    return "\n".join(lines)


# ═══════════════════════════════════════
# CORE DATA FETCH
# ═══════════════════════════════════════

# HIST cutoff cho từng quỹ — khớp với HIST_CUTOFF trong server.py
_HIST_CUTOFF = {
    "TCBF":    "2026-04-02",
    "VCBFTBF": "2026-04-02",
    "SSISCA":  "2026-04-02",
    "VCBFBCF": "2026-04-02",
    "TCFF":    "2026-04-02",
}


def _push_nav_to_server(nav_data: dict, config: dict):
    """Push NAV delta lên server.py sau mỗi lần fetch.

    nav_data: dict {code: {nav, nav_date, signal, ...}} — kết quả từ fetch_all()
    Chỉ gửi điểm date > _HIST_CUTOFF — server sẽ lưu vào nav_data.json.
    Không lỗi nếu server không chạy (dashboard offline là bình thường).
    """
    server_url = config.get("local_server_url", "http://localhost:8080")
    cached_nav = {}
    for code, info in nav_data.items():
        nav_date = info.get("nav_date", "")
        nav_val  = info.get("nav", 0)
        cutoff   = _HIST_CUTOFF.get(code, "")
        if nav_date and nav_val > 0 and (not cutoff or nav_date > cutoff):
            cached_nav[code] = [{"date": nav_date, "nav": nav_val}]
    if not cached_nav:
        log.info("[push-nav] Không có điểm mới hơn HIST cutoff → skip")
        return
    payload = {
        "cachedNav":   cached_nav,
        "lastRefresh": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "histCutoff":  _HIST_CUTOFF,
    }
    try:
        r = requests.post(
            f"{server_url}/save-nav",
            json=payload,
            timeout=5,
        )
        if r.ok:
            log.info(f"[push-nav] ✓ Đã cập nhật nav_data.json ({list(cached_nav.keys())})")
        else:
            log.warning(f"[push-nav] Server trả về {r.status_code}")
    except requests.exceptions.ConnectionError:
        log.debug("[push-nav] Server không chạy (offline) — bỏ qua")
    except Exception as e:
        log.warning(f"[push-nav] Lỗi: {e}")


def _handle_tcbs_auth_error(config: dict, failed_codes: set):
    """Gửi cảnh báo Telegram khi TCBS token hết hạn (401/403).

    Được gọi từ job_morning / job_check_signals khi _tcbs_auth_fail_codes
    không rỗng sau khi fetch_all hoàn thành.

    Không raise exception — fail gracefully nếu bot token chưa cấu hình.
    """
    bot_token = config.get("bot_token", "")
    if not bot_token or bot_token.startswith("NHAP"):
        log.warning("[TCBS-AUTH] Bot token chưa cấu hình — không gửi cảnh báo được")
        return
    codes_str = ", ".join(sorted(failed_codes))
    msg = (
        f"🔐 <b>TCBS Token hết hạn</b>\n"
        f"Quỹ chưa cập nhật NAV: <code>{codes_str}</code>\n\n"
        f"👉 Làm mới ngay trong Telegram:\n"
        f"<code>/otp</code>  — gửi OTP về SĐT\n"
        f"<code>/otp 123456</code>  — xác nhận OTP\n\n"
        f"<i>Chưa có SĐT? Gõ /otp setup 09xx để thiết lập.</i>"
    )
    sent = 0
    for profile in config.get("profiles", []):
        tg = str(profile.get("telegram_id", ""))
        if tg.lstrip("-").isdigit():
            ok = tg_send(bot_token, tg, msg)
            if ok:
                sent += 1
    log.warning(f"[TCBS-AUTH] Token hết hạn cho {codes_str} — đã cảnh báo {sent} profile(s)")


def check_jwt_freshness(config: dict) -> Optional[int]:
    """Đọc TCBS JWT từ config, trả về số giây còn lại trước khi expire.

    Trả về None nếu không có token hoặc token không phải JWT hợp lệ.
    Gửi cảnh báo Telegram nếu còn < 3600 giây (1 giờ).
    """
    import base64

    token = config.get("tcbs_token", "")
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        # Thêm padding nếu thiếu
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded).decode("utf-8"))
        exp = payload.get("exp", 0)
        if not exp:
            return None
        remaining = int(exp - time.time())
        return remaining
    except Exception as e:
        log.debug(f"[JWT-CHECK] Không parse được JWT payload: {e}")
        return None


# ── TCBS OTP endpoints (theo thứ tự ưu tiên) ──────────────────────────────────
_TCBS_OTP_URLS    = [
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/authentication",
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/otp-request",
]
_TCBS_VERIFY_URLS = [
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/authentication/otp",
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/otp-verify",
]


def _tcbs_request_otp(phone: str) -> tuple[bool, str]:
    """Gửi yêu cầu OTP về SĐT. Returns (success, session_id_or_error)."""
    import urllib.request as _req
    import urllib.error  as _err
    payload = json.dumps({"mobile": phone}).encode()
    headers = {"Content-Type": "application/json",
               "User-Agent": "Mozilla/5.0"}
    for url in _TCBS_OTP_URLS:
        try:
            r = _req.urlopen(
                _req.Request(url, data=payload, headers=headers, method="POST"),
                timeout=10
            )
            resp = json.loads(r.read())
            sid  = (resp.get("data") or {}).get("sessionId", "")
            return True, sid
        except _err.HTTPError as e:
            if e.code == 400:
                return False, f"Số điện thoại không hợp lệ"
            continue
        except Exception:
            continue
    return False, "TCBS API không phản hồi"


def _tcbs_verify_otp(phone: str, otp: str, session_id: str = "") -> tuple[bool, str]:
    """Xác nhận OTP. Returns (success, token_or_error)."""
    import urllib.request as _req
    import urllib.error  as _err
    payload_dict = {"mobile": phone, "otp": otp}
    if session_id:
        payload_dict["sessionId"] = session_id
    payload = json.dumps(payload_dict).encode()
    headers = {"Content-Type": "application/json",
               "User-Agent": "Mozilla/5.0"}
    for url in _TCBS_VERIFY_URLS:
        try:
            r = _req.urlopen(
                _req.Request(url, data=payload, headers=headers, method="POST"),
                timeout=10
            )
            resp = json.loads(r.read())
            token = (
                (resp.get("data") or {}).get("access_token")
                or resp.get("access_token")
                or (resp.get("data") or {}).get("token")
                or ""
            )
            if token:
                return True, token
            return False, f"API không trả về token: {resp}"
        except _err.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
            if e.code == 400:
                return False, f"OTP sai hoặc hết hạn"
            continue
        except Exception:
            continue
    return False, "TCBS API không phản hồi"


def _cmd_otp(token: str, chat_id: str, parts: list, profile: dict) -> None:
    """
    /otp                 → Gửi OTP về SĐT đã đăng ký
    /otp XXXXXX          → Xác nhận OTP, lưu JWT mới vào config
    /otp setup 0901...   → Đổi SĐT dùng cho TCBS auth
    """
    phone_in_profile = (profile or {}).get("phone", "").strip() if profile else ""

    # /otp setup 0901234567
    if len(parts) >= 3 and parts[1].lower() == "setup":
        new_phone = parts[2].strip()
        if not new_phone.lstrip("+").isdigit() or len(new_phone) < 9:
            tg_send(token, chat_id, "❌ Số điện thoại không hợp lệ.\nVí dụ: <code>/otp setup 0901234567</code>")
            return
        cfg = load_config()
        for p in cfg.get("profiles", []):
            if str(p.get("telegram_id", "")) == chat_id:
                p["phone"] = new_phone
                break
        save_config(cfg)
        tg_send(token, chat_id, f"✅ Đã lưu SĐT <b>{new_phone}</b> cho tài khoản TCBS.\n"
                                f"Gõ <code>/otp</code> để nhận OTP.")
        return

    # /otp XXXXXX — xác nhận OTP
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) >= 4:
        otp_code = parts[1]
        pending  = _otp_pending.get(chat_id)
        if not pending:
            tg_send(token, chat_id,
                    "⚠️ Không có phiên OTP nào đang chờ.\n"
                    "Gõ <code>/otp</code> để gửi OTP mới.")
            return
        if time.time() - pending["ts"] > _OTP_TTL:
            _otp_pending.pop(chat_id, None)
            tg_send(token, chat_id,
                    "⏱ Phiên OTP đã hết hạn (5 phút).\n"
                    "Gõ <code>/otp</code> để gửi lại.")
            return

        tg_send(token, chat_id, "⏳ Đang xác nhận OTP...")
        ok, result = _tcbs_verify_otp(
            pending["phone"], otp_code, pending.get("session_id", "")
        )
        _otp_pending.pop(chat_id, None)

        if not ok:
            tg_send(token, chat_id, f"❌ {result}\nGõ <code>/otp</code> để thử lại.")
            return

        # Lưu token mới vào config
        cfg = load_config()
        cfg["tcbs_token"] = result
        save_config(cfg)

        # Decode thời hạn từ JWT payload
        try:
            import base64 as _b64
            pad     = result.split(".")[1]
            pad    += "=" * (-len(pad) % 4)
            payload = json.loads(_b64.b64decode(pad).decode())
            exp_ts  = payload.get("exp", 0)
            exp_dt  = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y %H:%M") if exp_ts else "?"
            expires = f"\nHết hạn lúc <b>{exp_dt}</b>"
        except Exception:
            expires = ""

        tg_send(token, chat_id,
                f"✅ <b>TCBS Token đã được cập nhật!</b>{expires}\n\n"
                f"Bot sẽ tự nhắc khi token sắp hết hạn.")
        log.info(f"[OTP] Token mới đã lưu cho chat_id={chat_id}")
        return

    # /otp — gửi OTP
    phone = phone_in_profile
    if not phone:
        tg_send(token, chat_id,
                "📱 Chưa có SĐT TCBS.\n"
                "Thiết lập bằng:\n<code>/otp setup 0901234567</code>")
        return

    tg_send(token, chat_id, f"📱 Đang gửi OTP về <b>{phone[:4]}****{phone[-3:]}</b>...")
    ok, sid = _tcbs_request_otp(phone)
    if not ok:
        tg_send(token, chat_id, f"❌ {sid}")
        return

    _otp_pending[chat_id] = {"phone": phone, "session_id": sid, "ts": time.time()}
    tg_send(token, chat_id,
            f"📨 OTP đã gửi về <b>{phone[:4]}****{phone[-3:]}</b>\n\n"
            f"Nhập mã 6 số:\n<code>/otp 123456</code>\n\n"
            f"<i>(Hết hạn sau 5 phút)</i>")


def job_check_jwt():
    """Kiểm tra TCBS JWT token còn hạn không — chạy mỗi 30 phút.

    Gửi cảnh báo Telegram khi token sắp hết hạn (< 1 giờ).
    Dùng send_token_alert_once để tránh spam — chỉ gửi 1 lần mỗi chu kỳ hết hạn.
    """
    cfg = load_config()
    remaining = check_jwt_freshness(cfg)
    if remaining is None:
        return  # Không có token hoặc không phải JWT — bỏ qua

    bot_token = cfg.get("bot_token", "")
    if not bot_token or bot_token.startswith("NHAP"):
        return

    if remaining >= 7200:
        # Token còn hạn dài — reset flag phòng trường hợp user vừa refresh token
        reset_token_alert()
        hours = remaining // 3600
        log.debug(f"[JWT-CHECK] TCBS token còn hạn: {hours} giờ.")
        return

    if remaining < 0:
        log.warning("[JWT-CHECK] TCBS token đã hết hạn!")
        mins = abs(remaining) // 60
        msg = (
            f"🔐 <b>TCBS Token đã hết hạn!</b>\n"
            f"Đã hết hạn <b>{mins} phút</b> trước.\n\n"
            f"👉 Làm mới ngay:\n"
            f"<code>/otp</code>  →  gửi OTP về SĐT\n"
            f"<code>/otp 123456</code>  →  xác nhận"
        )
    else:
        mins = remaining // 60
        log.warning(f"[JWT-CHECK] TCBS token sắp hết hạn! Còn {mins} phút.")
        msg = (
            f"⚠️ <b>TCBS Token sắp hết hạn!</b>\n"
            f"Còn <b>{mins} phút</b>.\n\n"
            f"👉 Gia hạn ngay:\n"
            f"<code>/otp</code>  →  gửi OTP về SĐT\n"
            f"<code>/otp 123456</code>  →  xác nhận"
        )

    def _send_to_all(text: str):
        sent = 0
        for profile in cfg.get("profiles", []):
            tg = str(profile.get("telegram_id", ""))
            if tg.lstrip("-").isdigit():
                ok = tg_send(bot_token, tg, text)
                if ok:
                    sent += 1
        log.info(f"[JWT-CHECK] Đã gửi cảnh báo JWT tới {sent} profile(s).")

    send_token_alert_once(send_fn=_send_to_all, message=msg)


def fetch_all(config: dict, codes: set) -> dict:
    result = {}
    funds_cfg = config.get("funds", {})
    for code in sorted(codes):
        fund_cfg = funds_cfg.get(code, {})
        pts = get_nav_series(code, fund_cfg, config)
        if pts:
            result[code] = calc_signal(code, pts)
            sig = result[code]["signal"]
            log.info(f"  {code:12s}  NAV={result[code]['nav']:>10,.0f}  {sig}")
        else:
            log.warning(f"  {code:12s}  ⚠ No data")
    return result


def all_watched_codes(config: dict) -> set:
    codes = set()
    for p in config.get("profiles", []):
        codes.update(p.get("watched_funds", []))
    return codes


# ═══════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════

def job_morning():
    log.info("══ JOB: Morning Report ══")
    _tcbs_auth_fail_codes.clear()          # Reset trước mỗi chu kỳ fetch
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        log.error("Bot token chưa được cấu hình trong config.json")
        return
    codes    = all_watched_codes(config)
    nav_data = fetch_all(config, codes)
    # Cảnh báo ngay nếu TCBS token hết hạn trong lúc fetch
    if _tcbs_auth_fail_codes:
        _handle_tcbs_auth_error(config, _tcbs_auth_fail_codes.copy())
    state = load_state()
    state["morning_nav"]  = {k: {"nav": v["nav"], "date": v["nav_date"]} for k, v in nav_data.items()}
    state["last_morning"] = datetime.now().isoformat()
    save_state(state)
    for profile in config.get("profiles", []):
        tg = profile.get("telegram_id", "")
        if not tg:
            log.warning(f"Profile '{profile['name']}' chưa có telegram_id")
            continue
        ok = tg_send(token, tg, msg_morning(profile, nav_data))
        log.info(f"  → {profile['name']} ({tg}): {'OK' if ok else 'FAILED'}")
    # Đẩy NAV mới nhất lên dashboard server (bất đồng bộ, không block)
    try:
        _push_nav_to_server(nav_data, config)
    except Exception as e:
        log.warning(f"[job-morning] push-nav failed: {e}")


def job_evening():
    log.info("══ JOB: Evening Report ══")
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        return
    codes    = all_watched_codes(config)
    nav_data = fetch_all(config, codes)
    state = load_state()
    morning_nav = state.get("morning_nav", {})
    state["last_evening"] = datetime.now().isoformat()
    save_state(state)
    for profile in config.get("profiles", []):
        tg = profile.get("telegram_id", "")
        if not tg:
            continue
        ok = tg_send(token, tg, msg_evening(profile, nav_data, morning_nav))
        log.info(f"  → {profile['name']} ({tg}): {'OK' if ok else 'FAILED'}")


def job_check_signals():
    log.info("══ JOB: Signal Check ══")
    _tcbs_auth_fail_codes.clear()          # Reset trước mỗi chu kỳ fetch
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        log.error("Bot token chưa được cấu hình")
        return
    codes    = all_watched_codes(config)
    nav_data = fetch_all(config, codes)
    # Chỉ cảnh báo TCBS auth 1 lần/ngày — tránh spam; morning job đã gửi rồi,
    # check_signals bổ sung phòng khi token hết hạn giữa ngày
    if _tcbs_auth_fail_codes:
        _handle_tcbs_auth_error(config, _tcbs_auth_fail_codes.copy())
    state        = load_state()
    prev_signals = state.get("signals", {})
    new_signals  = {k: v["signal"] for k, v in nav_data.items()}
    for code, new_sig in new_signals.items():
        old_sig = prev_signals.get(code, "")
        if old_sig == new_sig:
            continue
        new_is_action = "MUA" in new_sig or "BÁN" in new_sig
        old_is_action = "MUA" in old_sig or "BÁN" in old_sig
        if not new_is_action and not old_is_action:
            log.info(f"  {code}: {old_sig!r} → {new_sig!r} (minor, skip)")
            prev_signals[code] = new_sig
            continue
        log.info(f"  🔔 SIGNAL CHANGE: {code}  {old_sig!r} → {new_sig!r}")
        for profile in config.get("profiles", []):
            if code not in profile.get("watched_funds", []):
                continue
            tg = profile.get("telegram_id", "")
            if not tg:
                continue
            ok = tg_send(token, tg, msg_signal_alert(profile, code, old_sig or "N/A", new_sig, nav_data.get(code, {})))
            log.info(f"    → {profile['name']} ({tg}): {'OK' if ok else 'FAILED'}")
    state["signals"]           = new_signals
    state["last_signal_check"] = datetime.now().isoformat()
    save_state(state)

    # Persist to PostgreSQL (no-op if DB unavailable)
    if _DB_AVAILABLE and _db.is_available():
        today = date.today()
        for code, d in nav_data.items():
            if d.get("nav") and d.get("nav_date"):
                try:
                    nav_date = date.fromisoformat(d["nav_date"])
                    _db.upsert_nav(code, nav_date, d["nav"])
                except Exception as e:
                    log.debug("upsert_nav %s: %s", code, e)
            sig = d.get("signal", "")
            if "MUA" in sig or "BÁN" in sig:
                strength_map = {
                    "MUA MẠNH": "strong_buy", "MUA": "buy",
                    "BÁN MẠNH": "strong_reduce", "BÁN": "reduce",
                }
                strength = next((v for k, v in strength_map.items() if k in sig), "hold")
                fund_cfg = next(
                    (f for f in config.get("funds", {}).values() if f.get("code") == code),
                    {}
                )
                settle = fund_cfg.get("settlement", "T2")
                try:
                    _db.save_signal(
                        fund_code=code,
                        signal_date=today,
                        strength=strength,
                        score=d.get("score", 0),
                        nav_at_signal=d.get("nav", 0),
                        indicators={
                            "rsi": d.get("rsi"),
                            "bb_pct": d.get("bb_pct"),
                            "macd_hist": d.get("macd_hist"),
                        },
                        settlement_rule=settle,
                    )
                except Exception as e:
                    log.debug("save_signal %s: %s", code, e)


def job_backfill_settlement():
    """Điền nav_at_settlement cho buy_signals đã qua est_exec_date.

    Chạy hàng ngày lúc 09:00 (sau job_morning). Tra cứu từ nav_history;
    nếu chưa có dữ liệu (NAV chưa được fetch vào DB) thì bỏ qua — ngày hôm sau tự điền.
    """
    log.info("══ JOB: Backfill Settlement NAV ══")
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[backfill] DB unavailable — skip")
        return
    today   = date.today()
    pending = _db.get_pending_backfill(today)
    if not pending:
        log.info("[backfill] Không có signal nào cần backfill")
        return
    filled  = 0
    skipped = 0
    for row in pending:
        fund_code    = row["fund_code"]
        signal_date  = row["signal_date"]
        est_exec     = row["est_exec_date"]
        nav = _db.get_nav_on_or_after(fund_code, est_exec)
        if nav is not None:
            try:
                _db.backfill_settlement_nav(fund_code, signal_date, nav)
                log.info("[backfill] ✓ %s signal=%s nav_settle=%.4f", fund_code, signal_date, nav)
                filled += 1
            except Exception as e:
                log.warning("[backfill] %s %s: %s", fund_code, signal_date, e)
        else:
            log.debug("[backfill] %s %s: NAV chưa có cho %s — bỏ qua", fund_code, signal_date, est_exec)
            skipped += 1
    log.info("[backfill] ✅ Filled=%d  Skipped=%d/%d", filled, skipped, len(pending))


def job_watchdog_ping():
    """Gửi ping hàng ngày lúc 00:01 — nếu không nhận được là bot đã chết."""
    cfg = load_config()
    tok = cfg.get("bot_token", "")
    if not tok or tok.startswith("NHAP"):
        return
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    log.info("══ JOB: Watchdog Ping ══")
    for profile in cfg.get("profiles", []):
        tg = profile.get("telegram_id", "")
        if not tg or not str(tg).lstrip("-").isdigit():
            continue
        ok = tg_send(
            tok, tg,
            f"🤖 <b>Bot alive</b> — {now}\n"
            f"Đang theo dõi: {', '.join(profile.get('watched_funds', []))}",
        )
        log.info(f"  → {profile['name']} ({tg}): {'OK' if ok else 'FAILED'}")


# ═══════════════════════════════════════
# NAV CHANGE ALERT JOB
# ═══════════════════════════════════════

def job_nav_change_alert():
    """Gửi thông báo khi có NAV mới được công bố (nav_date thay đổi so với lần trước).
    Chạy theo interval signal_check. Chỉ gửi khi có thay đổi thực sự — không spam.
    """
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        return
    codes    = all_watched_codes(config)
    if not codes:
        return
    nav_data = fetch_all(config, codes)
    state      = load_state()
    last_dates = state.get("last_nav_dates", {})

    newly_published = {c: d for c, d in nav_data.items() if d and d.get("nav_date") and d["nav_date"] != last_dates.get(c, "")}
    if not newly_published:
        log.debug("[nav-alert] Không có NAV mới")
        return

    log.info(f"[nav-alert] NAV mới: {sorted(newly_published.keys())}")
    for profile in config.get("profiles", []):
        tg = str(profile.get("telegram_id", ""))
        if not tg.lstrip("-").isdigit():
            continue
        watched   = set(profile.get("watched_funds", []))
        relevant  = {c: d for c, d in newly_published.items() if c in watched}
        if not relevant:
            continue
        lines = [
            f"📢 <b>NAV Mới — {date.today().strftime('%d/%m/%Y')}</b>",
            LINE,
        ]
        for code_na, d_na in sorted(relevant.items()):
            sig_na  = d_na.get("signal", "—")
            chg_na  = d_na.get("chg_pct", 0) or 0
            emoji   = "🟢" if "MUA" in sig_na else "🔴" if "BÁN" in sig_na else "⚪"
            chg_s   = f"{'+' if chg_na >= 0 else ''}{chg_na:.2f}%"
            lines.append(
                f"{emoji} <code>{code_na}</code>  <b>{fmt_nav(d_na['nav'])}</b>  "
                f"<i>{chg_s}</i>  {sig_na}"
            )
        lines += [LINE, "<i>Quỹ Tracker Pro · Tự động</i>"]
        tg_send(token, tg, "\n".join(lines))

    state["last_nav_dates"] = {**last_dates, **{c: d.get("nav_date", "") for c, d in nav_data.items() if d}}
    save_state(state)


def job_dca_reminder():
    """Gửi gợi ý DCA vào ngày 1 mỗi tháng cho các profile đã setup monthly_dca."""
    if date.today().day != 1:
        return
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        return
    log.info("══ JOB: DCA Monthly Reminder ══")
    for profile in config.get("profiles", []):
        budget = profile.get("monthly_dca", 0)
        if not budget:
            continue
        tg = str(profile.get("telegram_id", ""))
        if not tg.lstrip("-").isdigit():
            continue
        codes    = set(profile.get("watched_funds", []))
        nav_data = fetch_all(config, codes)
        tg_send(token, tg, msg_dca_suggest(profile, nav_data, float(budget)))
        log.info(f"  → DCA reminder: {profile['name']} ngân sách {int(budget):,}đ")


# ═══════════════════════════════════════
# MASTER NAV HARVEST JOB
# ═══════════════════════════════════════

def job_harvest_nav():
    """
    Chạy daily lúc 18:30 — fetch NAV mới nhất cho TẤT CẢ quỹ trong funds_master.
    Không giới hạn ở watched_funds — đây là master data pipeline.
    """
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[harvest] DB không khả dụng — bỏ qua")
        return

    log.info("══ JOB: Daily NAV Harvest ══")

    # Chạy harvest_nav.py --daily qua subprocess để tận dụng toàn bộ logic ở đó.
    # Dùng sys.executable để đảm bảo đúng Python environment (Railway virtualenv).
    import subprocess
    script = Path(__file__).parent.parent / "scripts" / "harvest_nav.py"
    if not script.exists():
        log.error("[harvest] scripts/harvest_nav.py không tìm thấy")
        return

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--daily"],
            capture_output=True, text=True, timeout=300,
            env={**__import__("os").environ},  # kế thừa DATABASE_URL
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            # Lấy dòng cuối (summary line) để log ngắn gọn
            summary = output.splitlines()[-1] if output else "OK"
            log.info("[harvest] %s", summary)
        else:
            log.error("[harvest] exit=%d stderr=%s", result.returncode,
                      (result.stderr or "")[:500])
    except subprocess.TimeoutExpired:
        log.error("[harvest] Timeout sau 300s")
    except Exception as e:
        log.error("[harvest] %s", e)


# ═══════════════════════════════════════
# DB USER HELPERS
# ═══════════════════════════════════════

def _ensure_db_user(
    telegram_id: int,
    profile_name: str,
) -> "tuple[str, str, bytes] | None":
    """Get-or-create DB user + default portfolio. Returns (user_uuid, portfolio_id, user_key).

    Returns None if DB, crypto, or ENCRYPTION_KEY is unavailable.
    Idempotent — safe to call on every command.
    """
    if not (_DB_AVAILABLE and _db.is_available() and _CRYPTO_AVAILABLE and _crypto.is_available()):
        return None
    master_key = _crypto.get_master_key()
    if not master_key:
        return None

    info = _db.get_user_info(telegram_id)
    if info:
        user_uuid = info["id"]
        user_key  = _crypto.derive_user_key(master_key, info["enc_salt"])
    else:
        enc_salt   = os.urandom(32)
        auth_hash  = _crypto.make_auth_hash(telegram_id, master_key)
        user_uuid  = _db.get_or_create_user(telegram_id, enc_salt, auth_hash)
        user_key   = _crypto.derive_user_key(master_key, enc_salt)

    name_enc     = _crypto.encrypt_str(profile_name or "Danh mục của tôi", user_key)
    portfolio_id = _db.get_or_create_portfolio(user_uuid, name_enc)
    return user_uuid, portfolio_id, user_key


def _get_db_user(telegram_id: int) -> "tuple[str, str, bytes] | None":
    """Read-only: returns (user_uuid, portfolio_id, user_key) only if user already exists in DB.

    Used by /portfolio so it doesn't create empty records for every viewer.
    """
    if not (_DB_AVAILABLE and _db.is_available() and _CRYPTO_AVAILABLE and _crypto.is_available()):
        return None
    master_key = _crypto.get_master_key()
    if not master_key:
        return None
    info = _db.get_user_info(telegram_id)
    if not info:
        return None
    user_uuid    = info["id"]
    user_key     = _crypto.derive_user_key(master_key, info["enc_salt"])
    portfolio_id = _db.get_portfolio_id(user_uuid)
    if not portfolio_id:
        return None
    return user_uuid, portfolio_id, user_key


def _msg_portfolio_from_db(
    profile: dict,
    raw_holdings: list,
    nav_data: dict,
    user_key: bytes,
) -> str:
    """Build portfolio P&L message from decrypted DB holdings."""
    now = datetime.now()
    lines = [
        f"📊 <b>DANH MỤC — {profile['name']}</b>",
        f"📅 {now.strftime('%d/%m/%Y %H:%M')}",
        LINE,
    ]
    total_value = 0.0
    total_cost  = 0.0

    for h in raw_holdings:
        fund_code = h["fund_code"]
        try:
            units    = _crypto.decrypt_decimal(h["units_enc"],    user_key)
            avg_cost = _crypto.decrypt_decimal(h["avg_cost_enc"], user_key)
        except Exception:
            lines.append(f"⚠️ <code>{fund_code}</code>  Lỗi giải mã")
            continue
        if units <= 0:
            continue
        d = nav_data.get(fund_code)
        if not d or d["nav"] == 0:
            lines.append(f"⚠️ <code>{fund_code}</code>  N/A (chưa có NAV)")
            continue
        nav_now   = d["nav"]
        cost_val  = units * avg_cost
        cur_val   = units * nav_now
        pnl       = cur_val - cost_val
        pnl_pct   = (nav_now - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
        emoji     = "🟢" if "MUA" in d["signal"] else "🔴" if "BÁN" in d["signal"] else "⚪"
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_sign  = "+" if pnl >= 0 else ""
        pct_sign  = "+" if pnl_pct >= 0 else ""
        lines.append(
            f"{emoji} <b><code>{fund_code}</code></b>  {units:,.3f} CCQ\n"
            f"   Giá vốn: {int(avg_cost):,}đ → Hiện: {int(nav_now):,}đ "
            f"({pct_sign}{pnl_pct:.2f}%)  {d['signal']}\n"
            f"   {pnl_emoji} Giá trị: {int(cur_val):,}đ  |  "
            f"{'Lãi' if pnl >= 0 else 'Lỗ'}: <b>{pnl_sign}{int(pnl):,}đ</b>"
        )
        total_value += cur_val
        total_cost  += cost_val

    if total_cost > 0:
        total_pnl     = total_value - total_cost
        total_pnl_pct = total_pnl / total_cost * 100
        pnl_sign      = "+" if total_pnl >= 0 else ""
        pct_sign      = "+" if total_pnl_pct >= 0 else ""
        lines.append(LINE)
        lines.append(
            f"💰 <b>Tổng: {int(total_value):,}đ</b>  |  "
            f"{'Lãi' if total_pnl >= 0 else 'Lỗ'}: "
            f"<b>{pnl_sign}{int(total_pnl):,}đ ({pct_sign}{total_pnl_pct:.2f}%)</b>"
        )
    lines.append("<i>Bot không cung cấp khuyến nghị đầu tư.</i>")
    return "\n".join(lines)


# ═══════════════════════════════════════
# RESEARCH ANALYSIS HELPERS
# ═══════════════════════════════════════

def compute_research_stats(pts: list) -> dict:
    """Extended stats from NAV series for /research command."""
    import math
    import statistics as _stats_mod
    if len(pts) < 10:
        return {}
    navs    = [p["nav"] for p in pts]
    nav_now = navs[-1]
    today   = date.today()
    cutoff_1y = f"{today.year - 1}-{today.month:02d}-{today.day:02d}"

    idx_1y  = next((i for i, p in enumerate(pts) if p["date"] >= cutoff_1y), 0)
    navs_1y = navs[idx_1y:] if idx_1y < len(navs) else navs
    nav_52w_high = max(navs_1y)
    nav_52w_low  = min(navs_1y)
    range_52w    = nav_52w_high - nav_52w_low

    chg365        = round((nav_now / navs[idx_1y] - 1) * 100, 2) if navs[idx_1y] > 0 else None
    pct_from_high = round((nav_now - nav_52w_high) / nav_52w_high * 100, 2) if nav_52w_high > 0 else 0.0
    pct_from_low  = round((nav_now - nav_52w_low)  / nav_52w_low  * 100, 2) if nav_52w_low  > 0 else 0.0
    pos_in_range  = round((nav_now - nav_52w_low)  / range_52w    * 100, 1) if range_52w    > 0 else 50.0

    vol_30d = None
    if len(navs) >= 31:
        recent = navs[-31:]
        rets = [(recent[i] / recent[i - 1] - 1) for i in range(1, len(recent)) if recent[i - 1] > 0]
        try:
            vol_30d = round(_stats_mod.stdev(rets) * math.sqrt(252) * 100, 2)
        except Exception:
            pass

    peak   = navs_1y[0] if navs_1y else nav_now
    max_dd = 0.0
    for n in navs_1y:
        peak = max(peak, n)
        if peak > 0:
            max_dd = min(max_dd, (n - peak) / peak * 100)

    return {
        "nav_52w_high":  nav_52w_high,
        "nav_52w_low":   nav_52w_low,
        "chg365":        chg365,
        "pct_from_high": pct_from_high,
        "pct_from_low":  pct_from_low,
        "pos_in_range":  pos_in_range,
        "vol_30d":       vol_30d,
        "max_drawdown":  round(max_dd, 2),
    }


def msg_research(code: str, d: dict, stats: dict, fund_name: str = "") -> str:
    """Multi-school deep analysis message for /research command."""
    now       = datetime.now()
    nav       = d.get("nav", 0)
    rsi       = d.get("rsi")
    bb        = d.get("bb_pct")
    ma20      = d.get("ma20") or 0.0
    ma50      = d.get("ma50") or 0.0
    score     = d.get("score", 0)
    sig       = d.get("signal", "—")
    chg_pct   = d.get("chg_pct", 0) or 0
    chg30     = d.get("chg30")
    macd_hist = d.get("macd_hist")

    nav_52w_high  = stats.get("nav_52w_high", nav)
    nav_52w_low   = stats.get("nav_52w_low",  nav)
    pct_from_high = stats.get("pct_from_high", 0.0)
    pct_from_low  = stats.get("pct_from_low",  0.0)
    pos_in_range  = stats.get("pos_in_range",  50.0)
    chg365        = stats.get("chg365")
    vol_30d       = stats.get("vol_30d")
    max_dd        = stats.get("max_drawdown", 0.0)

    # ─── 1. Technical ─────────────────────────────────────────
    if score >= 6:    ta_v = "🟢🟢 MUA MẠNH"
    elif score >= 3:  ta_v = "🟢 MUA"
    elif score <= -6: ta_v = "🔴🔴 BÁN MẠNH"
    elif score <= -3: ta_v = "🔴 BÁN"
    else:             ta_v = "⚪ TRUNG TÍNH"

    if rsi is None:   rsi_note = "—"
    elif rsi < 30:    rsi_note = f"{rsi:.1f} — Quá bán mạnh 🟢🟢"
    elif rsi < 40:    rsi_note = f"{rsi:.1f} — Vùng quá bán 🟢"
    elif rsi > 75:    rsi_note = f"{rsi:.1f} — Quá mua mạnh 🔴🔴"
    elif rsi > 65:    rsi_note = f"{rsi:.1f} — Vùng quá mua 🔴"
    else:             rsi_note = f"{rsi:.1f} — Trung tính ⚪"

    if bb is None: bb_note = "—"
    elif bb < 10:  bb_note = f"{bb:.0f}% — Đáy dải 🟢🟢"
    elif bb < 20:  bb_note = f"{bb:.0f}% — Gần đáy 🟢"
    elif bb > 90:  bb_note = f"{bb:.0f}% — Đỉnh dải 🔴🔴"
    elif bb > 80:  bb_note = f"{bb:.0f}% — Gần đỉnh 🔴"
    else:          bb_note = f"{bb:.0f}% — Vùng giữa ⚪"

    macd_note = "—"
    if macd_hist is not None:
        macd_note = f"{'Dương (+)' if macd_hist > 0 else 'Âm (-)'} — {'Đà tăng 🟢' if macd_hist > 0 else 'Đà giảm ⚠️'}"

    ma_note = "—"
    if ma20 and ma50:
        ma_note = f"MA20 {'&gt;' if ma20 > ma50 else '&lt;'} MA50 → {'Xu hướng tăng ↑' if ma20 > ma50 else 'Xu hướng giảm ↓'}"

    # ─── 2. Value ─────────────────────────────────────────────
    if pct_from_low < 5:     val_v = "🟢🟢 RẤT RẺ — Gần đáy 52 tuần"
    elif pct_from_low < 15:  val_v = "🟢 RẺ — Vùng tích lũy tốt"
    elif pct_from_high > -5: val_v = "🔴 ĐẮT — Gần đỉnh 52 tuần"
    elif pos_in_range > 70:  val_v = "⚠️ TRUNG BÌNH CAO"
    else:                    val_v = "⚪ TRUNG BÌNH"

    filled  = max(0, min(10, int(pos_in_range / 10)))
    pos_bar = "█" * filled + "░" * (10 - filled)

    # ─── 3. Momentum ──────────────────────────────────────────
    up_trend = bool(ma20 and ma50 and ma20 > ma50)
    if chg30 is not None and ma20 and ma50:
        if chg30 > 2 and up_trend:      mom_v = "🟢 TĂNG MẠNH — Đà và xu hướng tốt"
        elif chg30 < -2 and not up_trend: mom_v = "🔴 GIẢM — Không bắt đáy vội"
        elif up_trend:                   mom_v = "⚪ TĂNG NHẸ — Xu hướng tích cực"
        else:                            mom_v = "⚠️ PHÂN KỲ — Đà ngắn hạn suy yếu"
    else:
        mom_v = "⚪ Không đủ dữ liệu"

    # ─── 4. DCA ───────────────────────────────────────────────
    below_ma50 = bool(ma50 and nav < ma50)
    oversold   = rsi is not None and rsi < 45
    if below_ma50 and oversold:   dca_v = "🟢🟢 TỐT NHẤT — Dưới MA50 + RSI quá bán"
    elif below_ma50 or oversold:  dca_v = "🟢 PHÙ HỢP — Giá hợp lý để tích lũy dần"
    elif pct_from_high > -5:      dca_v = "⚠️ NÊN CHỜ — NAV gần đỉnh 52 tuần"
    else:                         dca_v = "⚪ TRUNG TÍNH — Theo kế hoạch DCA"

    # ─── 5. Risk ──────────────────────────────────────────────
    if vol_30d is not None:
        if vol_30d < 4:    risk_v = "🟢 THẤP"
        elif vol_30d < 10: risk_v = "🟡 TRUNG BÌNH"
        else:              risk_v = "🔴 CAO"
    else:
        risk_v = "⚪ Không đủ dữ liệu"

    chg_s   = f"{'+' if chg_pct >= 0 else ''}{chg_pct:.2f}%"
    chg30_s = f"{'+' if chg30 >= 0 else ''}{chg30:.1f}%" if chg30 is not None else "—"
    yr_s    = f"{'+' if chg365 >= 0 else ''}{chg365:.1f}%" if chg365 is not None else "N/A"
    dd_s    = f"{max_dd:.1f}%" if max_dd else "—"

    lines = [f"🔬 <b>PHÂN TÍCH — <code>{code}</code></b>"]
    if fund_name:
        lines.append(f"<i>{fund_name}</i>")
    lines += [
        f"📅 {now.strftime('%d/%m/%Y')}  💰 <b>{fmt_nav(nav)}</b>  {chg_s}  {sig}",
        LINE,
        f"<b>1️⃣ KỸ THUẬT (Technical Analysis)</b>",
        f"   RSI(14):   {rsi_note}",
        f"   Bollinger: {bb_note}",
        f"   MACD:      {macd_note}",
        f"   {ma_note}",
        f"   <b>→ {ta_v}</b>",
        LINE,
        f"<b>2️⃣ GIÁ TRỊ (Value Investing)</b>",
        f"   52T: {int(nav_52w_low):,} – {int(nav_52w_high):,}đ",
        f"   Vị trí: [{pos_bar}] {pos_in_range:.0f}%",
        f"   Cách đỉnh: {pct_from_high:+.1f}%  |  Cách đáy: +{pct_from_low:.1f}%",
        f"   1 năm: {yr_s}",
        f"   <b>→ {val_v}</b>",
        LINE,
        f"<b>3️⃣ XU HƯỚNG (Momentum / Trend)</b>",
        f"   30 ngày: {chg30_s}  |  {ma_note}",
        f"   <b>→ {mom_v}</b>",
        LINE,
        f"<b>4️⃣ ĐẦU TƯ ĐỊNH KỲ (DCA)</b>",
        f"   NAV vs MA50: {'Dưới ✅' if below_ma50 else 'Trên ⚠️'}  |  RSI: {'Quá bán ✅' if oversold else 'Bình thường'}",
        f"   <b>→ {dca_v}</b>",
        LINE,
        f"<b>5️⃣ RỦI RO (Risk Management)</b>",
        (f"   Biến động 30 ngày (năm hóa): {vol_30d:.1f}%  → {risk_v}" if vol_30d else f"   Biến động: {risk_v}"),
        f"   Max drawdown 1 năm: {dd_s}",
        f"   <b>→ Mức rủi ro: {risk_v}</b>",
        LINE,
        f"<b>📋 TỔNG KẾT</b>",
        f"   TA: {ta_v}   Value: {val_v.split('—')[0].strip()}",
        f"   Trend: {mom_v.split('—')[0].strip()}   DCA: {dca_v.split('—')[0].strip()}",
        LINE,
        f"<i>⚠️ Tham khảo — không phải khuyến nghị đầu tư cá nhân.</i>",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════
# DCA HELPER
# ═══════════════════════════════════════

def msg_dca_suggest(profile: dict, nav_data: dict, budget: float) -> str:
    """Gợi ý phân bổ DCA dựa trên signals. Weight = max(0, score + 6).
    Funds BÁN MẠNH (score ≤ -6) nhận 0%, còn lại theo tỉ lệ score.
    """
    now   = datetime.now()
    funds = profile.get("watched_funds", [])
    scored = []
    for code in funds:
        d = nav_data.get(code)
        if d and d.get("nav", 0) > 0:
            scored.append((code, d, d.get("score", 0)))

    if not scored:
        return "⚠️ Không có dữ liệu NAV để gợi ý DCA."

    # Weight: max(0, score + 6) — HOLD=6, MUA=9, MUA MẠNH=12, BÁN=3, BÁN MẠNH=0
    weighted = [(c, d, max(0.0, s + 6.0)) for c, d, s in scored]
    total_w  = sum(w for _, _, w in weighted)

    lines = [
        f"💰 <b>GỢI Ý DCA THÁNG {now.month}/{now.year}</b>",
        f"👤 {profile['name']}  |  Ngân sách: <b>{int(budget):,}đ</b>",
        LINE,
    ]

    if total_w == 0:
        lines += [
            "⚠️ <b>Tất cả quỹ đang có tín hiệu xấu.</b>",
            "Gợi ý: Giữ tiền mặt, chờ tín hiệu cải thiện.",
            LINE,
            "Tín hiệu hiện tại:",
        ]
        for c, d, _ in scored:
            lines.append(f"   🔴 <code>{c}</code>  {d['signal']}  (score {d.get('score',0):+})")
    else:
        allocs = []
        for c, d, w in weighted:
            pct    = w / total_w
            amount = round(pct * budget / 1_000) * 1_000
            allocs.append((c, d, pct, amount))

        for c, d, pct, amount in sorted(allocs, key=lambda x: -x[2]):
            emoji = "🟢" if "MUA" in d["signal"] else "🔴" if "BÁN" in d["signal"] else "⚪"
            skip  = "  <i>(bỏ qua tháng này)</i>" if amount == 0 else ""
            score_s = f"{d.get('score', 0):+}"
            lines.append(
                f"{emoji} <code>{c:<10}</code>  {pct*100:4.0f}%  →  <b>{int(amount):>12,}đ</b>"
                f"  [{score_s}]{skip}"
            )

        total_alloc = sum(a for _, _, _, a in allocs)
        remainder   = int(budget) - total_alloc
        lines += [
            LINE,
            f"💵 Tổng phân bổ: <b>{total_alloc:,}đ</b>" +
            (f"  |  Dư: {remainder:,}đ" if remainder else ""),
        ]

    lines += [
        LINE,
        "📌 <i>Weight = max(0, score + 6). BÁN MẠNH → bỏ qua.</i>",
        "💡 Lưu ngân sách: <code>/dca setup [số_tiền]</code>",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════
# TRADE HELPER (shared by /add-trade, /buy, /sell)
# ═══════════════════════════════════════

def _cmd_add_trade(
    token: str,
    chat_id: str,
    profile: dict,
    fund_code: str,
    tx_type: str,
    units: float,
    amount: float,
    order_date: "date",
) -> None:
    """Lưu giao dịch vào DB + cập nhật holding. Gửi confirm/error về Telegram."""
    if not (_DB_AVAILABLE and _db.is_available()):
        tg_send(token, chat_id, "⚠️ Database chưa kết nối. Liên hệ admin.")
        return
    if not (_CRYPTO_AVAILABLE and _crypto.is_available() and _crypto.get_master_key()):
        tg_send(token, chat_id, "⚠️ Encryption chưa được cấu hình (ENCRYPTION_KEY). Liên hệ admin.")
        return
    db_ctx = _ensure_db_user(int(chat_id), profile.get("name", "User"))
    if not db_ctx:
        tg_send(token, chat_id, "❌ Không thể khởi tạo tài khoản DB. Liên hệ admin.")
        return
    user_uuid, portfolio_id, user_key = db_ctx
    nav_at_order = round(amount / units, 4)
    try:
        _db.add_transaction(
            user_uuid    = user_uuid,
            portfolio_id = portfolio_id,
            fund_code    = fund_code,
            tx_type      = tx_type,
            order_date   = order_date,
            units_enc    = _crypto.encrypt_decimal(units,  user_key),
            amount_enc   = _crypto.encrypt_decimal(amount, user_key),
            nav_at_order = nav_at_order,
        )
    except Exception as e:
        log.error("[add-trade] add_transaction failed: %s", e)
        tg_send(token, chat_id, "❌ Lỗi khi lưu giao dịch. Vui lòng thử lại.")
        return
    try:
        existing_h = _db.get_holdings_raw(user_uuid, portfolio_id)
        prev_h     = next((h for h in existing_h if h["fund_code"] == fund_code), None)
        if prev_h:
            prev_units = _crypto.decrypt_decimal(prev_h["units_enc"],    user_key)
            prev_avg   = _crypto.decrypt_decimal(prev_h["avg_cost_enc"], user_key)
        else:
            prev_units, prev_avg = 0.0, 0.0
        if tx_type == "buy":
            new_units = prev_units + units
            new_avg   = ((prev_units * prev_avg) + (units * nav_at_order)) / new_units
        else:
            new_units = max(0.0, prev_units - units)
            new_avg   = prev_avg
        _db.upsert_holding(
            user_uuid    = user_uuid,
            portfolio_id = portfolio_id,
            fund_code    = fund_code,
            units_enc    = _crypto.encrypt_decimal(new_units, user_key),
            avg_cost_enc = _crypto.encrypt_decimal(new_avg,   user_key),
        )
    except Exception as e:
        log.error("[add-trade] upsert_holding failed: %s", e)
    action = "Mua" if tx_type == "buy" else "Bán"
    tg_send(token, chat_id, (
        f"✅ <b>Đã ghi giao dịch {action}</b>\n\n"
        f"📌 Quỹ: <code>{fund_code}</code>\n"
        f"📦 Số CCQ: <b>{units:,.3f}</b>\n"
        f"💰 Tổng tiền: <b>{int(amount):,}đ</b>\n"
        f"📊 NAV thực hiện: ~{int(nav_at_order):,}đ/CCQ\n"
        f"📅 Ngày lệnh: {order_date.strftime('%d/%m/%Y')}\n\n"
        f"Gõ /portfolio để xem danh mục cập nhật."
    ))


# ═══════════════════════════════════════
# TELEGRAM COMMAND HANDLER (long-polling)
# ═══════════════════════════════════════

def find_profile_by_chat(config: dict, chat_id: str) -> Optional[dict]:
    for p in config.get("profiles", []):
        tg = str(p.get("telegram_id", "")).strip().lstrip("@")
        if tg and tg == chat_id.strip().lstrip("@"):
            return p
    return None


# Seed profile cho admin (Harvey) — dùng để reconcile config trên /data (Railway).
# Khi Harvey tự /register, profile chỉ có default_watched_funds (3 quỹ) và không có
# portfolio → /portfolio rơi vào fallback 7/30 ngày. Reconcile lúc startup đảm bảo
# admin luôn có đủ 5 quỹ theo dõi + portfolio để hiển thị P&L all-time.
_ADMIN_PROFILE_SEED = {
    "watched_funds": ["TCBF", "VCBFTBF", "SSISCA", "VCBFBCF", "TCFF"],
    "portfolio": [
        {"code": "TCBF",    "units": 487.21,  "avg_cost": 20525},
        {"code": "SSISCA",  "units": 713.57,  "avg_cost": 42042},
        {"code": "VCBFBCF", "units": 839.29,  "avg_cost": 35744},
        {"code": "VCBFTBF", "units": 449.41,  "avg_cost": 33377},
        {"code": "TCFF",    "units": 1832.66, "avg_cost": 13641},
    ],
}


def reconcile_admin_profile(config: dict) -> bool:
    """Đảm bảo profile admin có đủ watched_funds + portfolio (seed).

    Trả về True nếu config bị thay đổi (cần save). An toàn idempotent — chỉ bổ sung
    quỹ thiếu và thêm portfolio nếu chưa có, KHÔNG ghi đè dữ liệu user đã nhập.
    """
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    if not admin_id or admin_id.startswith("NHAP"):
        return False

    profiles = config.setdefault("profiles", [])
    admin = None
    for p in profiles:
        if str(p.get("telegram_id", "")).strip() == admin_id:
            admin = p
            break

    changed = False
    if admin is None:
        admin = {"name": "Harvey", "telegram_id": admin_id}
        profiles.append(admin)
        changed = True
        log.info(f"[reconcile] Tạo profile admin Harvey ({admin_id})")

    # Bổ sung watched_funds còn thiếu (giữ thứ tự seed, không xoá quỹ user thêm)
    cur_watched = admin.get("watched_funds") or []
    merged = list(cur_watched)
    for code in _ADMIN_PROFILE_SEED["watched_funds"]:
        if code not in merged:
            merged.append(code)
            changed = True
    if merged != cur_watched:
        admin["watched_funds"] = merged

    # Thêm portfolio nếu chưa có (không ghi đè nếu user đã có dữ liệu)
    if not admin.get("portfolio"):
        admin["portfolio"] = [dict(h) for h in _ADMIN_PROFILE_SEED["portfolio"]]
        changed = True
        log.info("[reconcile] Thêm portfolio seed cho admin")

    return changed


def command_handler():
    offset = 0
    while True:
        try:
            config = load_config()
            token  = config.get("bot_token", "")
            if not token or token.startswith("NHAP"):
                time.sleep(60)
                continue
            base = f"https://api.telegram.org/bot{token}"
            r = requests.get(f"{base}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=40)
            if not r.ok:
                time.sleep(5)
                continue
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg    = upd.get("message") or upd.get("edited_message") or {}
                if not msg:
                    continue
                chat_id = str(msg["chat"]["id"])
                text    = msg.get("text", "").strip()
                parts   = text.split()  # luôn định nghĩa sẵn, tránh NameError
                cmd     = parts[0].lower().split("@")[0] if parts else ""
                log.info(f"[CMD] {cmd!r} from chat {chat_id}")
                profile = find_profile_by_chat(config, chat_id)

                try:
                    if cmd == "/getid":
                        tg_name = msg.get("chat", {}).get("first_name", "") or msg.get("chat", {}).get("title", "")
                        status = f"✅ Đã liên kết với profile <b>{profile['name']}</b>" if profile else "⚠️ Chưa đăng ký — dùng /register để tự đăng ký"
                        tg_send(token, chat_id, (f"🪪 <b>Thông tin chat của bạn</b>\n\nTên Telegram: {tg_name}\nChat ID: <code>{chat_id}</code>\nTrạng thái: {status}"))
                        continue

                    if cmd == "/register":
                        if profile:
                            tg_send(token, chat_id, f"✅ Bạn đã đăng ký rồi — profile: <b>{profile['name']}</b>\nChat ID: <code>{chat_id}</code>")
                            continue
                        parts = text.split(maxsplit=1)
                        tg_name = msg.get("chat", {}).get("first_name", "")
                        reg_name = parts[1].strip() if len(parts) > 1 else tg_name or f"User_{chat_id[-4:]}"
                        cfg_w = load_config()
                        default_funds = cfg_w.get("default_watched_funds", ["TCBF", "SSISCA", "VCBFBCF"])
                        new_p = {"name": reg_name, "telegram_id": chat_id, "watched_funds": default_funds}
                        cfg_w.setdefault("profiles", []).append(new_p)
                        save_config(cfg_w)
                        log.info(f"[REGISTER] New profile: {reg_name} ({chat_id})")
                        tg_send(token, chat_id, (f"✅ <b>Đăng ký thành công!</b>\n\nTên: <b>{reg_name}</b>\nChat ID: <code>{chat_id}</code>\nQuỹ theo dõi mặc định: {', '.join(default_funds)}\n\nDùng /nav để xem NAV ngay, hoặc /help để xem tất cả lệnh."))
                        admin_id = cfg_w.get("admin_telegram_id", "")
                        if admin_id and admin_id != chat_id:
                            tg_send(token, admin_id, (f"🔔 <b>User mới đăng ký</b>\nTên: <b>{reg_name}</b>\nChat ID: <code>{chat_id}</code>\nTổng profiles: {len(cfg_w.get('profiles', []))}"))
                        continue

                    if cmd in ("/start", "/help"):
                        profile_note = (f"\n\n✅ Xin chào <b>{profile['name']}</b>! Bot đã nhận diện bạn." if profile else f"\n\n👤 Bạn chưa đăng ký. Gõ:\n<code>/register Tên Của Bạn</code>\nđể tự đăng ký và nhận báo cáo tự động.")
                        n_funds = len(config.get("funds", {}))
                        tg_send(token, chat_id, (
                            "👋 <b>Quỹ Tracker Pro Bot</b>\n\n"
                            "<b>Theo dõi NAV:</b>\n"
                            "📈 /nav — NAV quỹ của bạn + tín hiệu\n"
                            f"🌐 /navall — NAV tất cả {n_funds} quỹ trong hệ thống\n"
                            "📊 /signal — Tín hiệu kỹ thuật (RSI, BB, MACD)\n"
                            "🔍 /explain [MÃ] — Phân tích chi tiết\n"
                            "🔬 /research MÃ — Phân tích chuyên sâu 5 trường phái\n"
                            "📚 /learn — Từ điển chỉ số &amp; trường phái đầu tư\n\n"
                            "<b>Danh mục &amp; Giao dịch:</b>\n"
                            "🗂 /portfolio — Xem danh mục + P&amp;L\n"
                            "🟢 /buy MÃ số_CCQ tổng_tiền [ngày] — Ghi lệnh mua\n"
                            "🔴 /sell MÃ số_CCQ tổng_tiền [ngày] — Ghi lệnh bán\n"
                            "➕ /add-trade MÃ buy/sell CCQ tiền [ngày] — Ghi giao dịch\n"
                            "💰 /dca [số_tiền] — Gợi ý phân bổ DCA theo tín hiệu\n"
                            "💰 /dca setup [số_tiền] — Lưu ngân sách DCA hàng tháng\n\n"
                            "<b>Quản lý danh mục:</b>\n"
                            "📋 /funds — Xem tất cả quỹ có thể theo dõi\n"
                            "👁 /watch TCBF SSISCA — Thêm quỹ vào danh mục\n"
                            "🚫 /unwatch TCBF — Bỏ quỹ khỏi danh mục\n\n"
                            "<b>Báo cáo tự động:</b>\n"
                            "🌅 /morning — Báo cáo sáng (ngay bây giờ)\n"
                            "🌆 /evening — Báo cáo chiều (ngay bây giờ)\n"
                            "📢 Auto: Thông báo khi có NAV mới hàng ngày\n\n"
                            "<b>Tài khoản &amp; TCBS:</b>\n"
                            "🪪 /getid — Xem Chat ID của bạn\n"
                            "✍️ /register [tên] — Tự đăng ký nhận báo cáo\n"
                            "🔐 /otp — Gửi OTP làm mới TCBS token\n"
                            "🔐 /otp 123456 — Xác nhận OTP (sau khi nhận SMS)\n"
                            "🔐 /otp setup 0901... — Đăng ký SĐT TCBS lần đầu\n"
                            "❓ /help — Trợ giúp\n\n"
                            "🔔 <b>Tự động:</b>\n"
                            "• 08:00 T2–T6 → Báo cáo sáng\n"
                            "• 17:30 T2–T6 → Báo cáo chiều\n"
                            "• Cảnh báo ngay khi tín hiệu MUA/BÁN thay đổi\n\n"
                            "<i>Bot không cung cấp khuyến nghị đầu tư.</i>"
                        ) + profile_note)

                    elif cmd == "/nav":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                        tg_send(token, chat_id, msg_nav_query(profile, nav_data))

                    elif cmd == "/navall":
                        all_codes = set(config.get("funds", {}).keys())
                        if not all_codes:
                            tg_send(token, chat_id, "⚠️ Không có quỹ nào trong config.")
                            continue
                        nav_data_all = fetch_all(config, all_codes)
                        now_na = datetime.now()
                        lines_na = [
                            f"📈 <b>NAV TẤT CẢ QUỸ — {now_na.strftime('%d/%m/%Y %H:%M')}</b>",
                            LINE,
                        ]
                        for code_na in sorted(nav_data_all.keys()):
                            d_na = nav_data_all[code_na]
                            if not d_na or d_na.get("nav", 0) == 0:
                                lines_na.append(f"⚠️ <code>{code_na}</code>  N/A")
                                continue
                            sig_na  = d_na.get("signal", "—")
                            chg_na  = d_na.get("chg_pct", 0) or 0
                            chg_s   = f"{'+' if chg_na >= 0 else ''}{chg_na:.2f}%"
                            emoji   = "🟢" if "MUA" in sig_na else "🔴" if "BÁN" in sig_na else "⚪"
                            lines_na.append(
                                f"{emoji} <code>{code_na:<10}</code>  {fmt_nav(d_na['nav']):>13}  "
                                f"<i>{chg_s}</i>  {sig_na}"
                            )
                        lines_na.append(LINE)
                        lines_na.append(f"<i>{len(nav_data_all)} quỹ · {now_na.strftime('%H:%M')}</i>")
                        tg_send(token, chat_id, "\n".join(lines_na))

                    elif cmd == "/signal":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                        tg_send(token, chat_id, msg_signal_summary(profile, nav_data))

                    elif cmd == "/portfolio":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        db_ctx = _get_db_user(int(chat_id))
                        if db_ctx:
                            user_uuid, portfolio_id, user_key = db_ctx
                            raw = _db.get_holdings_raw(user_uuid, portfolio_id)
                            if raw:
                                held_codes = {h["fund_code"] for h in raw}
                                nav_data = fetch_all(config, held_codes)
                                tg_send(token, chat_id, _msg_portfolio_from_db(profile, raw, nav_data, user_key))
                                continue
                        # Fallback: config.json portfolio (watched_funds + P&L if portfolio field present)
                        nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                        tg_send(token, chat_id, msg_portfolio(profile, nav_data))

                    elif cmd == "/add-trade":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        parts_tr = text.split()
                        if len(parts_tr) < 5:
                            tg_send(token, chat_id, (
                                "❓ <b>Cú pháp /add-trade:</b>\n\n"
                                "<code>/add-trade MÃ loại số_CCQ tổng_tiền [ngày]</code>\n\n"
                                "Ví dụ:\n"
                                "<code>/add-trade TCBF buy 1000.5 15000000</code>\n"
                                "<code>/add-trade SSISCA sell 200 3200000 2026-06-15</code>\n\n"
                                "• <b>loại</b>: <code>buy</code> hoặc <code>sell</code>\n"
                                "• <b>số_CCQ</b>: số chứng chỉ quỹ nhận được\n"
                                "• <b>tổng_tiền</b>: số VND thực tế thanh toán\n"
                                "• <b>ngày</b>: ngày lệnh (YYYY-MM-DD), mặc định hôm nay"
                            ))
                            continue
                        tr_fund = parts_tr[1].upper()
                        tr_type = parts_tr[2].lower()
                        if tr_type not in ("buy", "sell"):
                            tg_send(token, chat_id, "⚠️ Loại giao dịch phải là <code>buy</code> hoặc <code>sell</code>.")
                            continue
                        if tr_fund not in config.get("funds", {}):
                            tg_send(token, chat_id, f"⚠️ Không tìm thấy quỹ <code>{tr_fund}</code>.\nGõ /funds để xem danh sách.")
                            continue
                        try:
                            tr_units  = float(parts_tr[3])
                            tr_amount = float(parts_tr[4])
                            if tr_units <= 0 or tr_amount <= 0:
                                raise ValueError("non-positive")
                        except (ValueError, IndexError):
                            tg_send(token, chat_id, "⚠️ Số CCQ và số tiền phải là số dương.")
                            continue
                        tr_date_str = parts_tr[5] if len(parts_tr) > 5 else date.today().isoformat()
                        try:
                            tr_order_date = date.fromisoformat(tr_date_str)
                        except ValueError:
                            tg_send(token, chat_id, f"⚠️ Ngày không hợp lệ: <code>{tr_date_str}</code>\nDùng định dạng YYYY-MM-DD.")
                            continue
                        _cmd_add_trade(token, chat_id, profile, tr_fund, tr_type, tr_units, tr_amount, tr_order_date)

                    elif cmd in ("/buy", "/sell"):
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        tx_type_bs = "buy" if cmd == "/buy" else "sell"
                        action_bs  = "Mua" if tx_type_bs == "buy" else "Bán"
                        parts_bs   = text.split()
                        # Format: /buy MÃ số_CCQ tổng_tiền [ngày]
                        if len(parts_bs) < 4:
                            tg_send(token, chat_id, (
                                f"❓ <b>Cú pháp /{action_bs.lower()}:</b>\n\n"
                                f"<code>/{action_bs.lower()} MÃ số_CCQ tổng_tiền [ngày]</code>\n\n"
                                f"Ví dụ:\n"
                                f"<code>/{action_bs.lower()} TCBF 1000.5 15000000</code>\n"
                                f"<code>/{action_bs.lower()} SSISCA 200 3200000 2026-06-15</code>"
                            ))
                            continue
                        bs_fund = parts_bs[1].upper()
                        if bs_fund not in config.get("funds", {}):
                            tg_send(token, chat_id, f"⚠️ Không tìm thấy quỹ <code>{bs_fund}</code>.\nGõ /funds để xem danh sách.")
                            continue
                        try:
                            bs_units  = float(parts_bs[2])
                            bs_amount = float(parts_bs[3])
                            if bs_units <= 0 or bs_amount <= 0:
                                raise ValueError("non-positive")
                        except (ValueError, IndexError):
                            tg_send(token, chat_id, (
                                f"⚠️ Cú pháp: <code>/{action_bs.lower()} MÃ số_CCQ tổng_tiền [ngày]</code>\n"
                                f"Số CCQ và số tiền phải là số dương."
                            ))
                            continue
                        bs_date_str = parts_bs[4] if len(parts_bs) > 4 else date.today().isoformat()
                        try:
                            bs_order_date = date.fromisoformat(bs_date_str)
                        except ValueError:
                            tg_send(token, chat_id, f"⚠️ Ngày không hợp lệ: <code>{bs_date_str}</code>\nDùng định dạng YYYY-MM-DD.")
                            continue
                        _cmd_add_trade(token, chat_id, profile, bs_fund, tx_type_bs, bs_units, bs_amount, bs_order_date)

                    elif cmd == "/explain":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        parts  = text.split()
                        target = parts[1].upper() if len(parts) > 1 else None
                        codes_ = set(profile.get("watched_funds", []))
                        if target and target not in codes_:
                            tg_send(token, chat_id, f"⚠️ Quỹ <code>{target}</code> không có trong danh mục.\nDanh mục hiện tại: {', '.join(sorted(codes_))}")
                            continue
                        nav_data = fetch_all(config, {target} if target else codes_)
                        tg_send(token, chat_id, msg_explain(profile, nav_data, target))

                    elif cmd == "/research":
                        parts_rs = text.split()
                        if len(parts_rs) < 2:
                            tg_send(token, chat_id, (
                                "❓ Cú pháp: <code>/research MÃ_QUỸ</code>\n"
                                "Ví dụ: <code>/research TCBF</code>\n\n"
                                "Phân tích chuyên sâu theo 5 trường phái đầu tư:\n"
                                "1️⃣ Kỹ thuật  2️⃣ Giá trị  3️⃣ Xu hướng  4️⃣ DCA  5️⃣ Rủi ro"
                            ))
                            continue
                        rs_code    = parts_rs[1].upper()
                        cfg_funds  = config.get("funds", {})
                        if rs_code not in cfg_funds:
                            tg_send(token, chat_id, f"⚠️ Không tìm thấy quỹ <code>{rs_code}</code>.\nGõ /funds để xem danh sách.")
                            continue
                        rs_pts = get_nav_series(rs_code, cfg_funds[rs_code], config)
                        if not rs_pts or len(rs_pts) < 60:
                            tg_send(token, chat_id, f"⚠️ Không đủ dữ liệu cho <code>{rs_code}</code> (cần ≥60 điểm NAV).")
                            continue
                        rs_d     = calc_signal(rs_code, rs_pts)
                        rs_stats = compute_research_stats(rs_pts)
                        tg_send(token, chat_id, msg_research(rs_code, rs_d, rs_stats, cfg_funds[rs_code].get("name", "")))

                    # ── LEARN: chỉ số kỹ thuật ──────────────────────────────
                    elif cmd == "/rsi":
                        tg_send(token, chat_id, (
                            "📊 <b>RSI — Relative Strength Index</b>\n"
                            "Tác giả: J. Welles Wilder (1978)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Dao động 0–100 đo <i>tốc độ</i> và <i>biên độ</i> thay đổi giá. "
                            "So sánh trung bình ngày tăng vs ngày giảm trong 14 kỳ.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• RSI &lt; 30 → <b>Quá bán</b> 🟢 — thị trường đã bán quá mức, "
                            "có thể chuẩn bị bật\n"
                            "• RSI &gt; 70 → <b>Quá mua</b> 🔴 — đà tăng có thể cạn kiệt\n"
                            "• RSI 40–60 → Trung tính ⚪\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "NAV cập nhật T+1 (không realtime) nên RSI &lt; 33 mới thực sự "
                            "có ý nghĩa. Dùng kết hợp BB và MACD để xác nhận.\n\n"
                            "<b>Công thức:</b>\n"
                            "<code>RSI = 100 − 100/(1 + RS)</code>\n"
                            "<code>RS = Avg Gain / Avg Loss (14 kỳ)</code>\n\n"
                            "📌 Bot dùng RSI 14 kỳ. Ngưỡng: &lt;33 MUA, &gt;70 BÁN."
                        ))

                    elif cmd == "/macd":
                        tg_send(token, chat_id, (
                            "📊 <b>MACD — Moving Average Convergence Divergence</b>\n"
                            "Tác giả: Gerald Appel (1979)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Hiệu của 2 EMA (12 và 26 kỳ), kết hợp với đường Signal (EMA 9 "
                            "của MACD). Histogram = MACD − Signal.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• Histogram &gt; 0 → đà tăng 🟢 (MACD vượt Signal)\n"
                            "• Histogram &lt; 0 → đà giảm 🔴 (MACD dưới Signal)\n"
                            "• MACD cắt Signal từ dưới lên → <b>Tín hiệu MUA</b> 🟢\n"
                            "• MACD cắt Signal từ trên xuống → <b>Tín hiệu BÁN</b> 🔴\n\n"
                            "<b>Phân kỳ (Divergence):</b>\n"
                            "NAV lập đỉnh mới nhưng MACD không → <i>Phân kỳ âm</i> ⚠️ "
                            "(đà tăng yếu dần, sắp đảo chiều)\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "MACD histogram dương liên tiếp 3+ kỳ là xác nhận xu hướng "
                            "tăng khỏe. Tránh dùng đơn lẻ, cần xác nhận RSI hoặc BB.\n\n"
                            "<b>Công thức:</b>\n"
                            "<code>MACD = EMA(12) − EMA(26)</code>\n"
                            "<code>Signal = EMA(9) of MACD</code>\n"
                            "<code>Hist = MACD − Signal</code>\n\n"
                            "📌 Bot dùng bộ chuẩn (12, 26, 9)."
                        ))

                    elif cmd == "/bb":
                        tg_send(token, chat_id, (
                            "📊 <b>BB — Bollinger Bands</b>\n"
                            "Tác giả: John Bollinger (1983)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "3 dải quanh MA20: dải giữa = MA20, dải trên/dưới = MA20 ± 2σ "
                            "(2 lần độ lệch chuẩn). Khoảng 95% giá nằm trong dải.\n\n"
                            "<b>Đọc tín hiệu (BB%):</b>\n"
                            "Bot tính <b>BB%</b> = vị trí NAV trong dải (0%=đáy, 100%=đỉnh)\n"
                            "• BB% &lt; 20% → Gần đáy dải 🟢 — NAV thấp bất thường, "
                            "có thể phục hồi\n"
                            "• BB% &gt; 80% → Gần đỉnh dải 🔴 — NAV cao bất thường\n"
                            "• BB% 20–80% → Vùng giữa ⚪\n\n"
                            "<b>Squeeze (dải thu hẹp):</b>\n"
                            "Khi dải Bollinger hẹp lại (biến động thấp) → thường báo hiệu "
                            "sắp có biến động lớn. Không biết là tăng hay giảm.\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "BB% &lt; 15% kết hợp RSI &lt; 35 là vùng mua tốt nhất theo "
                            "phong cách Value/Contrarian.\n\n"
                            "<b>Công thức:</b>\n"
                            "<code>Upper = MA20 + 2σ</code>\n"
                            "<code>Lower = MA20 − 2σ</code>\n"
                            "<code>BB% = (NAV − Lower)/(Upper − Lower) × 100</code>\n\n"
                            "📌 Bot dùng BB 20 kỳ, 2 σ."
                        ))

                    elif cmd == "/stoch":
                        tg_send(token, chat_id, (
                            "📊 <b>Stochastic Oscillator (%K)</b>\n"
                            "Tác giả: George Lane (1950s)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Đo vị trí giá hiện tại trong vùng giá cao-thấp 14 kỳ. "
                            "Dao động 0–100.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• %K &lt; 20 → Quá bán 🟢\n"
                            "• %K &gt; 80 → Quá mua 🔴\n"
                            "• %K cắt %D từ dưới &lt; 20 → Tín hiệu MUA mạnh 🟢🟢\n\n"
                            "<b>Khác RSI:</b>\n"
                            "RSI đo <i>tốc độ thay đổi</i>. Stoch đo <i>vị trí giá</i> "
                            "trong range. Stoch nhạy hơn với biến động ngắn hạn.\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "Stoch &lt; 20 + RSI &lt; 33 là xác nhận mạnh nhất cho vùng "
                            "quá bán. Dùng trong /research (điểm kỹ thuật).\n\n"
                            "<code>%K = (NAV − Low14)/(High14 − Low14) × 100</code>\n\n"
                            "📌 Bot dùng Stoch 14 kỳ."
                        ))

                    elif cmd == "/atr":
                        tg_send(token, chat_id, (
                            "📊 <b>ATR — Average True Range</b>\n"
                            "Tác giả: J. Welles Wilder (1978)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Đo <i>biến động trung bình</i> trong 14 kỳ. ATR% = ATR/NAV×100 "
                            "cho biết biến động tương đối.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• ATR% thấp → thị trường ổn định, xu hướng rõ ràng\n"
                            "• ATR% cao → biến động lớn, rủi ro cao hơn\n"
                            "• ATR tăng đột biến → thường xảy ra ở đáy thị trường (panic)\n\n"
                            "<b>Ứng dụng thực tế:</b>\n"
                            "• Đặt stop-loss: 1.5–2× ATR tính từ điểm mua\n"
                            "• So sánh quỹ: quỹ cổ phiếu ATR% 1–3%, quỹ trái phiếu "
                            "ATR% 0.1–0.5%\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "ATR% cao (&gt;2%) + RSI thấp = vùng biến động mạnh, rủi ro "
                            "cao nhưng cũng là cơ hội cho value investor.\n\n"
                            "<code>TR = max(High−Low, |High−Close_prev|, |Low−Close_prev|)</code>\n"
                            "<code>ATR = EMA(TR, 14)</code>\n\n"
                            "📌 Bot tính ATR% = ATR/NAV hiện tại × 100."
                        ))

                    elif cmd == "/sharpe":
                        tg_send(token, chat_id, (
                            "📊 <b>Sharpe Ratio</b>\n"
                            "Tác giả: William Sharpe (1966, Nobel 1990)\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Đo lợi nhuận thu được <i>trên mỗi đơn vị rủi ro</i>. "
                            "Là thước đo hiệu suất điều chỉnh rủi ro quan trọng nhất.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• Sharpe &gt; 1.5 → Rất tốt 🟢🟢\n"
                            "• Sharpe 1–1.5 → Tốt 🟢\n"
                            "• Sharpe 0.5–1 → Chấp nhận được ⚪\n"
                            "• Sharpe &lt; 0.5 → Lợi nhuận không xứng rủi ro 🔴\n"
                            "• Sharpe &lt; 0 → Thua lãi suất phi rủi ro 🔴🔴\n\n"
                            "<b>Hạn chế:</b>\n"
                            "Giả định phân phối lợi nhuận chuẩn (normal). Thực tế quỹ "
                            "cổ phiếu có đuôi béo (fat tail) → Sharpe có thể lạc quan hơn thực tế.\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "Dùng để so sánh các quỹ cùng loại (quỹ trái phiếu vs quỹ "
                            "trái phiếu). Không so trái phiếu vs cổ phiếu.\n\n"
                            "<code>Sharpe = (R_p − R_f) / σ_p</code>\n"
                            "<code>R_f ≈ 4.5%/năm (lãi suất tiền gửi 12T VN)</code>\n\n"
                            "📌 Bot tính Sharpe năm hóa, chuẩn hóa bằng √252."
                        ))

                    elif cmd == "/momentum" or cmd == "/mom":
                        tg_send(token, chat_id, (
                            "📊 <b>Momentum — Đà Tăng Trưởng</b>\n"
                            "──────────────────────────\n"
                            "<b>Là gì?</b>\n"
                            "Tài sản đang tăng giá có xu hướng <i>tiếp tục tăng</i> "
                            "trong ngắn-trung hạn (nghiên cứu Jegadeesh & Titman 1993). "
                            "Bot đo momentum bằng % thay đổi NAV 7 và 30 ngày.\n\n"
                            "<b>Đọc tín hiệu:</b>\n"
                            "• 30d &gt; +2% + MA20 &gt; MA50 → Đà tăng mạnh 🟢\n"
                            "• 30d &lt; -2% + MA20 &lt; MA50 → Đà giảm 🔴\n"
                            "• MA20 &gt; MA50 nhưng 30d âm → <i>Phân kỳ</i> ⚠️ "
                            "(xu hướng dài hạn tốt nhưng ngắn hạn yếu)\n\n"
                            "<b>Với quỹ mở VN:</b>\n"
                            "Momentum quỹ cổ phiếu thường kéo dài 1–3 tháng. Quỹ trái "
                            "phiếu ít biến động hơn, momentum ngắn hơn.\n\n"
                            "<b>Khung thời gian trong bot:</b>\n"
                            "• Mom7 = thay đổi 5 phiên giao dịch (7 ngày)\n"
                            "• Mom30 = thay đổi ~23 phiên giao dịch (30 ngày)\n"
                            "• MA20 &gt; MA50 = xu hướng tăng trung hạn (Golden Cross)\n\n"
                            "📌 Dùng /research để xem cả 5 trường phái đồng thời."
                        ))

                    # ── LEARN: trường phái đầu tư ────────────────────────────
                    elif cmd == "/mpt":
                        tg_send(token, chat_id, (
                            "🎓 <b>MPT — Modern Portfolio Theory</b>\n"
                            "Tác giả: Harry Markowitz (1952, Nobel 1990)\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "Tối đa hóa <b>Sharpe Ratio</b> — lợi nhuận cao nhất trên "
                            "mỗi đơn vị rủi ro. Phân bổ dựa trên hiệp phương sai (correlation) "
                            "giữa các tài sản.\n\n"
                            "<b>Nguyên tắc cốt lõi:</b>\n"
                            "• Đa dạng hóa giảm rủi ro mà không giảm lợi nhuận\n"
                            "• Tài sản ít tương quan nhau → portfolio tốt hơn\n"
                            "• Efficient Frontier: tập hợp portfolio tối ưu\n\n"
                            "<b>Áp dụng với quỹ VN:</b>\n"
                            "Kết hợp quỹ cổ phiếu (return cao, rủi ro cao) + trái phiếu "
                            "(return ổn, rủi ro thấp) + cân bằng. Quỹ cổ phiếu VN thường "
                            "tương quan cao nhau → đa dạng hóa cần cả asset class khác.\n\n"
                            "<b>Hạn chế:</b>\n"
                            "Dựa trên lịch sử quá khứ, không dự đoán được khủng hoảng. "
                            "Khủng hoảng 2008 và COVID 2020 làm tất cả tài sản cùng giảm "
                            "(correlation = 1 trong crisis).\n\n"
                            "📌 Dashboard: thẻ <b>Phân Bổ</b> → chọn <b>Modern Portfolio Theory</b>"
                        ))

                    elif cmd == "/kelly":
                        tg_send(token, chat_id, (
                            "🎓 <b>Kelly Criterion</b>\n"
                            "Tác giả: John L. Kelly Jr. (1956, Bell Labs)\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "Tối đa hóa <i>tăng trưởng log dài hạn</i>. "
                            "Tìm % vốn tối ưu để đặt vào mỗi tài sản.\n\n"
                            "<b>Công thức:</b>\n"
                            "<code>f* = E[R] / Var[R]</code>\n"
                            "E[R] = lợi nhuận kỳ vọng, Var[R] = phương sai\n\n"
                            "<b>Phiên bản thực tế:</b>\n"
                            "• <b>Full Kelly</b>: lý thuyết, rủi ro drawdown cực cao\n"
                            "• <b>Half Kelly</b>: bảo thủ hơn, được dùng phổ biến\n"
                            "• <b>Quarter Kelly</b>: rất bảo thủ, phù hợp khi "
                            "không chắc về input\n\n"
                            "<b>Áp dụng với quỹ VN:</b>\n"
                            "Quỹ có Sharpe cao + biến động thấp → Kelly tự nhiên phân "
                            "bổ nhiều hơn. Thường kết quả: 50–70% trái phiếu + 30–50% "
                            "cổ phiếu cho nhà đầu tư dài hạn VN.\n\n"
                            "<b>⚠️ Cảnh báo:</b>\n"
                            "Full Kelly rất hung hăng — có thể gợi ý 100% vào 1 quỹ. "
                            "Thực tế nên dùng Half Kelly hoặc Quarter Kelly.\n\n"
                            "📌 Dashboard: thẻ <b>Phân Bổ</b> → chọn <b>Kelly Criterion</b>"
                        ))

                    elif cmd == "/riskparity" or cmd == "/rp":
                        tg_send(token, chat_id, (
                            "🎓 <b>Risk Parity — Cân Bằng Rủi Ro</b>\n"
                            "Nổi bật: Ray Dalio / Bridgewater All Weather\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "Mỗi tài sản đóng góp <i>rủi ro bằng nhau</i> vào portfolio, "
                            "không phải <i>vốn bằng nhau</i>. Tài sản biến động ít → "
                            "phân bổ vốn nhiều hơn.\n\n"
                            "<b>Ví dụ:</b>\n"
                            "Quỹ trái phiếu σ=1% vs cổ phiếu σ=5%\n"
                            "→ Risk Parity: 83% trái phiếu + 17% cổ phiếu\n"
                            "→ Equal Weight: 50%/50% (cổ phiếu dominate rủi ro)\n\n"
                            "<b>Phiên bản trong Dashboard:</b>\n"
                            "• Equal Risk Contribution (ERC)\n"
                            "• Volatility-Weighted (đơn giản hơn)\n"
                            "• ATR Risk Budget\n\n"
                            "<b>Áp dụng với quỹ VN:</b>\n"
                            "Phù hợp cho nhà đầu tư bảo thủ muốn tối thiểu hóa drawdown. "
                            "Quỹ cổ phiếu VN biến động σ≈15–20%/năm, quỹ trái phiếu "
                            "σ≈2–4%/năm → Risk Parity tự nhiên nghiêng về trái phiếu.\n\n"
                            "📌 Dashboard: thẻ <b>Phân Bổ</b> → chọn <b>Risk Parity</b>"
                        ))

                    elif cmd == "/valueinvesting" or cmd == "/contrarian":
                        tg_send(token, chat_id, (
                            "🎓 <b>Value / Contrarian Investing</b>\n"
                            "Benjamin Graham, Warren Buffett, David Dreman\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "<i>\"Mua khi người khác sợ hãi, bán khi người khác tham lam\"</i> "
                            "— Warren Buffett\n\n"
                            "Tìm mua tài sản đang bị định giá thấp hơn giá trị thực. "
                            "Đi ngược tâm lý đám đông.\n\n"
                            "<b>Tín hiệu mua theo Value:</b>\n"
                            "• RSI &lt; 33 (quá bán)\n"
                            "• BB% &lt; 20% (gần đáy dải)\n"
                            "• Drawdown 1 năm &gt; 10% từ đỉnh\n"
                            "• NAV dưới MA50\n\n"
                            "<b>Áp dụng với quỹ VN:</b>\n"
                            "Quỹ cổ phiếu VN thường có chu kỳ điều chỉnh 3–6 tháng. "
                            "Mua dần khi drawdown &gt;10% từ đỉnh, tăng tốc khi &gt;20%.\n\n"
                            "<b>Rủi ro:</b>\n"
                            "\"Bẫy giá trị\" (value trap): giá rẻ vì lý do cơ bản xấu, "
                            "không phải vì thị trường sợ hãi. Với quỹ mở VN thì rủi ro "
                            "này thấp hơn cổ phiếu đơn lẻ.\n\n"
                            "📌 /research [MÃ] → trường phái <b>2️⃣ GIÁ TRỊ</b>"
                        ))

                    elif cmd == "/momentuminvesting":
                        tg_send(token, chat_id, (
                            "🎓 <b>Momentum Investing</b>\n"
                            "Jegadeesh &amp; Titman (1993), AQR Capital\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "<i>\"Tài sản đang tăng tiếp tục tăng\"</i> — xu hướng có quán tính. "
                            "Mua những gì đang mạnh, bán những gì đang yếu.\n\n"
                            "<b>Chiến lược trong Dashboard:</b>\n"
                            "• <b>Momentum 1 năm</b>: hiệu quả nhất theo nghiên cứu học thuật\n"
                            "• <b>Momentum 3 tháng</b>: ngắn hạn hơn, phản ứng nhanh hơn\n"
                            "• <b>Dual Momentum</b>: kết hợp 1 năm × 3 tháng — cân bằng\n"
                            "• <b>Mom + Sharpe</b>: ưu tiên quỹ vừa có đà vừa hiệu quả\n\n"
                            "<b>Tín hiệu momentum trong bot:</b>\n"
                            "• Mom30 &gt; +2% + MA20 &gt; MA50 → đà tăng mạnh\n"
                            "• MACD Histogram &gt; 0 → xác nhận đà tăng\n\n"
                            "<b>Hạn chế:</b>\n"
                            "Momentum crash: khi thị trường đảo chiều đột ngột, "
                            "cổ phiếu momentum giảm mạnh nhất. Tháng 3/2020 (COVID) là ví dụ điển hình.\n\n"
                            "📌 /research [MÃ] → trường phái <b>3️⃣ XU HƯỚNG</b>"
                        ))

                    elif cmd == "/dcainvesting":
                        tg_send(token, chat_id, (
                            "🎓 <b>DCA — Dollar-Cost Averaging</b>\n"
                            "Benjamin Graham: <i>The Intelligent Investor</i> (1949)\n"
                            "──────────────────────────\n"
                            "<b>Triết lý:</b>\n"
                            "Đầu tư đều đặn <i>cùng số tiền cố định</i> theo chu kỳ, "
                            "bất kể thị trường lên hay xuống. "
                            "→ Tự động mua nhiều hơn khi giá thấp, ít hơn khi giá cao.\n\n"
                            "<b>Ưu điểm:</b>\n"
                            "• Loại bỏ hoàn toàn rủi ro timing thị trường\n"
                            "• Giảm stress tâm lý — không cần đoán đáy đỉnh\n"
                            "• Phù hợp với thu nhập cố định hàng tháng\n\n"
                            "<b>Intelligent DCA (phiên bản nâng cao):</b>\n"
                            "Tăng mức đầu tư khi tín hiệu thuận lợi:\n"
                            "• NAV dưới MA50 → tăng gấp 1.5× ngân sách\n"
                            "• RSI &lt; 45 → cộng thêm điểm ưu tiên\n"
                            "• Phân bổ thêm vào quỹ có score cao nhất\n\n"
                            "<b>Thực tế VN:</b>\n"
                            "Quỹ mở VN thanh toán T+3 (mua) / T+5 (bán). DCA hàng tháng "
                            "vào đầu tháng là chiến lược phổ biến và hiệu quả dài hạn.\n\n"
                            "📌 /dca setup [ngân_sách] để bot nhắc mỗi tháng\n"
                            "📌 /research [MÃ] → trường phái <b>4️⃣ DCA</b>"
                        ))

                    elif cmd == "/learn":
                        tg_send(token, chat_id, (
                            "📚 <b>LEARN — Từ Điển Đầu Tư</b>\n"
                            "──────────────────────────\n"
                            "<b>📊 Chỉ số kỹ thuật:</b>\n"
                            "/RSI — Relative Strength Index (quá mua/bán)\n"
                            "/MACD — Moving Avg Convergence Divergence (đà)\n"
                            "/BB — Bollinger Bands (vị trí trong biên độ)\n"
                            "/Stoch — Stochastic Oscillator (vị trí trong range)\n"
                            "/ATR — Average True Range (biến động)\n"
                            "/Sharpe — Lợi nhuận/rủi ro\n"
                            "/Momentum — Đà tăng trưởng 7/30 ngày\n\n"
                            "<b>🎓 Trường phái đầu tư:</b>\n"
                            "/MPT — Modern Portfolio Theory (tối ưu hóa Sharpe)\n"
                            "/Kelly — Kelly Criterion (tối đa tăng trưởng log)\n"
                            "/RiskParity — Cân bằng rủi ro bằng nhau (Ray Dalio)\n"
                            "/ValueInvesting — Mua rẻ, đi ngược đám đông\n"
                            "/MomentumInvesting — Theo đà tăng\n"
                            "/DCAInvesting — Đầu tư định kỳ (Graham)\n\n"
                            "<b>🔬 Phân tích nâng cao:</b>\n"
                            "/explain [MÃ] — Giải thích chi tiết tín hiệu quỹ\n"
                            "/research MÃ — Phân tích 5 trường phái đồng thời"
                        ))

                    elif cmd == "/dca":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        parts_dca = text.split()
                        sub = parts_dca[1].lower() if len(parts_dca) > 1 else ""

                        if sub == "setup":
                            # /dca setup 10000000
                            if len(parts_dca) < 3:
                                tg_send(token, chat_id, (
                                    "❓ Cú pháp: <code>/dca setup [ngân_sách_tháng]</code>\n"
                                    "Ví dụ: <code>/dca setup 10000000</code>\n\n"
                                    "Bot sẽ nhắc phân bổ DCA vào ngày 1 mỗi tháng."
                                ))
                                continue
                            try:
                                dca_budget = float(parts_dca[2].replace(",", "").replace(".", ""))
                                if dca_budget <= 0:
                                    raise ValueError
                            except ValueError:
                                tg_send(token, chat_id, "⚠️ Ngân sách phải là số dương. Ví dụ: <code>/dca setup 10000000</code>")
                                continue
                            cfg_dca = load_config()
                            for p in cfg_dca.get("profiles", []):
                                if str(p.get("telegram_id")) == chat_id:
                                    p["monthly_dca"] = int(dca_budget)
                                    break
                            save_config(cfg_dca)
                            tg_send(token, chat_id, (
                                f"✅ Đã lưu ngân sách DCA: <b>{int(dca_budget):,}đ/tháng</b>\n\n"
                                f"Bot sẽ gửi gợi ý phân bổ vào ngày 1 mỗi tháng.\n"
                                f"Gõ <code>/dca</code> để xem gợi ý ngay."
                            ))

                        elif sub == "off":
                            cfg_dca = load_config()
                            for p in cfg_dca.get("profiles", []):
                                if str(p.get("telegram_id")) == chat_id:
                                    p.pop("monthly_dca", None)
                                    break
                            save_config(cfg_dca)
                            tg_send(token, chat_id, "✅ Đã tắt nhắc nhở DCA hàng tháng.")

                        else:
                            # /dca [AMOUNT] hoặc /dca (dùng monthly_dca)
                            dca_budget = None
                            if sub and sub.replace(",", "").replace(".", "").isdigit():
                                dca_budget = float(sub.replace(",", "").replace(".", ""))
                            elif len(parts_dca) > 1:
                                try:
                                    dca_budget = float(parts_dca[1].replace(",", "").replace(".", ""))
                                except ValueError:
                                    pass
                            if not dca_budget:
                                dca_budget = float(profile.get("monthly_dca", 0))
                            if not dca_budget:
                                tg_send(token, chat_id, (
                                    "❓ <b>DCA — Đầu tư định kỳ theo tín hiệu</b>\n\n"
                                    "Gõ <code>/dca [số_tiền]</code> để xem gợi ý phân bổ ngay.\n"
                                    "Gõ <code>/dca setup 10000000</code> để lưu ngân sách tháng.\n\n"
                                    "Ví dụ: <code>/dca 5000000</code>\n"
                                    "Gợi ý: <code>/dca off</code> — tắt nhắc nhở hàng tháng"
                                ))
                                continue
                            codes_dca = set(profile.get("watched_funds", []))
                            nav_data_dca = fetch_all(config, codes_dca)
                            tg_send(token, chat_id, msg_dca_suggest(profile, nav_data_dca, dca_budget))

                    elif cmd == "/funds":
                        cfg_funds = config.get("funds", {})
                        lines = ["📋 <b>Danh Sách Quỹ Có Thể Theo Dõi</b>", LINE]
                        for code, info in sorted(cfg_funds.items()):
                            src = "TCBS" if info.get("tcbs") else "fmarket"
                            lines.append(f"• <code>{code}</code> — {info.get('name', '')}  <i>({src})</i>")
                        lines.append(LINE)
                        if profile:
                            lines.append(f"📌 Quỹ bạn đang theo: <code>{', '.join(profile.get('watched_funds', []))}</code>")
                            lines.append("💡 <code>/watch TCBF SSISCA</code> — thêm · <code>/unwatch TCBF</code> — bỏ")
                        else:
                            lines.append("⚠️ Gõ /register để đăng ký trước khi theo dõi quỹ.")
                        tg_send(token, chat_id, "\n".join(lines))

                    elif cmd == "/watch":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        parts_w = text.split()[1:]
                        if not parts_w:
                            tg_send(token, chat_id, "❓ Cú pháp: <code>/watch TCBF SSISCA</code>")
                            continue
                        cfg_funds = config.get("funds", {})
                        current   = set(profile.get("watched_funds", []))
                        added, invalid = [], []
                        for code in [p.upper() for p in parts_w]:
                            if code not in cfg_funds:
                                invalid.append(code)
                            elif code not in current:
                                added.append(code)
                                current.add(code)
                        if added:
                            cfg_w = load_config()
                            for p in cfg_w.get("profiles", []):
                                if str(p.get("telegram_id")) == chat_id:
                                    p["watched_funds"] = sorted(current)
                                    break
                            save_config(cfg_w)
                        lines = []
                        if added:
                            lines.append(f"✅ Đã thêm: <code>{', '.join(added)}</code>")
                        if invalid:
                            lines.append(f"⚠️ Không tìm thấy: <code>{', '.join(invalid)}</code> — Gõ /funds để xem danh sách")
                        if not added and not invalid:
                            lines.append("ℹ️ Các quỹ này đã có trong danh mục của bạn rồi.")
                        lines.append(f"📋 Danh mục hiện tại: <code>{', '.join(sorted(current))}</code>")
                        tg_send(token, chat_id, "\n".join(lines))

                    elif cmd == "/unwatch":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        parts_u = text.split()[1:]
                        if not parts_u:
                            tg_send(token, chat_id, "❓ Cú pháp: <code>/unwatch TCBF</code>")
                            continue
                        current    = set(profile.get("watched_funds", []))
                        removed, not_found = [], []
                        for code in [p.upper() for p in parts_u]:
                            if code in current:
                                removed.append(code)
                                current.discard(code)
                            else:
                                not_found.append(code)
                        if not current:
                            tg_send(token, chat_id, "⚠️ Cần giữ ít nhất 1 quỹ trong danh mục.")
                            continue
                        if removed:
                            cfg_w = load_config()
                            for p in cfg_w.get("profiles", []):
                                if str(p.get("telegram_id")) == chat_id:
                                    p["watched_funds"] = sorted(current)
                                    break
                            save_config(cfg_w)
                        lines = []
                        if removed:
                            lines.append(f"✅ Đã bỏ: <code>{', '.join(removed)}</code>")
                        if not_found:
                            lines.append(f"⚠️ Không có trong danh mục: <code>{', '.join(not_found)}</code>")
                        lines.append(f"📋 Danh mục còn lại: <code>{', '.join(sorted(current))}</code>")
                        tg_send(token, chat_id, "\n".join(lines))

                    elif cmd == "/admin":
                        admin_id = str(config.get("admin_telegram_id", "")).strip()
                        if not admin_id or chat_id != admin_id:
                            tg_send(token, chat_id, "⛔ Lệnh chỉ dành cho admin.")
                            continue
                        sub = text.split()[1].lower() if len(text.split()) > 1 else ""
                        if sub == "users":
                            profiles_list = config.get("profiles", [])
                            if not profiles_list:
                                tg_send(token, chat_id, "📭 Chưa có user nào đăng ký.")
                            else:
                                lines = [f"👥 <b>Danh sách {len(profiles_list)} users:</b>", LINE]
                                for i, p in enumerate(profiles_list, 1):
                                    lines.append(
                                        f"{i}. <b>{p['name']}</b> — <code>{p.get('telegram_id','?')}</code>\n"
                                        f"   Quỹ: {', '.join(p.get('watched_funds', []))}"
                                    )
                                tg_send(token, chat_id, "\n".join(lines))
                        elif sub == "kick" and len(text.split()) > 2:
                            target_id = text.split()[2]
                            cfg_w = load_config()
                            before = len(cfg_w.get("profiles", []))
                            cfg_w["profiles"] = [p for p in cfg_w.get("profiles", []) if str(p.get("telegram_id")) != target_id]
                            if len(cfg_w["profiles"]) < before:
                                save_config(cfg_w)
                                tg_send(token, chat_id, f"✅ Đã xóa profile <code>{target_id}</code>")
                            else:
                                tg_send(token, chat_id, f"⚠️ Không tìm thấy <code>{target_id}</code>")
                        elif sub == "broadcast" and len(text.split()) > 2:
                            bcast_msg = " ".join(text.split()[2:])
                            sent_count = 0
                            for p in config.get("profiles", []):
                                tg = str(p.get("telegram_id", ""))
                                if tg.lstrip("-").isdigit():
                                    if tg_send(token, tg, f"📢 <b>Thông báo</b>\n\n{bcast_msg}"):
                                        sent_count += 1
                            tg_send(token, chat_id, f"✅ Đã gửi tới {sent_count} users")
                        else:
                            tg_send(token, chat_id, (
                                "🔧 <b>Admin Commands</b>\n\n"
                                "<code>/admin users</code> — Xem tất cả users\n"
                                "<code>/admin kick CHATID</code> — Xóa user\n"
                                "<code>/admin broadcast TIN NHẮN</code> — Broadcast tới tất cả\n"
                            ))

                    elif cmd == "/morning":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                        tg_send(token, chat_id, msg_morning(profile, nav_data))

                    elif cmd == "/evening":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để tự đăng ký.")
                            continue
                        nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                        state    = load_state()
                        tg_send(token, chat_id, msg_evening(profile, nav_data, state.get("morning_nav", {})))

                    elif cmd == "/otp":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để đăng ký.")
                            continue
                        _cmd_otp(token, chat_id, parts, profile)

                    else:
                        if text.startswith("/"):
                            tg_send(token, chat_id, f"❓ Lệnh <code>{cmd}</code> không tồn tại. Gõ /help để xem danh sách.")

                except Exception as _cmd_exc:
                    log.error("[CMD ERROR] %r %s: %s", cmd, chat_id, _cmd_exc, exc_info=True)
                    try:
                        tg_send(token, chat_id, f"⚠ Lỗi xử lý lệnh <code>{cmd}</code>. Vui lòng thử lại sau.")
                    except Exception:
                        pass
        except KeyboardInterrupt:
            log.info("Command handler stopped.")
            break
        except Exception as e:
            log.error(f"[command_handler] {e}")
            time.sleep(10)


# ═══════════════════════════════════════
# MAIN
# ═══════════════════════════════════════

def main():
    log.info("══════════════════════════════════")
    log.info("  Quỹ Tracker Bot v2.0  —  Start ")
    log.info("══════════════════════════════════")
    log.info(f"  DATA_DIR: {DATA_DIR}")

    _ensure_config_exists()  # Tạo config từ ENV nếu chạy lần đầu trên cloud

    # Bridge database_url từ config.json sang ENV (db.py chỉ đọc DATABASE_URL env).
    # Đảm bảo DB fallback (nav_history) hoạt động kể cả khi Railway không tự inject env.
    if not os.environ.get("DATABASE_URL"):
        _db_url = load_config().get("database_url", "")
        if _db_url:
            os.environ["DATABASE_URL"] = _db_url
            log.info("[DB] DATABASE_URL nạp từ config.json")

    if _DB_AVAILABLE:
        _db.init_pool()
        log.info(f"[DB] PostgreSQL available={_db.is_available()}")
    else:
        log.warning("db.py không khả dụng — PostgreSQL bị bỏ qua")

    if not CONFIG_FILE.exists():
        log.error(f"Không tìm thấy {CONFIG_FILE}. Hãy copy config.example.json → config.json và điền thông tin.")
        log.error("Hoặc set ENV: BOT_TOKEN=... để tự tạo config khi deploy lên cloud.")
        return

    config = load_config()
    # Reconcile profile admin (Harvey): đảm bảo đủ 5 quỹ + portfolio trên /data volume
    if reconcile_admin_profile(config):
        save_config(config)
        log.info("[reconcile] config.json đã cập nhật profile admin")
    sched  = config.get("schedule", {})
    t_morn = sched.get("morning_report", "08:00")
    t_eve  = sched.get("evening_report", "17:30")
    t_int  = int(sched.get("signal_check_interval_minutes", 60))

    log.info(f"Lịch: sáng={t_morn}, chiều={t_eve}, signal_check={t_int}m")
    log.info(f"Profiles: {[p['name'] for p in config.get('profiles', [])]}")
    log.info(f"Tất cả quỹ theo dõi: {sorted(all_watched_codes(config))}")

    for day in (schedule.every().monday, schedule.every().tuesday,
                schedule.every().wednesday, schedule.every().thursday,
                schedule.every().friday):
        day.at(t_morn).do(job_morning)
        day.at(t_eve).do(job_evening)

    schedule.every(t_int).minutes.do(job_check_signals)
    schedule.every(t_int).minutes.do(job_nav_change_alert)
    schedule.every(30).minutes.do(job_check_jwt)
    schedule.every().day.at("09:00").do(job_backfill_settlement)
    schedule.every().day.at("09:00").do(job_dca_reminder)
    schedule.every().day.at("18:30").do(job_harvest_nav)
    schedule.every().day.at("00:01").do(job_watchdog_ping)

    log.info("Chạy signal check khởi động...")
    job_check_signals()

    t = threading.Thread(target=command_handler, daemon=True, name="cmd-handler")
    t.start()
    log.info("Command handler (long-polling) đã khởi động.")

    log.info("Bot đang chạy. Nhấn Ctrl+C để dừng.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        log.info("Bot dừng.")


if __name__ == "__main__":
    main()
