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


def load_config() -> dict:
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
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
            "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",          "fmarket_id": 22},
            "TCFF":    {"name": "Quỹ Linh Hoạt Techcombank",            "fmarket_id": None, "tcbs": True},
            "TCGF":    {"name": "Quỹ Tăng Trưởng Techcombank",          "fmarket_id": None, "tcbs": True},
            "VCBFTBF": {"name": "Quỹ TPDN Có Bảo Đảm VCB Fund",        "fmarket_id": 31},
            "VCBFBCF": {"name": "Quỹ Trái Phiếu Bền Vững VCB Fund",    "fmarket_id": 32},
            "VCBFEF":  {"name": "Quỹ Cổ Phiếu Việt Nam VCB Fund",      "fmarket_id": 28},
            "SSISCA":  {"name": "Quỹ Tích Lũy Bền Vững SSI",           "fmarket_id": 11},
            "MAFPF1":  {"name": "Quỹ Tích Lũy Hưu Trí Manulife",       "fmarket_id": 45},
            "MAFEQI":  {"name": "Quỹ Cổ Phiếu Manulife",               "fmarket_id": 34},
            "MBBF":    {"name": "Quỹ Trái Phiếu MB Capital",            "fmarket_id": 40},
            "MBVF":    {"name": "Quỹ Cổ Phiếu MB Capital",             "fmarket_id": 35},
            "ESSCF":   {"name": "Quỹ Cổ Phiếu Eastspring VN",          "fmarket_id": 47},
            "ESBF":    {"name": "Quỹ Trái Phiếu Eastspring VN",        "fmarket_id": 46},
            "BVPF":    {"name": "Quỹ Tăng Trưởng Bảo Việt",            "fmarket_id": 20},
            "MIRAEF":  {"name": "Quỹ Cổ Phiếu Mirae Asset VN",         "fmarket_id": 38},
            "VNDAF":   {"name": "Quỹ Cổ Phiếu Năng Động VinaCapital",  "fmarket_id": 1},
            "VNDBF":   {"name": "Quỹ Trái Phiếu VinaCapital",          "fmarket_id": 2},
            "DCDS":    {"name": "Quỹ Tăng Trưởng Dragon Capital",       "fmarket_id": 6},
            "DCBF":    {"name": "Quỹ Trái Phiếu Dragon Capital",        "fmarket_id": 5},
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
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


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


def fetch_tcbs(code: str, token: str = "", from_date: str = None) -> list:
    """Fetch lịch sử NAV từ TCBS.
    from_date: "yyyy-mm-dd" — nếu không truyền, mặc định 2023-01-01 (lấy toàn bộ).
               Truyền HIST cutoff để chỉ lấy delta mới hơn → tiết kiệm băng thông.
    """
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
                # Token hết hạn — đánh dấu để job gửi cảnh báo, không thử URL thứ 2
                log.warning(f"[TCBS] {code} HTTP {r.status_code} — Token hết hạn hoặc không hợp lệ")
                _tcbs_auth_fail_codes.add(code)
                break
            elif not r.ok:
                log.warning(f"[TCBS] {code} HTTP {r.status_code}")
                continue
            data = r.json()
            navs = data.get("data") or data.get("navHistory") or data.get("list") or []
            pts = []
            for n in navs:
                d = (n.get("navDate") or n.get("tradingDate") or n.get("date") or "")[:10]
                v = float(n.get("nav") or n.get("navValue") or n.get("close") or 0)
                if d and v > 0:
                    pts.append({"date": d, "nav": v})
            if pts:
                last = sorted(pts, key=lambda x: x["date"])[-1]
                log.info(f"[TCBS] ✓ {code}: {len(pts)} pts, last={last['date']}")
                return sorted(pts, key=lambda x: x["date"])
        except Exception as e:
            log.warning(f"[TCBS] {code} {url}: {e}")
    return []


def get_nav_series(code: str, fund_cfg: dict, config: dict = None) -> list:
    fid = fund_cfg.get("fmarket_id")
    pts = fetch_fmarket(fid) if fid else []
    if not pts and fund_cfg.get("tcbs"):
        tcbs_token = (config or {}).get("tcbs_token", "")
        # Truyền from_date để chỉ fetch từ HIST cutoff → tiết kiệm băng thông
        cutoff = _HIST_CUTOFF.get(code, None)
        log.info(f"[TCBS fallback] {code} from_date={cutoff} (token={'yes' if tcbs_token else 'no'})")
        pts = fetch_tcbs(code, tcbs_token, from_date=cutoff)
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
        ma_note = "MA20 > MA50 ↑" if d.get("ma20") and d.get("ma50") and d["ma20"] > d["ma50"] else "MA20 < MA50 ↓"
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
        f"Các quỹ không cập nhật được NAV: <code>{codes_str}</code>\n\n"
        f"👉 <b>Cách lấy token mới:</b>\n"
        f"1. Mở Dashboard → Cài Đặt → TCBS Auth\n"
        f"2. Nhập số điện thoại → Gửi OTP\n"
        f"3. Nhập OTP → Xác nhận\n\n"
        f"<code>http://localhost:8080/Quy%20Tracker%20Dashboard.html</code>"
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
            f"👉 Vào Dashboard → Cài Đặt → TCBS Auth để lấy token mới.\n"
            f"<code>http://localhost:8080/Quy%20Tracker%20Dashboard.html</code>"
        )
    else:
        mins = remaining // 60
        log.warning(f"[JWT-CHECK] TCBS token sắp hết hạn! Còn {mins} phút.")
        msg = (
            f"⚠️ <b>TCBS Token sắp hết hạn!</b>\n"
            f"Còn <b>{mins} phút</b>.\n\n"
            f"👉 Vào Dashboard → Cài Đặt → TCBS Auth để gia hạn ngay.\n"
            f"<code>http://localhost:8080/Quy%20Tracker%20Dashboard.html</code>"
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
# TELEGRAM COMMAND HANDLER (long-polling)
# ═══════════════════════════════════════

def find_profile_by_chat(config: dict, chat_id: str) -> Optional[dict]:
    for p in config.get("profiles", []):
        tg = str(p.get("telegram_id", "")).strip().lstrip("@")
        if tg and tg == chat_id.strip().lstrip("@"):
            return p
    return None


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
                cmd     = text.split()[0].lower().split("@")[0] if text else ""
                log.info(f"[CMD] {cmd!r} from chat {chat_id}")
                profile = find_profile_by_chat(config, chat_id)

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
                    tg_send(token, chat_id, (
                        "👋 <b>Quỹ Tracker Pro Bot</b>\n\n"
                        "<b>Theo dõi NAV:</b>\n"
                        "📈 /nav — NAV hiện tại + tín hiệu\n"
                        "📊 /signal — Tín hiệu kỹ thuật (RSI, BB, MACD)\n"
                        "🔍 /explain [MÃ] — Phân tích chi tiết\n"
                        "🗂 /portfolio — Danh mục + P&amp;L\n\n"
                        "<b>Quản lý danh mục:</b>\n"
                        "📋 /funds — Xem tất cả quỹ có thể theo dõi\n"
                        "➕ /watch TCBF SSISCA — Thêm quỹ vào danh mục\n"
                        "➖ /unwatch TCBF — Bỏ quỹ khỏi danh mục\n\n"
                        "<b>Báo cáo:</b>\n"
                        "🌅 /morning — Báo cáo sáng (ngay bây giờ)\n"
                        "🌆 /evening — Báo cáo chiều (ngay bây giờ)\n\n"
                        "<b>Tài khoản:</b>\n"
                        "🪪 /getid — Xem Chat ID của bạn\n"
                        "✍️ /register [tên] — Tự đăng ký nhận báo cáo\n"
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
                    nav_data = fetch_all(config, set(profile.get("watched_funds", [])))
                    tg_send(token, chat_id, msg_portfolio(profile, nav_data))

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

                else:
                    if text.startswith("/"):
                        tg_send(token, chat_id, f"❓ Lệnh <code>{cmd}</code> không tồn tại. Gõ /help để xem danh sách.")

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

    if _DB_AVAILABLE:
        _db.init_pool()
    else:
        log.warning("db.py không khả dụng — PostgreSQL bị bỏ qua")

    if not CONFIG_FILE.exists():
        log.error(f"Không tìm thấy {CONFIG_FILE}. Hãy copy config.example.json → config.json và điền thông tin.")
        log.error("Hoặc set ENV: BOT_TOKEN=... để tự tạo config khi deploy lên cloud.")
        return

    config = load_config()
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
    schedule.every(30).minutes.do(job_check_jwt)
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
