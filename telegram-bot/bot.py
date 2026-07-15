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
║  Lệnh:  /register  /app  /admin  /help              ║
║  (Tất cả tính năng khác đã chuyển vào Mini App)      ║
╚══════════════════════════════════════════════════════╝
"""

import json
import math
import os
import subprocess
import sys
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
_tcbs_auth_notified: bool = False  # True sau khi đã notify; reset khi token hoạt động lại


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
        ("DATABASE_URL",      "database_url"),
        ("TCBS_TOKEN",        "tcbs_token"),
    ]:
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    return cfg


FUND_CATALOG: dict = {
    "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",              "fmarket_id": None, "tcbs": True},
    "TCFF":    {"name": "Quỹ Tăng Trưởng Techcombank",             "fmarket_id": None, "tcbs": True},
    "TCGF":    {"name": "Quỹ Tăng Trưởng Toàn Cầu Techcombank",   "fmarket_id": None, "tcbs": True},
    "TCSME":   {"name": "Quỹ Cổ Phiếu SME Techcombank",            "fmarket_id": None, "tcbs": True},
    "TCEF":    {"name": "Quỹ Cổ Phiếu Techcombank",                "fmarket_id": None, "tcbs": True},
    "TCRES":   {"name": "Quỹ Bất Động Sản Techcombank",            "fmarket_id": None, "tcbs": True},
    "TCFIN":   {"name": "Quỹ Tài Chính Techcombank",               "fmarket_id": None, "tcbs": True},
    # fmarket_id=31 (cũ) trỏ NHẦM sang 1 quỹ trái phiếu khác (~30.000đ) — VCBF-TBF
    # thật là quỹ CÂN BẰNG (50% cổ phiếu/50% TP, theo fmarket.vn/quy/VCBFTBF và
    # vcbs.com.vn) với NAV thật ~38.000-39.000đ (khớp TCinvest). Bug này khiến
    # nav_history bị 2 nguồn ghi đè lẫn nhau, tạo dao động giả ~23%/ngày —
    # phát hiện qua vol_30d bất thường khi debug DCA riskparity (2026-07-14).
    "VCBFTBF": {"name": "Quỹ Đầu Tư Cân Bằng Chiến Lược VCBF",     "fmarket_id": None, "tcbs": True},
    "VCBFBCF": {"name": "Quỹ Trái Phiếu Bền Vững VCB Fund",       "fmarket_id": 32,   "tcbs": True},
    "VCBFFIF": {"name": "Quỹ Thu Nhập Cố Định VCB Fund",           "fmarket_id": 33,   "tcbs": True},
    "VCBFMGF": {"name": "Quỹ Tăng Trưởng VCB Fund",               "fmarket_id": None, "tcbs": True},
    "VCBFAIF": {"name": "Quỹ Cổ Phiếu VCB Fund",                  "fmarket_id": 82,   "tcbs": True},
    "VCAMDF":  {"name": "Quỹ Bản Việt Discovery (VCAM)",          "fmarket_id": 75,   "tcbs": True},
    "VCAMBF":  {"name": "Quỹ Cân Bằng Bản Việt (VCAM)",          "fmarket_id": 70,   "tcbs": True},
    "SSISCA":  {"name": "Quỹ Tích Lũy Bền Vững SSI",              "fmarket_id": 11,   "tcbs": True},
    "VDEF":    {"name": "Quỹ Cổ Phiếu Tiên Phong VinaCapital",   "fmarket_id": 80,   "tcbs": True},
    "VEOF":    {"name": "Quỹ Cổ Phiếu Doanh Nghiệp Hàng Đầu VF", "fmarket_id": 20,   "tcbs": True},
    "VESAF":   {"name": "Quỹ Cổ Phiếu Tăng Trưởng VinaCapital",  "fmarket_id": 23,   "tcbs": True},
    "VIBF":    {"name": "Quỹ Cân Bằng Gắn Kết VinaCapital",      "fmarket_id": 22,   "tcbs": True},
    "VMEEF":   {"name": "Quỹ Cổ Phiếu Kinh Tế Hiện Đại VF",      "fmarket_id": 68,   "tcbs": True},
    "VMPF":    {"name": "Quỹ Cổ Phiếu VietFund Emerging (mã cũ)", "fmarket_id": None, "tcbs": True},
    "UVDIF":   {"name": "Quỹ Thu Nhập Năng Động UOB",             "fmarket_id": 78,   "tcbs": True},
    "UVEEF":   {"name": "Quỹ Cổ Phiếu ESG UOB",                  "fmarket_id": 58,   "tcbs": True},
    "DCAF":    {"name": "Quỹ Tăng Trưởng DFVN",                   "fmarket_id": 29,   "tcbs": True},
    "DCDE":    {"name": "Quỹ Cổ Phiếu Cổ Tức Dragon Capital",    "fmarket_id": 25,   "tcbs": True},
    "DCDS":    {"name": "Quỹ Chứng Khoán Năng Động Dragon Capital", "fmarket_id": 28,  "tcbs": True},
    "DFIX":    {"name": "Quỹ Trái Phiếu DFVN",                    "fmarket_id": 30,   "tcbs": True},
    "KDEF":    {"name": "Quỹ Cổ Phiếu Cổ Tức KIM",               "fmarket_id": 86,   "tcbs": True},
    "LHCDF":   {"name": "Quỹ Năng Động Lighthouse",               "fmarket_id": 76,   "tcbs": True},
    "MAGEF":   {"name": "Quỹ Cổ Phiếu Manulife",                  "fmarket_id": None, "tcbs": True},
    "PHVSF":   {"name": "Quỹ Chọn Lọc Phú Hưng VN",              "fmarket_id": 66,   "tcbs": True},
    "NTPPF":   {"name": "Quỹ Cổ Phiếu Triển Vọng NTP",           "fmarket_id": 52,   "tcbs": True},
    "TVPF":    {"name": "Quỹ Cổ Phiếu NTP (mã cũ)",              "fmarket_id": None, "tcbs": True},
    "MAFPF1":  {"name": "Quỹ Tích Lũy Hưu Trí Manulife",          "fmarket_id": 45},
    "MBBF":    {"name": "Quỹ Trái Phiếu MB Capital",              "fmarket_id": 40},
    "MBVF":    {"name": "Quỹ Cổ Phiếu MB Capital",               "fmarket_id": 35},
    "ESSCF":   {"name": "Quỹ Cổ Phiếu Eastspring VN",            "fmarket_id": 47},
    "ESBF":    {"name": "Quỹ Trái Phiếu Eastspring VN",          "fmarket_id": 46},
    "BVPF":    {"name": "Quỹ Cổ Phiếu Triển Vọng Bảo Việt",     "fmarket_id": 14},
    "MIRAEF":  {"name": "Quỹ Cổ Phiếu Mirae Asset VN",           "fmarket_id": 38},
    "VNDAF":   {"name": "Quỹ Cổ Phiếu Năng Động VinaCapital",    "fmarket_id": None},
    "VNDBF":   {"name": "Quỹ Trái Phiếu VND",                    "fmarket_id": 37},
}


def _ensure_config_exists():
    """Tạo config.json tối thiểu từ ENV nếu chưa có (first-run trên cloud).

    CẢNH BÁO: nếu dòng log "[BOOTSTRAP]" xuất hiện SAU LẦN CHẠY ĐẦU TIÊN
    (tức là bot đã từng có config.json với users đã đăng ký), điều đó có
    nghĩa là Railway volume /data KHÔNG persistent — mỗi lần redeploy sẽ
    mất toàn bộ profiles (users đăng ký qua /register) + tcbs_token đã lưu.
    → Kiểm tra Railway Dashboard → Volumes → đảm bảo có volume mount tại /data.
    """
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
        "funds": FUND_CATALOG,
        "schedule": {
            "morning_report":               os.environ.get("MORNING_TIME", "08:00"),
            "evening_report":               os.environ.get("EVENING_TIME", "17:30"),
            "signal_check_interval_minutes": int(os.environ.get("SIGNAL_INTERVAL", "60")),
        },
    }
    save_config(cfg)
    log.warning(
        f"[BOOTSTRAP] ⚠️ config.json KHÔNG TỒN TẠI tại {CONFIG_FILE} — đã tạo mới rỗng "
        f"(admin={cfg['admin_telegram_id']}). Nếu đây không phải lần deploy đầu tiên, "
        f"volume /data đã bị mất dữ liệu — TẤT CẢ profiles đã đăng ký (vd: /register) "
        f"và tcbs_token đã lưu đều bị XÓA. Kiểm tra Railway Volumes ngay."
    )


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


def _tcbs_expiry_notify_key(token: str) -> str:
    """Hash ngắn của token — dùng làm key dedup, không lưu token thô vào state.json."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else ""


def _already_notified_token_expired(token: str) -> bool:
    """True nếu đã gửi cảnh báo 'token hết hạn' cho ĐÚNG token này rồi (kể cả sau khi bot restart).
    Lưu vào state.json (persisted) thay vì biến global trong RAM, vì bot có thể restart
    (Railway) giữa 2 lần kiểm tra khác nhau (fetch trực tiếp vs job cron) — trước đây mỗi
    đường đều tự dedup bằng RAM riêng nên khi restart lại gửi trùng cảnh báo."""
    return load_state().get("tcbs_expired_notified_key") == _tcbs_expiry_notify_key(token)


def _mark_token_expired_notified(token: str):
    state = load_state()
    state["tcbs_expired_notified_key"] = _tcbs_expiry_notify_key(token)
    save_state(state)


def _clear_token_expired_notified():
    state = load_state()
    if "tcbs_expired_notified_key" in state:
        del state["tcbs_expired_notified_key"]
        save_state(state)


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
                last_pt = pts[-1]
                today_str = date.today().isoformat()
                label = f"{code} → alias {try_code}" if try_code != code else code
                if last_pt["date"] < today_str:
                    # NAV chưa publish hôm nay — log rõ để debug delay
                    log.warning(
                        f"[TCinvest] {label}: latest={last_pt['date']} nav={last_pt['nav']:.0f}"
                        f" (today={today_str}, DELAY {(date.fromisoformat(today_str)-date.fromisoformat(last_pt['date'])).days}d)"
                    )
                else:
                    log.info(f"[TCinvest] {label}: {len(pts)} pts, last={last_pt['date']} nav={last_pt['nav']:.0f}")
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
    """Trả về list điểm NAV (không kèm source — dùng cho hiển thị/tính tín hiệu).
    Dùng get_nav_series_with_source() nếu cần biết nguồn để ghi DB đúng."""
    pts, _src = get_nav_series_with_source(code, fund_cfg, config)
    return pts


# Khớp với các nguồn upsert_nav() (db.py) coi là "đã khóa cứng" — fetch lại
# cũng không ghi đè được, nên khỏi tốn API call/băng thông. (fmarket/TCinvest
# đều không hỗ trợ giới hạn khoảng ngày ở server — luôn trả full history mỗi
# lần gọi — nên đòn bẩy duy nhất để "không fetch ngày đã khóa" là bỏ qua CUỘC
# GỌI API luôn khi hôm nay đã khóa, không phải lọc bớt ngày trong response.)
_LOCKED_SOURCES = ('fixed', 'manual', 'tcinvest')


def get_nav_series_with_source(code: str, fund_cfg: dict, config: dict = None) -> tuple:
    """GOV-007 (2026-07-14): TCinvest là nguồn CHUẨN — luôn thử trước fmarket.
    Trước đây fmarket được thử TRƯỚC bất kể quỹ có JWT TCinvest hay không, nên
    1 fmarket_id cấu hình sai (vụ VCBFTBF) đã âm thầm ghi đè NAV đúng từ TCinvest
    mỗi lần job chạy — vì hàm gọi upsert_nav() không hề biết dữ liệu thật sự đến
    từ đâu, chỉ đoán theo fund_cfg tĩnh. Trả kèm source thật để caller ghi DB
    đúng nguồn (xem fetch_all()).

    Tránh xung đột thêm 1 bước: nếu NAV hôm nay trong DB đã khóa cứng rồi
    (fixed/manual/tcinvest), bỏ qua fetch live hoàn toàn — không có lý do gì
    gọi lại API chỉ để bị chặn ghi ở tầng DB, vừa tốn quota vừa tăng rủi ro."""
    db_pts = []
    if _DB_AVAILABLE and _db.is_available():
        try:
            rows = _db.get_nav_series(code, days=400)  # đủ cho RSI/MACD/BB
            db_pts = sorted(
                ({"date": r["nav_date"].isoformat(), "nav": float(r["nav"]), "source": r.get("source")}
                 for r in rows),
                key=lambda x: x["date"],
            )
        except Exception as e:
            log.warning(f"[Nav] {code} đọc DB lỗi: {e}")

    today_str = date.today().isoformat()
    if db_pts and db_pts[-1]["date"] == today_str and db_pts[-1].get("source") in _LOCKED_SOURCES:
        log.debug(f"[Nav] {code} hôm nay đã khóa (source={db_pts[-1]['source']}) — bỏ qua fetch")
        return [{"date": p["date"], "nav": p["nav"]} for p in db_pts], None

    pts, source = [], None
    if fund_cfg.get("tcbs"):
        tcbs_token = os.environ.get("TCBS_TOKEN") or (config or {}).get("tcbs_token", "")
        log.info(f"[Nav] {code} fetch full history (token={'yes' if tcbs_token else 'no'})")
        pts = fetch_tcbs(code, tcbs_token)
        if pts:
            source = "tcinvest"
    if not pts:
        fid = fund_cfg.get("fmarket_id")
        if fid:
            pts = fetch_fmarket(fid)
            if pts:
                source = "fmarket"
    # Fallback cuối: fetch live thất bại nhưng đã có sẵn history trong DB
    # — giúp quỹ TCinvest-only (vd TCFF) vẫn hiển thị khi token hết hạn.
    if not pts and db_pts:
        pts = [{"date": p["date"], "nav": p["nav"]} for p in db_pts]
        log.info(f"[Nav] {code} fallback DB nav_history: {len(pts)} điểm")
        source = None  # đã có sẵn trong DB rồi, không cần ghi lại

    # GOV-011 (2026-07-15, Harvey phát hiện SSISCA hiện NAV 14/7 dù DB đã có NAV
    # 15/7): pts fetch live (tcbs/fmarket) có thể CHƯA có NAV hôm nay dù DB đã có
    # sẵn — vd TCinvest công bố trễ hơn fmarket, hoặc script/admin khác đã ghi
    # NAV hôm nay trước khi job này chạy (đúng tình huống vừa xảy ra: harvest_nav
    # --daily ghi NAV 15/7 nguồn fmarket, nhưng job fetch live sau đó gọi lại
    # TCBS — TCBS chưa publish 15/7 nên trả về pts chỉ tới 14/7, âm thầm "lùi"
    # NAV hiển thị). Tín hiệu PHẢI luôn ưu tiên NGÀY MỚI NHẤT bất kể nguồn nào
    # "đáng tin" hơn — merge thêm điểm mới nhất từ DB nếu nó mới hơn pts vừa fetch,
    # và bỏ qua ghi lại (source=None) để không mất nhãn nguồn thật đã lưu đúng.
    if pts and db_pts and db_pts[-1]["date"] > pts[-1]["date"]:
        log.info(f"[Nav] {code} DB đã có NAV mới hơn ({db_pts[-1]['date']}) so với "
                 f"fetch live ({pts[-1]['date']}) — merge, không ghi đè lại")
        pts_by_date = {p["date"]: p for p in pts}
        for p in db_pts:
            pts_by_date.setdefault(p["date"], p)
        pts = sorted(pts_by_date.values(), key=lambda x: x["date"])
        source = None

    return pts, source


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


def calc_cci(navs: list, period: int = 20) -> Optional[float]:
    """Commodity Channel Index — dùng NAV thay Typical Price cho quỹ mở.

    CCI > 100: quá mua. CCI < -100: quá bán.
    """
    if len(navs) < period:
        return None
    window = navs[-period:]
    sma = _avg(window)
    mean_dev = _avg([abs(v - sma) for v in window])
    if mean_dev == 0:
        return None
    return round((navs[-1] - sma) / (0.015 * mean_dev), 1)


def calc_roc(navs: list, period: int = 10) -> Optional[float]:
    """Rate of Change (%) — đo momentum {period} ngày."""
    if len(navs) < period + 1:
        return None
    base = navs[-(period + 1)]
    if base == 0:
        return None
    return round((navs[-1] / base - 1) * 100, 2)


def calc_volatility(navs: list, periods: int = 252) -> Optional[float]:
    """Volatility annualized (%) — rolling {periods} ngày.

    = std(daily_returns) × sqrt(252) × 100
    """
    window = navs[-min(periods + 1, len(navs)):]
    if len(window) < 30:
        return None
    returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    n = len(returns)
    mean_r = sum(returns) / n
    std_r = (sum((r - mean_r) ** 2 for r in returns) / n) ** 0.5
    return round(std_r * (252 ** 0.5) * 100, 2)


def calc_sharpe_ratio(navs: list, periods: int = 252, rf_annual: float = 0.05) -> Optional[float]:
    """Sharpe Ratio xấp xỉ, rolling {periods} ngày gần nhất (252 = 1 năm giao dịch VN).

    rf_annual: lãi suất phi rủi ro — lãi suất tiền gửi 1Y VN ~5%
    """
    window = navs[-min(periods + 1, len(navs)):]
    if len(window) < 30:
        return None
    returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    n = len(returns)
    mean_r = sum(returns) / n
    std_r = (sum((r - mean_r) ** 2 for r in returns) / n) ** 0.5
    if std_r == 0:
        return None
    sharpe = (mean_r - rf_annual / 252) / std_r * (252 ** 0.5)
    return round(sharpe, 2)


def calc_sortino_ratio(navs: list, periods: int = 252, rf_annual: float = 0.05) -> Optional[float]:
    """Sortino Ratio — chỉ dùng downside deviation (returns âm) thay vì total std.

    Tốt hơn Sharpe cho tài sản có return không đối xứng (quỹ trái phiếu VN).
    """
    window = navs[-min(periods + 1, len(navs)):]
    if len(window) < 30:
        return None
    returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
    mean_r = sum(returns) / len(returns)
    rf_daily = rf_annual / 252
    neg_returns = [r for r in returns if r < rf_daily]
    if not neg_returns:
        return None  # Không có ngày lỗ → Sortino = infinity (không có ý nghĩa)
    downside_var = sum((r - rf_daily) ** 2 for r in neg_returns) / len(neg_returns)
    downside_std = downside_var ** 0.5
    if downside_std == 0:
        return None
    return round((mean_r - rf_daily) / downside_std * (252 ** 0.5), 2)


def calc_max_drawdown(navs: list, periods: int = 252) -> Optional[float]:
    """Max Drawdown trong {periods} ngày gần nhất. Returns phần trăm (0–100)."""
    window = navs[-min(periods, len(navs)):]
    if len(window) < 5:
        return None
    peak = window[0]
    max_dd = 0.0
    for nav in window[1:]:
        if nav > peak:
            peak = nav
        else:
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd
    return round(max_dd * 100, 2)


def calc_stochastic(navs: list, k_period: int = 14, k_smooth: int = 3, d_period: int = 3) -> Optional[dict]:
    """Stochastic oscillator (%K/%D) — dùng NAV thay OHLC (quỹ mở không có volume/OHLC).

    k_period: lookback tìm highest/lowest
    k_smooth: SMA tạo Slow %K
    d_period: SMA tạo %D

    Returns {"pct_k": float, "pct_d": float} hoặc None nếu thiếu data.
    """
    raw_k_count = k_smooth + d_period - 1  # số raw_k cần tính để có đủ %D
    if len(navs) < k_period + raw_k_count - 1:
        return None

    raw_k = []
    for i in range(len(navs) - raw_k_count, len(navs)):
        window = navs[i - k_period + 1: i + 1]
        lo, hi = min(window), max(window)
        if hi == lo:
            raw_k.append(50.0)
        else:
            raw_k.append((navs[i] - lo) / (hi - lo) * 100)

    # Slow %K: SMA(raw_k, k_smooth)
    smooth_k = [_avg(raw_k[j - k_smooth + 1: j + 1]) for j in range(k_smooth - 1, len(raw_k))]
    if len(smooth_k) < d_period:
        return None

    return {
        "pct_k": round(smooth_k[-1], 1),
        "pct_d": round(_avg(smooth_k[-d_period:]), 1),
    }


def calc_golden_cross(navs: list, lookback: int = 5) -> Optional[dict]:
    """Phát hiện Golden Cross / Death Cross (MA20 × MA50) trong lookback ngày gần nhất.

    Returns dict với:
      type: "golden" (MA20 cắt lên MA50), "death" (MA20 cắt xuống MA50),
            "above" (MA20 đang trên, không cross gần đây), "below" (MA20 đang dưới)
      ma20, ma50: giá trị hiện tại

    Returns None nếu không đủ dữ liệu (cần ít nhất 50 + lookback điểm).
    """
    if len(navs) < 50 + lookback:
        return None

    n = len(navs)
    # Tính (lookback+1) giá trị MA để phát hiện (lookback) lần chuyển trạng thái
    indices = range(n - lookback - 1, n)
    ma20_series = [_avg(navs[max(0, i - 19): i + 1]) for i in indices]
    ma50_series = [_avg(navs[max(0, i - 49): i + 1]) for i in indices]
    above = [m20 > m50 for m20, m50 in zip(ma20_series, ma50_series)]

    # Tìm cross gần nhất (ưu tiên gần nhất)
    cross_type = None
    for i in range(len(above) - 1, 0, -1):
        if not above[i - 1] and above[i]:
            cross_type = "golden"
            break
        elif above[i - 1] and not above[i]:
            cross_type = "death"
            break

    return {
        "type": cross_type if cross_type else ("above" if above[-1] else "below"),
        "ma20": round(ma20_series[-1], 2),
        "ma50": round(ma50_series[-1], 2),
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

    stoch = calc_stochastic(navs)
    stoch_k = stoch_d = None
    if stoch:
        stoch_k, stoch_d = stoch["pct_k"], stoch["pct_d"]
        if stoch_k < 20 and stoch_d < 20:
            score += 1; details.append(f"Stoch {stoch_k:.0f}/{stoch_d:.0f} qua ban")
        elif stoch_k > 80 and stoch_d > 80:
            score -= 1; details.append(f"Stoch {stoch_k:.0f}/{stoch_d:.0f} qua mua")

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

    gc = calc_golden_cross(navs)
    ma20 = gc["ma20"] if gc else calc_ma(navs, 20)
    ma50 = gc["ma50"] if gc else calc_ma(navs, 50)
    gc_type = None
    if gc:
        gc_type = gc["type"]
        if gc_type == "golden":
            score += 3; details.append("Golden Cross 🟢🟢")
        elif gc_type == "death":
            score -= 3; details.append("Death Cross 🔴🔴")
        elif gc_type == "above":
            score += 1; details.append("MA✅")
        else:
            details.append("MA⬇")
    elif ma20 and ma50:
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

    cci = calc_cci(navs)
    if cci is not None:
        if cci < -100:
            score += 1; details.append(f"CCI {cci:.0f} qua ban")
        elif cci > 100:
            score -= 1; details.append(f"CCI {cci:.0f} qua mua")

    roc = calc_roc(navs)
    if roc is not None:
        if roc < -5:
            score += 1; details.append(f"ROC {roc:.1f}% dip")
        elif roc > 5:
            score -= 1; details.append(f"ROC +{roc:.1f}% hot")

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

    sharpe  = calc_sharpe_ratio(navs)
    sortino = calc_sortino_ratio(navs)
    vol     = calc_volatility(navs)
    max_dd  = calc_max_drawdown(navs)

    return {
        "signal": sig, "score": score, "rsi": rsi,
        "bb_pct": bb_pct, "macd_hist": macd_hist,
        "stoch_k": stoch_k, "stoch_d": stoch_d,
        "cci": cci, "roc": roc,
        "sharpe": sharpe, "sortino": sortino,
        "volatility": vol, "max_dd": max_dd,
        "nav": last, "nav_prev": prev, "chg_pct": round(chg_pct, 3),
        "nav_date": pts[-1]["date"],
        "details": details[:4],
        "ma20": ma20, "ma50": ma50, "gc_type": gc_type,
        "chg7": chg7, "chg30": chg30,
    }


# ═══════════════════════════════════════
# TELEGRAM HELPERS
# ═══════════════════════════════════════

# ── Trade wizard session state ────────────────────────────────────────────────
# { chat_id: {"step": "await_units"|"await_amount"|"confirm",
#             "fund": str, "type": "buy"|"sell",
#             "units": float|None, "amount": float|None, "date": str} }
_TRADE_SESSIONS: dict = {}


def _make_rate_checker(limit: int = 10, window: int = 60):
    """Trả về hàm check_rate(chat_id) dùng state riêng cho 1 lần chạy command_handler().

    State cục bộ (không phải module-global) để mỗi lần command_handler() khởi động
    (1 lần duy nhất khi bot start, chạy vô hạn trong daemon thread) có sổ đếm sạch.
    """
    rate_state: dict = {}  # { chat_id: [timestamp, ...] } — timestamps trong window hiện tại

    def check_rate(chat_id: str) -> bool:
        """True nếu chat_id còn trong hạn mức (limit req / window giây), False nếu vượt quá."""
        now = time.time()
        hits = [t for t in rate_state.get(chat_id, []) if now - t < window]
        if len(hits) >= limit:
            rate_state[chat_id] = hits
            return False
        hits.append(now)
        rate_state[chat_id] = hits
        return True

    return check_rate


def tg_send_keyboard(token: str, chat_id: str, text: str, buttons: list[list[dict]]) -> bool:
    """Gửi tin nhắn với InlineKeyboardMarkup. buttons = [[{text, callback_data}, ...], ...]"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": buttons},
        }, timeout=15)
        if not r.ok:
            log.error(f"[Telegram KB] {r.status_code} → {r.text[:200]}")
        return r.ok
    except Exception as e:
        log.error(f"[Telegram KB] {e}")
        return False


def tg_answer_callback(token: str, callback_id: str) -> None:
    """Acknowledge callback query để Telegram xoá loading spinner."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5,
        )
    except Exception:
        pass


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
LINE = "─" * 16


def _get_portfolio_holdings(profile: dict) -> dict:
    """Đọc CCQ holdings từ PostgreSQL. Fallback về config.json nếu DB không có."""
    tg_id = str(profile.get("telegram_id", ""))
    if tg_id and _DB_AVAILABLE and _db.is_available():
        try:
            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                import psycopg2 as _pg2
                _pc = _pg2.connect(db_url, connect_timeout=6)
                with _pc.cursor() as _cur:
                    _cur.execute("""
                        SELECT code, type, units::float, nav::float, amount::float
                        FROM user_ccq_trades WHERE telegram_id=%s
                        ORDER BY trade_date, id
                    """, [tg_id])
                    _hmap: dict = {}
                    for _code, _tx, _u, _n, _amt in _cur.fetchall():
                        _u = float(_u or 0); _n = float(_n or 0); _amt = float(_amt or 0)
                        if _tx == "buy":
                            if _code not in _hmap:
                                _hmap[_code] = {"units": 0.0, "total_cost": 0.0}
                            _hmap[_code]["units"] += _u
                            _hmap[_code]["total_cost"] += _u * _n
                        elif _tx == "dividend":
                            if _code not in _hmap:
                                _hmap[_code] = {"units": 0.0, "total_cost": 0.0}
                            _hmap[_code]["units"] += _u
                            if _u <= 0 and _amt > 0:  # tiền mặt → giảm cost basis
                                _hmap[_code]["total_cost"] -= _amt
                        elif _tx == "sell" and _code in _hmap and _hmap[_code]["units"] > 0:
                            _f = min(_u / _hmap[_code]["units"], 1.0)
                            _hmap[_code]["total_cost"] -= _hmap[_code]["total_cost"] * _f
                            _hmap[_code]["units"] -= _u
                            if _hmap[_code]["units"] < 0.001:
                                del _hmap[_code]
                _pc.close()
                return {
                    c: {"code": c, "units": v["units"],
                        "avg_cost": v["total_cost"] / v["units"] if v["units"] else 0}
                    for c, v in _hmap.items() if v.get("units", 0) >= 0.001
                }
        except Exception as _pe:
            log.warning(f"[portfolio] from DB: {_pe}")
    return {h["code"]: h for h in profile.get("portfolio", [])
            if h.get("units", 0) > 0 and h.get("avg_cost", 0) > 0}


def msg_morning(profile: dict, nav_data: dict) -> str:
    action_funds = []
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if d and d["nav"] and ("MUA" in d["signal"] or "BÁN" in d["signal"]):
            action_funds.append(code)

    pnl_part = ""
    holdings = _get_portfolio_holdings(profile)
    if holdings:
        total_val = total_cost = 0.0
        for code, h in holdings.items():
            d = nav_data.get(code)
            if d and d["nav"]:
                total_val  += float(h["units"]) * d["nav"]
                total_cost += float(h["units"]) * float(h["avg_cost"])
        if total_cost > 0:
            pnl = total_val - total_cost
            sign = "+" if pnl >= 0 else ""
            pnl_part = f" · Danh mục {int(total_val):,}đ ({sign}{pnl/total_cost*100:.1f}%)"

    sig_part = f"⚡ {', '.join(action_funds)}" if action_funds else "💤 Không có tín hiệu đặc biệt"
    return f"🌅 {sig_part}{pnl_part}\n👉 Xem chi tiết trong Mini App — gõ /app"


def msg_evening(profile: dict, nav_data: dict, morning_nav: dict) -> str:
    today = datetime.now().date().isoformat()
    action_funds  = []
    outdated_note = []
    for code in profile.get("watched_funds", []):
        d = nav_data.get(code)
        if not d or d["nav"] == 0:
            continue
        if d.get("nav_date") and d["nav_date"] < today:
            outdated_note.append(code)
        if "MUA" in d["signal"] or "BÁN" in d["signal"]:
            action_funds.append(code)

    pnl_part = ""
    holdings = _get_portfolio_holdings(profile)
    if holdings:
        total_val = total_cost = 0.0
        for code, h in holdings.items():
            d = nav_data.get(code)
            if d and d["nav"]:
                total_val  += float(h["units"]) * d["nav"]
                total_cost += float(h["units"]) * float(h["avg_cost"])
        if total_cost > 0:
            pnl = total_val - total_cost
            sign = "+" if pnl >= 0 else ""
            pnl_part = f" · Danh mục {int(total_val):,}đ ({sign}{pnl/total_cost*100:.1f}%)"

    sig_part = f"⚡ {', '.join(action_funds)}" if action_funds else "💤 Không có tín hiệu đặc biệt"
    warn = f"\n⚠️ NAV chưa cập nhật: {', '.join(outdated_note)}" if outdated_note else ""
    return f"🌆 {sig_part}{pnl_part}{warn}\n👉 Xem chi tiết trong Mini App — gõ /app"


def msg_signal_alert(profile: dict, code: str, old_sig: str, new_sig: str, d: dict) -> str:
    if "MUA" in new_sig:
        icon = "🟢"
    elif "BÁN" in new_sig:
        icon = "🔴"
    else:
        icon = "🔔"
    return (
        f"{icon} <b>{code}</b> {old_sig or 'N/A'} → <b>{new_sig}</b> · NAV {fmt_nav(d.get('nav', 0))}\n"
        f"👉 Xem chi tiết trong Mini App — gõ /app"
    )


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
    "TCBF":    "2026-06-23",
    "VCBFTBF": "2026-06-23",
    "SSISCA":  "2026-06-23",
    "VCBFBCF": "2026-06-23",
    "TCFF":    "2026-06-23",
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


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Decode JWT exp claim (unix timestamp) mà không cần verify signature.

    TCBS JWT là HS256 — chúng ta không có secret key để verify,
    nhưng chỉ cần exp để biết khi nào token hết hạn.
    Returns Unix timestamp hoặc None nếu decode thất bại.
    """
    try:
        import base64, json as _json
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Payload là phần thứ 2, base64url-encoded (không có padding)
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("exp")
    except Exception:
        return None


def _check_tcbs_token_expiry(config: dict) -> Optional[dict]:
    """Kiểm tra TCBS token có sắp hết hạn không.

    Returns dict {"days_left": int, "expired": bool} hoặc None nếu không có token.
    """
    token = config.get("tcbs_token", "")
    if not token or token.startswith("NHAP"):
        return None
    exp = _decode_jwt_exp(token)
    if not exp:
        return None
    now_ts = int(time.time())
    days_left = (exp - now_ts) // 86400
    return {"days_left": days_left, "expired": days_left < 0, "exp_ts": exp}


def _handle_tcbs_auth_error(config: dict, failed_codes: set):
    """Gửi Telegram notification khi TCBS token hết hạn — chỉ 1 lần cho đến khi token được update.
    Dedup dùng chung state.json với job_check_tcbs_token() để 2 đường phát hiện (fetch trực
    tiếp vs cron kiểm tra JWT exp hàng ngày) không cùng gửi 2 tin nhắn cho cùng 1 token hết hạn."""
    global _tcbs_auth_notified
    tcbs_token = config.get("tcbs_token", "")
    if _tcbs_auth_notified or _already_notified_token_expired(tcbs_token):
        log.debug("[TCBS-AUTH] Đã notify rồi, bỏ qua cho đến khi token được cập nhật")
        return
    _tcbs_auth_notified = True
    _mark_token_expired_notified(tcbs_token)
    log.warning(f"[TCBS-AUTH] Token hết hạn, không fetch được: {', '.join(sorted(failed_codes))}"
                f" — Cập nhật token mới qua Mini App (tab Admin).")
    token = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", ""))
    if token and admin_id:
        msg = (
            f"⚠️ <b>TCBS Token hết hạn</b>\n"
            f"Quỹ bị ảnh hưởng: {', '.join(f'<code>{c}</code>' for c in sorted(failed_codes))}\n"
            f"→ Mở Mini App → tab Admin → Cập nhật TCBS Token"
        )
        tg_send(token, admin_id, msg)




def fetch_all(config: dict, codes: set) -> dict:
    """GOV-007 tiếp diễn (2026-07-14): fund_cfg TRƯỚC ĐÂY ưu tiên config.json["funds"]
    (dữ liệu ghi 1 lần, có thể cũ/sai) HƠN FUND_CATALOG (mã nguồn, luôn đúng nhất) —
    đây chính là lý do bản sửa fmarket_id cho VCBFTBF trong FUND_CATALOG KHÔNG có tác
    dụng gì cả: config.json trên Railway vẫn giữ fmarket_id=31 cũ, và luôn thắng.
    Đổi ưu tiên: FUND_CATALOG trước, config.json["funds"] chỉ dùng cho quỹ KHÔNG có
    trong FUND_CATALOG (khớp đúng pattern đã dùng ở _api_admin_fetch_nav)."""
    result = {}
    funds_cfg = config.get("funds", {})
    for code in sorted(codes):
        fund_cfg = FUND_CATALOG.get(code) or funds_cfg.get(code) or {}
        pts, src = get_nav_series_with_source(code, fund_cfg, config)
        if pts:
            result[code] = calc_signal(code, pts)
            sig = result[code]["signal"]
            nav_dt = result[code]["nav_date"]
            today_str = date.today().isoformat()
            stale_warn = f"  ⚠ NAV date={nav_dt} (stale, today={today_str})" if nav_dt < today_str else ""
            log.info(f"  {code:12s}  NAV={result[code]['nav']:>10,.0f}  {sig}{stale_warn}")
            # Sync full history to DB so miniapp uses same data as bot. src=None
            # nghĩa là điểm này đã đọc lại từ chính nav_history (fallback cuối,
            # không phải fetch mới) — không cần ghi lại, và quan trọng hơn: KHÔNG
            # còn đoán nguồn theo fund_cfg tĩnh nữa (bug gây ra vụ NAV VCBFTBF sai —
            # 'fmarket' bị dùng làm nhãn dù dữ liệu thật lấy từ TCinvest).
            if src and _DB_AVAILABLE and _db.is_available():
                saved = 0
                for p in pts:
                    try:
                        _db.upsert_nav(code, date.fromisoformat(p["date"]), p["nav"], src)
                        saved += 1
                    except Exception:
                        pass
                if saved:
                    log.debug(f"  {code}  synced {saved} NAV points to DB")
        else:
            log.warning(f"  {code:12s}  ⚠ No data")
    return result


def all_watched_codes(config: dict) -> set:
    codes = set(FUND_CATALOG.keys())  # Luôn fetch tất cả 43 quỹ để DB nav_history đầy đủ
    for p in get_profiles(config):
        codes.update(p.get("watched_funds", []))
    return codes


# ═══════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════

def job_morning():
    log.info("══ JOB: Morning Report ══")
    today = date.today().isoformat()
    state_chk = load_state()
    if state_chk.get("last_morning_date") == today:
        log.info(f"[job_morning] Đã gửi hôm nay ({today}), bỏ qua.")
        return
    _tcbs_auth_fail_codes.clear()          # Reset trước mỗi chu kỳ fetch
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        log.error("Bot token chưa được cấu hình trong config.json")
        return
    # Fetch giá vàng mỗi sáng (vang.today API, không cần auth)
    try:
        import sys as _sys
        _gold_script = Path(__file__).parent / "fetch_gold.py"
        if _gold_script.exists():
            _sys.path.insert(0, str(_gold_script.parent))
            import importlib.util as _ilu
            _gspec = _ilu.spec_from_file_location("fetch_gold", _gold_script)
            _gmod  = _ilu.module_from_spec(_gspec)
            _gspec.loader.exec_module(_gmod)
            _gmod.run_daily(verbose=False)
            # Tự vá khoảng trống (bot restart/deploy làm lỡ vài ngày) — idempotent,
            # chỉ điền ngày chưa có dữ liệu nên gọi lại mỗi sáng vẫn an toàn.
            _filled = _gmod.run_backfill(days=10, verbose=False)
            log.info(f"[job_morning] Giá vàng đã cập nhật (backfill {_filled} điểm)")
    except Exception as _ge:
        log.warning(f"[job_morning] fetch_gold: {_ge}")
    codes    = all_watched_codes(config)
    nav_data = fetch_all(config, codes)
    # Cảnh báo ngay nếu TCBS token hết hạn trong lúc fetch
    if _tcbs_auth_fail_codes:
        _handle_tcbs_auth_error(config, _tcbs_auth_fail_codes.copy())
    else:
        global _tcbs_auth_notified
        _tcbs_auth_notified = False  # Token hoạt động → reset để notify lần sau nếu hết hạn lại
        _clear_token_expired_notified()
    state = load_state()
    state["morning_nav"]       = {k: {"nav": v["nav"], "date": v["nav_date"]} for k, v in nav_data.items()}
    state["last_morning"]      = datetime.now().isoformat()
    state["last_morning_date"] = today
    save_state(state)
    for profile in get_profiles(config):
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

    # Kiểm tra pending_confirm từ harvest qua đêm → notify admin
    try:
        _notify_pending_nav_confirms(token, config)
    except Exception as e:
        log.warning(f"[job-morning] pending-confirm check failed: {e}")


def _notify_pending_nav_confirms(token: str, config: dict) -> None:
    """Gửi Telegram cho admin các NAV cần xác nhận (manual ≠ fetch)."""
    if not (_DB_AVAILABLE and _db.is_available()):
        return
    pendings = _db.get_pending_confirms()
    if not pendings:
        return

    admin_id = str(config.get("admin_telegram_id", ""))
    if not admin_id:
        return

    log.info(f"[nav-confirm] {len(pendings)} mã cần xác nhận")
    for p in pendings:
        code      = p["fund_code"]
        nav_date  = p["nav_date"]
        manual    = p["manual_nav"]
        fetch_val = p["fetch_nav"]
        diff_pct  = (fetch_val - manual) / manual * 100 if manual else 0

        msg = (
            f"⚠️ <b>NAV cần xác nhận — <code>{code}</code></b>\n"
            f"📅 Ngày: <b>{nav_date}</b>\n"
            f"📝 Manual (user nhập): <b>{manual:,.0f} đ</b>\n"
            f"📡 Fetch (TCinvest): <b>{fetch_val:,.0f} đ</b>\n"
            f"↕️ Chênh lệch: <b>{diff_pct:+.2f}%</b>\n\n"
            f"Chọn giá trị đúng:"
        )
        buttons = [[
            {"text": f"✅ Manual ({manual:,.0f})",
             "callback_data": f"nav_confirm:{code}:{nav_date}:manual"},
            {"text": f"📡 Fetch ({fetch_val:,.0f})",
             "callback_data": f"nav_confirm:{code}:{nav_date}:fetch"},
        ]]
        tg_send_keyboard(token, admin_id, msg, buttons)


def job_evening():
    log.info("══ JOB: Evening Report ══")
    today = date.today().isoformat()
    state_chk = load_state()
    if state_chk.get("last_evening_date") == today:
        log.info(f"[job_evening] Đã gửi hôm nay ({today}), bỏ qua.")
        return
    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        return
    codes    = all_watched_codes(config)
    nav_data = fetch_all(config, codes)
    state = load_state()
    morning_nav = state.get("morning_nav", {})
    state["last_evening"]      = datetime.now().isoformat()
    state["last_evening_date"] = today
    save_state(state)
    for profile in get_profiles(config):
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
    if _tcbs_auth_fail_codes:
        _handle_tcbs_auth_error(config, _tcbs_auth_fail_codes.copy())
    else:
        global _tcbs_auth_notified
        _tcbs_auth_notified = False  # Token hoạt động → reset để notify lần sau nếu hết hạn lại
        _clear_token_expired_notified()
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
        for profile in get_profiles(config):
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

    # Persist to PostgreSQL (no-op if DB unavailable). NAV chính nó đã được
    # fetch_all() ghi với nguồn ĐÚNG ở trên rồi (get_nav_series_with_source) —
    # gọi lại upsert_nav() ở đây KHÔNG kèm source (mặc định "fmarket") là dư thừa
    # và từng là 1 trong các chỗ góp phần gây sai nhãn nguồn NAV (vụ VCBFTBF).
    if _DB_AVAILABLE and _db.is_available():
        today = date.today()
        for code, d in nav_data.items():
            sig = d.get("signal", "")
            strength_map = {
                "MUA MẠNH": "strong_buy", "MUA": "buy",
                "BÁN MẠNH": "strong_reduce", "BÁN": "reduce",
            }
            strength = next((v for k, v in strength_map.items() if k in sig), "hold")
            fund_cfg = config.get("funds", {}).get(code) or FUND_CATALOG.get(code, {})
            settle = fund_cfg.get("settlement", "T2")
            try:
                _db.save_signal(
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
    for profile in get_profiles(config):
        tg = str(profile.get("telegram_id", ""))
        if not tg.lstrip("-").isdigit():
            continue
        watched   = set(profile.get("watched_funds", []))
        relevant  = {c: d for c, d in newly_published.items() if c in watched}
        if not relevant:
            continue
        codes_s = ", ".join(sorted(relevant.keys()))
        msg = (
            f"📢 NAV mới cho {len(relevant)} quỹ: {codes_s}\n"
            f"👉 Xem chi tiết trong Mini App — gõ /app"
        )
        tg_send(token, tg, msg)

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
    for profile in get_profiles(config):
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

def job_check_tcbs_token():
    """Chạy lúc 07:30 hàng ngày — kiểm tra TCBS JWT còn hạn không, cảnh báo trước 3 ngày."""
    config = load_config()
    status = _check_tcbs_token_expiry(config)
    if not status:
        return  # Không có token hoặc không decode được — bỏ qua
    token = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", ""))
    if not token or not admin_id:
        return
    days = status["days_left"]
    tcbs_token = config.get("tcbs_token", "")
    if status["expired"]:
        if _already_notified_token_expired(tcbs_token):
            log.debug("[token-check] Đã notify token hết hạn này rồi (từ đường khác) — bỏ qua")
            return
        _mark_token_expired_notified(tcbs_token)
        tg_send(token, admin_id, (
            "🔴 <b>TCBS Token đã HẾT HẠN</b>\n"
            "Quỹ TCBS (TCBF, TCFF, TCGF...) không fetch được NAV.\n"
            "→ Mở Mini App → tab Admin → Cập nhật TCBS Token"
        ))
        log.warning("[token-check] TCBS token HET HAN — notified admin")
    elif days <= 3:
        tg_send(token, admin_id, (
            f"⚠️ <b>TCBS Token sắp hết hạn</b> (còn {days} ngày)\n"
            "→ Mở Mini App → tab Admin → Cập nhật TCBS Token trước khi hết hạn"
        ))
        log.warning(f"[token-check] TCBS token con {days} ngay — notified admin")
    else:
        log.debug(f"[token-check] TCBS token OK con {days} ngay")


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
    script = Path(__file__).parent / "harvest_nav.py"
    if not script.exists():
        log.error("[harvest] harvest_nav.py không tìm thấy")
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
            _handle_nav_jump_alert(output)
        else:
            log.error("[harvest] exit=%d stderr=%s", result.returncode,
                      (result.stderr or "")[:500])
    except subprocess.TimeoutExpired:
        log.error("[harvest] Timeout sau 300s")
    except Exception as e:
        log.error("[harvest] %s", e)


def job_nav_reverify():
    """GOV-008/T2-014 (2026-07-15): Cơ chế 3-layer re-verification cho NAV
    nguồn 'tcinvest' — chạy sau job_harvest_nav (21:00, sau cả 2 lần harvest
    18:30/20:00). Bài học vụ VCBFTBF: fetch tcinvest lần đầu KHÔNG đủ để coi
    NAV ngày mới nhất là "chốt" — TCBS có thể tự sửa lại vài giờ sau khi công
    bố chính thức. Job này fetch lại và nâng verify_tier (T+1/T+8/T+31) cho
    các ngày đã đủ tuổi và vẫn khớp, hoặc phát hiện+sửa nếu TCBS đã tự đổi.
    """
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[nav_reverify] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: NAV 3-Layer Re-verify (T+1/T+8/T+31) ══")
    import subprocess
    script = Path(__file__).parent / "harvest_nav.py"
    if not script.exists():
        log.error("[nav_reverify] harvest_nav.py không tìm thấy")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--reverify"],
            capture_output=True, text=True, timeout=300,
            env={**__import__("os").environ},
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            summary = output.splitlines()[-1] if output else "OK"
            log.info("[nav_reverify] %s", summary)
        else:
            log.error("[nav_reverify] exit=%d stderr=%s", result.returncode,
                      (result.stderr or "")[:500])
    except subprocess.TimeoutExpired:
        log.error("[nav_reverify] Timeout sau 300s")
    except Exception as e:
        log.error("[nav_reverify] %s", e)


def job_nav_integrity_check():
    """GOV-008-part2 (2026-07-15): Harvey yêu cầu xác thực NAV tới TỪNG datapoint
    và chống bị sửa ngầm (manipulate) — chạy sau job_nav_reverify (21:30), quét
    row_hash toàn bộ nav_history, báo admin ngay nếu phát hiện dòng nào có hash
    không khớp giá trị hiện tại (dấu hiệu bị sửa bằng SQL thô, bỏ qua các hàm
    ứng dụng upsert_nav/reverify_nav_tier/resolve_nav_confirm)."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[nav_integrity] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: NAV Integrity Check (row_hash) ══")
    import subprocess
    script = Path(__file__).parent / "harvest_nav.py"
    if not script.exists():
        log.error("[nav_integrity] harvest_nav.py không tìm thấy")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--verify-integrity"],
            capture_output=True, text=True, timeout=180,
            env={**__import__("os").environ},
        )
        output = (result.stdout or "").strip()
        if "MISMATCH_ALERT:" in output:
            mismatch_line = next((l for l in output.splitlines() if l.startswith("MISMATCH_ALERT:")), "")
            codes = mismatch_line.replace("MISMATCH_ALERT:", "").strip()
            log.warning("[nav_integrity] Phát hiện NAV bị sửa ngầm: %s", codes)
            config = load_config()
            token = config.get("bot_token", "")
            admin_id = str(config.get("admin_telegram_id", "")).strip()
            if token and admin_id:
                tg_send(token, admin_id, (
                    "🚨 <b>Phát hiện NAV bị sửa ngầm (row_hash không khớp)</b>\n"
                    f"{codes[:300]}\n"
                    "Kiểm tra ngay — có thể do script/thao tác bỏ qua hàm ứng dụng chuẩn."
                ))
            if _DB_AVAILABLE and _db.is_available():
                _db.log_audit(None, "nav_integrity_mismatch", "nav_history", None,
                               note=f"row_hash không khớp: {codes[:500]}")
        elif result.returncode == 0:
            log.info("[nav_integrity] %s", output.splitlines()[-1] if output else "OK")
        else:
            log.error("[nav_integrity] exit=%d stderr=%s", result.returncode,
                      (result.stderr or "")[:500])
    except subprocess.TimeoutExpired:
        log.error("[nav_integrity] Timeout sau 180s")
    except Exception as e:
        log.error("[nav_integrity] %s", e)


def _handle_nav_jump_alert(harvest_stdout: str) -> None:
    """GOV-003: parse dòng 'JUMP_ALERT: CODE:old->new:pct%;...' từ harvest_nav.py --daily
    (NAV nhảy >15%/phiên — có thể là data glitch, không phải lỗi manual/fetch mismatch đã
    có ở pending_confirm). Ghi audit_log + báo admin ngay, không chỉ log im lặng vì có thể
    ảnh hưởng tín hiệu/dự báo hiển thị cho user."""
    line = next((l for l in harvest_stdout.splitlines() if l.startswith("JUMP_ALERT:")
                 or " JUMP_ALERT: " in l), None)
    if not line:
        return
    payload = line.split("JUMP_ALERT:", 1)[-1].strip()
    if not payload:
        return
    entries = [e for e in payload.split(";") if e]
    log.warning("[harvest] NAV jump anomaly: %s", payload)
    if _DB_AVAILABLE and _db.is_available():
        for e in entries:
            try:
                code, rest = e.split(":", 1)
                old_new, pct = rest.rsplit(":", 1)
                old_v, new_v = old_new.split("->")
                _db.log_audit(None, "nav_jump_anomaly", "nav_history", code,
                              before={"nav": old_v}, after={"nav": new_v, "pct": pct},
                              note="Harvest daily phát hiện NAV nhảy bất thường")
            except Exception as ex:
                log.warning("[harvest] không parse được jump entry '%s': %s", e, ex)

    config = load_config()
    token = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    if token and admin_id:
        tg_send(token, admin_id, (
            f"⚠️ <b>NAV nhảy bất thường (&gt;15%/phiên)</b>\n"
            f"<code>{payload.replace(';', chr(10))}</code>\n"
            f"Kiểm tra lại nguồn dữ liệu — có thể là lỗi API, không phải biến động thị trường thật."
        ))


def _run_t2_script(name: str, script_name: str, args: list, timeout: int = 300) -> None:
    """Helper chạy 1 script scripts/*.py qua subprocess, log kết quả. Không raise
    — lỗi ở 1 model (vd XGBoost chưa train) không được chặn model khác chạy."""
    script = Path(__file__).parent.parent / "scripts" / script_name
    if not script.exists():
        log.error("[%s] %s không tìm thấy", name, script_name)
        return
    try:
        result = __import__("subprocess").run(
            [sys.executable, str(script)] + args,
            capture_output=True, text=True, timeout=timeout,
            env={**__import__("os").environ},
        )
        if result.returncode == 0:
            summary = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else "OK"
            log.info("[%s] %s", name, summary)
        else:
            log.error("[%s] exit=%d err=%s", name, result.returncode, (result.stderr or "")[:300])
    except Exception as e:
        log.error("[%s] %s", name, e)


def job_t2_predict():
    """T2-003/T2-004/T2-005/T2-012: Chạy ARIMA + XGBoost + Naive + Ensemble forecast
    sau harvest lúc 18:31, theo thứ tự (ensemble cần cả 3 dự báo con của cùng ngày
    đã ghi DB). Naive (persistence) thêm vào T2-012 sau khi backtest walk-forward
    cho thấy nó đánh bại ARIMA ở mọi quỹ test — xem BACKLOG.md."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[t2_predict] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: T+2 Predict (ARIMA + XGBoost + Naive + Ensemble) ══")
    _run_t2_script("t2_predict_arima",    "t2_arima.py",    ["--predict"])
    _run_t2_script("t2_predict_xgboost",  "t2_xgboost.py",  ["--predict"])
    _run_t2_script("t2_predict_naive",    "t2_naive.py",    ["--predict"])
    _run_t2_script("t2_predict_ensemble", "t2_ensemble.py", ["--predict"], timeout=120)


def job_t2_score():
    """T2-006: Chấm điểm dự báo T+2 sau khi NAV hôm nay đã về (18:32)."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[t2_score] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: T+2 Score ══")
    script = Path(__file__).parent.parent / "scripts" / "t2_arima.py"
    if not script.exists():
        log.error("[t2_score] t2_arima.py không tìm thấy")
        return
    try:
        result = __import__("subprocess").run(
            [sys.executable, str(script), "--score"],
            capture_output=True, text=True, timeout=120,
            env={**__import__("os").environ},
        )
        if result.returncode == 0:
            for line in (result.stdout or "").strip().splitlines()[-3:]:
                log.info("[t2_score] %s", line)
        else:
            log.error("[t2_score] exit=%d err=%s", result.returncode, (result.stderr or "")[:300])
    except Exception as e:
        log.error("[t2_score] %s", e)

    try:
        _check_mape_streak_alerts()
    except Exception as e:
        log.warning("[t2_score] mape streak check failed: %s", e)


# GOV-003: model dự báo T+2 sai lệch kéo dài ảnh hưởng trực tiếp tới giá trị tính năng Pro
# (T2-009 hiển thị dự báo cho user trả tiền) — cần biết sớm hơn là chỉ xem accuracy dashboard
# thủ công. Threshold/streak chọn kinh nghiệm: NAV quỹ mở dao động nhẹ, MAPE T+2 bình thường
# thường <3%; >8% duy trì 5 ngày liên tiếp là dấu hiệu model lệch (data glitch, regime thay đổi).
MAPE_ALERT_THRESHOLD_PCT = 8.0
MAPE_ALERT_STREAK_DAYS = 5


def _latest_xgb_version() -> str:
    """T2-007 bump version (xgb-v1 → xgb-v2 → ...) mỗi lần retrain — không được
    hardcode 'xgb-v1' (cùng bug đã sửa trong t2_ensemble.py: sau retrain, mọi
    dự báo XGBoost mới nằm dưới version mới, hardcode cũ sẽ không match được
    nữa, khiến cảnh báo/monitoring âm thầm ngừng theo dõi XGBoost)."""
    try:
        with _db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT model_version FROM nav_predictions
                    WHERE model_version LIKE 'xgb-v%'
                    ORDER BY created_at DESC LIMIT 1
                """)
                row = cur.fetchone()
        return row[0] if row else "xgb-v1"
    except Exception:
        return "xgb-v1"


def _check_mape_streak_alerts() -> None:
    if not (_DB_AVAILABLE and _db.is_available()):
        return
    config = load_config()
    token = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    for model_version in ("arima-v1", _latest_xgb_version(), "naive-v1", "ensemble-v1"):
        streak = _db.get_mape_breach_streak(model_version, MAPE_ALERT_THRESHOLD_PCT,
                                             max_days=MAPE_ALERT_STREAK_DAYS)
        if streak != MAPE_ALERT_STREAK_DAYS:
            continue  # chưa đạt ngưỡng, hoặc đã báo rồi (streak > N ở ngày trước đó)
        _db.log_audit(None, "mape_threshold_breach", "model_metrics", model_version,
                       after={"streak_days": streak, "threshold_pct": MAPE_ALERT_THRESHOLD_PCT},
                       note=f"MAPE > {MAPE_ALERT_THRESHOLD_PCT}% liên tục {streak} ngày")
        log.warning("[t2_score] MAPE breach: %s streak=%d", model_version, streak)
        if token and admin_id:
            tg_send(token, admin_id, (
                f"⚠️ <b>Model T+2 {model_version} kém chính xác</b>\n"
                f"MAPE &gt; {MAPE_ALERT_THRESHOLD_PCT}% liên tục {streak} ngày qua.\n"
                f"Cân nhắc kiểm tra dữ liệu đầu vào hoặc chờ retrain tuần tới."
            ))


def job_t2_retrain():
    """T2-007: Weekly retrain XGBoost — Chủ nhật 02:00, dùng toàn bộ nav_history
    (kể cả actuals mới nhất tích luỹ từ tuần trước). Bump model_version tự động
    (xgb-v{N+1}) — xem t2_xgboost.py::_next_version(). Train có thể chậm hơn khi
    data lớn dần nên timeout dài hơn các job T+2 khác."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[t2_retrain] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: T+2 Weekly Retrain (XGBoost) ══")
    _run_t2_script("t2_retrain", "t2_xgboost.py", ["--train"], timeout=900)


def job_t2_reweight():
    """T2-008/T2-012: Tính lại trọng số ensemble (W_ARIMA/W_XGB/W_NAIVE) mỗi 30
    ngày dựa trên MAPE 30 ngày qua của cả 3 model con — model lỗi ít hơn được
    trọng số cao hơn."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[t2_reweight] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: T+2 Ensemble Reweight ══")
    _run_t2_script("t2_reweight", "t2_ensemble.py", ["--reweight"], timeout=60)


def job_backup_db():
    """GOV-002: pg_dump hàng ngày vào DATA_DIR/backups (Railway volume persistent),
    retention 14 bản gần nhất (scripts/backup_db.py::_prune). Không raise — lỗi backup
    không được chặn bot chạy tiếp, nhưng PHẢI báo admin vì đây là dữ liệu quan trọng
    (không có backup = mất dữ liệu vĩnh viễn nếu Railway volume hỏng)."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[backup_db] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: Database Backup ══")
    script = Path(__file__).parent.parent / "scripts" / "backup_db.py"
    if not script.exists():
        log.error("[backup_db] scripts/backup_db.py không tìm thấy")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--backup"],
            capture_output=True, text=True, timeout=600,
            env={**os.environ},
        )
    except Exception as e:
        result = None
        log.error("[backup_db] exception: %s", e)

    ok = result is not None and result.returncode == 0
    if ok:
        summary = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else "OK"
        log.info("[backup_db] %s", summary)
        return

    err = (result.stderr or "")[:300] if result else "subprocess lỗi (xem log exception phía trên)"
    log.error("[backup_db] FAILED exit=%s err=%s", result.returncode if result else "?", err)
    config = load_config()
    tok = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    if tok and admin_id:
        tg_send(tok, admin_id, f"⚠️ <b>Backup DB thất bại</b>\n<code>{err}</code>\nKiểm tra Railway logs ngay.")


def job_nav_source_audit():
    """Tự động hoá quy trình cross-check định kỳ ghi trong BACKLOG GOV-007-part3
    (trước đây phải chạy tay, và vì thế bug NAV-source-chưa-khoá kiểu VCBFTBF chỉ
    được phát hiện sau khi Harvey report — đã lặp lại 3 lần với 3 root cause khác
    nhau). Chạy hàng tuần, báo admin ngay nếu có quỹ nào trong 30 ngày qua có dòng
    nav_history không đến từ tcinvest/fixed/manual (dấu hiệu sớm của việc 1 job
    daily nào đó ghi đè lên dữ liệu đã khoá)."""
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[nav_source_audit] DB không khả dụng — bỏ qua")
        return
    log.info("══ JOB: NAV Source Audit (weekly) ══")
    try:
        flagged = _db.get_nav_source_audit(days=30)
    except Exception as e:
        log.error(f"[nav_source_audit] lỗi: {e}")
        return
    if not flagged:
        log.info("[nav_source_audit] Sạch — không có quỹ nào bị nguồn lạ ghi đè")
        return

    lines = ["⚠️ <b>NAV Source Audit</b> — phát hiện quỹ có nguồn chưa khoá (30 ngày qua):"]
    for f in flagged[:15]:
        sources = ", ".join(s for s in (f.get("sources_seen") or []) if s)
        dates = ", ".join((f.get("sample_dates") or [])[:3])
        lines.append(f"• <code>{f['fund_code']}</code>: {f['untrusted_count']} ngày ({sources}) — gần nhất {dates}")
    lines.append("\nChạy lại <code>harvest_nav.py --tcinvest</code> (lệnh reconcile) để tcinvest tự khoá lại toàn bộ lịch sử các mã này.")
    msg = "\n".join(lines)

    config = load_config()
    tok = config.get("bot_token", "")
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    if tok and admin_id:
        tg_send(tok, admin_id, msg)
    try:
        _db.log_audit(None, "nav_source_audit_flag", "nav_history", None,
                       note=f"{len(flagged)} quỹ bị flag: {[f['fund_code'] for f in flagged[:20]]}")
    except Exception:
        pass


def job_check_alerts():
    """PRO-004: Kiểm tra ngưỡng cảnh báo user tự đặt (bảng `alerts`), chạy 18:33
    sau daily harvest (18:30) + T+2 predict/score (18:31/18:32) để có NAV mới nhất.

    Debounce: chỉ gửi tối đa 1 lần / alert / ngày (so last_triggered với hôm nay).
    """
    if not (_DB_AVAILABLE and _db.is_available()):
        log.debug("[alerts] DB không khả dụng — bỏ qua")
        return
    try:
        alerts = _db.get_active_alerts()
    except Exception as e:
        log.error(f"[alerts] get_active_alerts lỗi: {e}")
        return
    if not alerts:
        return
    log.info(f"══ JOB: Check Alerts ({len(alerts)} active) ══")

    config = load_config()
    token  = config.get("bot_token", "")
    if not token or token.startswith("NHAP"):
        log.error("[alerts] Bot token chưa được cấu hình")
        return

    codes    = {a["fund_code"] for a in alerts}
    nav_data = fetch_all(config, codes)
    today    = date.today()

    for a in alerts:
        code = a["fund_code"]
        d    = nav_data.get(code)
        if not d:
            continue
        last_trig = a.get("last_triggered")
        if last_trig and last_trig.date() == today:
            continue  # đã báo hôm nay rồi

        cond      = a["condition"]
        threshold = float(a["threshold"]) if a.get("threshold") is not None else 0.0
        chg_pct   = d.get("chg_pct", 0) or 0
        sig       = d.get("signal", "")
        fired     = False
        reason    = ""
        if cond == "nav_up" and chg_pct >= threshold:
            fired, reason = True, f"NAV tăng {chg_pct:+.2f}% (ngưỡng ≥{threshold:.1f}%)"
        elif cond == "nav_down" and chg_pct <= -threshold:
            fired, reason = True, f"NAV giảm {chg_pct:+.2f}% (ngưỡng ≤-{threshold:.1f}%)"
        elif cond == "signal_buy" and "MUA" in sig:
            fired, reason = True, f"Tín hiệu {sig}"
        elif cond == "signal_sell" and "BÁN" in sig:
            fired, reason = True, f"Tín hiệu {sig}"
        if not fired:
            continue

        tg = a["telegram_id"]
        fund_name = (config.get("funds", {}).get(code) or FUND_CATALOG.get(code, {})).get("name", code)
        text = (
            f"🔔 <b>Cảnh báo: {code}</b> — {fund_name}\n\n"
            f"📌 {reason}\n"
            f"💰 NAV: {d.get('nav', 0):,.0f} đ ({d.get('nav_date', '')})\n\n"
            f"Gõ /app để mở Mini App."
        )
        ok = tg_send(token, tg, text)
        log.info(f"  🔔 ALERT #{a['id']} {code} {cond} → {tg}: {'OK' if ok else 'FAILED'}")
        if ok:
            try:
                _db.mark_alert_triggered(a["id"])
            except Exception as e:
                log.error(f"[alerts] mark_alert_triggered lỗi: {e}")


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

def get_profiles(config: dict) -> list:
    """Danh sách profiles (users đã /register). Nguồn chính: bảng bot_profiles trên
    PostgreSQL (persistent, không phụ thuộc Railway volume). Fallback config.json
    profiles nếu DB chưa sẵn sàng — giữ bot hoạt động được kể cả khi DB down.
    """
    if _DB_AVAILABLE and _db.is_available():
        try:
            db_profiles = _db.list_profiles()
            if db_profiles:
                return db_profiles
        except Exception as e:
            log.warning(f"[get_profiles] DB lỗi, fallback config.json: {e}")
    return config.get("profiles", [])


def find_profile_by_chat(config: dict, chat_id: str) -> Optional[dict]:
    if _DB_AVAILABLE and _db.is_available():
        try:
            p = _db.find_profile(chat_id)
            if p:
                return p
        except Exception as e:
            log.warning(f"[find_profile_by_chat] DB lỗi, fallback config.json: {e}")
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
        {"code": "TCBF",    "units": 487.21,  "avg_cost": 19525},
        {"code": "SSISCA",  "units": 713.57,  "avg_cost": 41936},
        {"code": "VCBFBCF", "units": 839.29,  "avg_cost": 35744},
        {"code": "VCBFTBF", "units": 449.41,  "avg_cost": 33377},
        {"code": "TCFF",    "units": 1832.66, "avg_cost": 13641},
    ],
}


def reconcile_admin_profile(config: dict) -> bool:
    """Tạo profile admin (seed watched_funds + portfolio) NẾU CHƯA TỒN TẠI.

    Trả về True nếu config.json bị thay đổi (cần save). Chỉ seed một lần lúc tạo
    profile mới — KHÔNG merge lại watched_funds mỗi lần bot khởi động, để tránh
    tự động thêm lại quỹ mà user đã chủ động unwatch qua Mini App.

    Từ Giai đoạn 1 (scaling): nguồn thật của profile là bảng bot_profiles trên PostgreSQL
    (persistent qua redeploy, không phụ thuộc Railway volume). Hàm này reconcile CẢ HAI —
    DB là chính, config.json chỉ giữ để fallback khi DB down.
    """
    admin_id = str(config.get("admin_telegram_id", "")).strip()
    if not admin_id or admin_id.startswith("NHAP"):
        return False

    if _DB_AVAILABLE and _db.is_available():
        try:
            if _db.find_profile(admin_id) is None:
                _db.create_profile(
                    admin_id, "Harvey", _ADMIN_PROFILE_SEED["watched_funds"], is_admin=True
                )
                log.info(f"[reconcile] Tạo profile admin Harvey trong DB ({admin_id})")
        except Exception as e:
            log.warning(f"[reconcile] DB lỗi, dùng config.json: {e}")

    profiles = config.setdefault("profiles", [])
    admin = None
    for p in profiles:
        if str(p.get("telegram_id", "")).strip() == admin_id:
            admin = p
            break

    changed = False
    if admin is None:
        admin = {
            "name": "Harvey", "telegram_id": admin_id,
            "watched_funds": list(_ADMIN_PROFILE_SEED["watched_funds"]),
            "portfolio": [dict(h) for h in _ADMIN_PROFILE_SEED["portfolio"]],
        }
        profiles.append(admin)
        changed = True
        log.info(f"[reconcile] Tạo profile admin Harvey ({admin_id})")

    return changed


# ── Trade wizard helpers ───────────────────────────────────────────────────────

def _handle_callback(token: str, chat_id: str, data: str, profile: dict | None, config: dict) -> None:
    """Xử lý inline keyboard callback từ wizard /buy /sell."""
    if data == "trade_cancel":
        _TRADE_SESSIONS.pop(chat_id, None)
        tg_send(token, chat_id, "❌ Đã huỷ giao dịch.")
        return

    if data.startswith("buyplan:"):
        plan_key = data.split(":", 1)[1]
        if plan_key not in PRO_PLANS:
            tg_send(token, chat_id, "⚠️ Gói không hợp lệ, dùng /buy_pro để chọn lại.")
            return
        _send_stars_invoice(token, chat_id, plan_key)
        return

    if data.startswith("nav_confirm:"):
        # nav_confirm:FUND:DATE:manual|fetch  — chỉ admin
        admin_id = str(load_config().get("admin_telegram_id", ""))
        if chat_id != admin_id:
            tg_send(token, chat_id, "⚠️ Chỉ admin có quyền xác nhận NAV.")
            return
        parts_c = data.split(":")
        if len(parts_c) < 4:
            return
        _, fund_code, nav_date_s, choice = parts_c[0], parts_c[1], parts_c[2], parts_c[3]
        if not (_DB_AVAILABLE and _db.is_available()):
            tg_send(token, chat_id, "⚠️ DB không khả dụng.")
            return
        ok = _db.resolve_nav_confirm(fund_code, nav_date_s, choice)
        if ok:
            label = "Manual (user nhập)" if choice == "manual" else "Fetch (API)"
            tg_send(token, chat_id,
                    f"✅ Đã xác nhận <code>{fund_code}</code> ngày <b>{nav_date_s}</b>\n"
                    f"Nguồn được chọn: <b>{label}</b> — đã khóa (confirmed).")
        else:
            tg_send(token, chat_id,
                    f"⚠️ Không tìm thấy pending_confirm cho {fund_code} {nav_date_s}.")
        return

    if data.startswith("trade_confirm:"):
        # trade_confirm:FUND:type:units:amount:date
        _TRADE_SESSIONS.pop(chat_id, None)
        parts_c = data.split(":")
        if len(parts_c) < 6:
            tg_send(token, chat_id, "⚠️ Dữ liệu xác nhận không hợp lệ.")
            return
        _, fund_code, tx_type, units_s, amount_s, order_date_s = parts_c[:6]
        if not profile:
            tg_send(token, chat_id, "⚠️ Không tìm thấy profile.")
            return
        try:
            units  = float(units_s)
            amount = float(amount_s)
            order_date = date.fromisoformat(order_date_s)
        except (ValueError, TypeError) as e:
            tg_send(token, chat_id, f"⚠️ Lỗi dữ liệu: {e}")
            return
        _cmd_add_trade(token, chat_id, profile, fund_code, tx_type, units, amount, order_date)
        return

    if not data.startswith("trade:"):
        return
    parts = data.split(":")
    if len(parts) < 3:
        return
    _, tx_type, fund_code = parts[0], parts[1], parts[2]

    if not profile:
        tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký. Gõ /register Tên để đăng ký.")
        return

    watched = profile.get("watched_funds", [])
    if fund_code not in watched:
        tg_send(token, chat_id, f"⚠️ <code>{fund_code}</code> không có trong danh mục của bạn.")
        return

    # Lấy NAV hiện tại để gợi ý
    cfg_funds  = config.get("funds", {})
    nav_hint   = ""
    try:
        pts = get_nav_series(fund_code, cfg_funds.get(fund_code, {}), config)
        if pts:
            latest_nav = pts[-1]["nav"]
            nav_hint = f"\n💡 NAV mới nhất: <b>{latest_nav:,.0f}đ</b>/CCQ"
    except Exception:
        pass

    action = "Mua" if tx_type == "buy" else "Bán"
    fund_name = cfg_funds.get(fund_code, {}).get("name", fund_code)

    _TRADE_SESSIONS[chat_id] = {
        "step": "await_units",
        "fund": fund_code,
        "type": tx_type,
        "units": None,
        "amount": None,
        "date": date.today().isoformat(),
    }

    tg_send(token, chat_id, (
        f"{'🟢' if tx_type == 'buy' else '🔴'} <b>{action}: {fund_code}</b>\n"
        f"{fund_name}{nav_hint}\n\n"
        f"Bước 1/2 — Nhập <b>số chứng chỉ quỹ (CCQ)</b>:\n"
        f"<i>Ví dụ: 487.21</i>\n\n"
        f"(Gõ /cancel để huỷ)"
    ))


def _handle_trade_wizard_text(token: str, chat_id: str, text: str, profile: dict | None, config: dict) -> None:
    """Xử lý input text khi đang trong trade wizard session."""
    sess = _TRADE_SESSIONS.get(chat_id)
    if not sess:
        return

    if text.strip().lower() in ("/cancel", "cancel", "huỷ", "huy"):
        del _TRADE_SESSIONS[chat_id]
        tg_send(token, chat_id, "❌ Đã huỷ giao dịch.")
        return

    fund_code = sess["fund"]
    tx_type   = sess["type"]
    action    = "Mua" if tx_type == "buy" else "Bán"

    if sess["step"] == "await_units":
        try:
            val = float(text.replace(",", "").replace(".", ".", 1).replace(",", ""))
            val = float(text.replace(",", ""))
            if val <= 0:
                raise ValueError
        except ValueError:
            tg_send(token, chat_id, "⚠️ Số CCQ không hợp lệ. Nhập số dương (vd: 487.21):")
            return
        sess["units"] = val
        sess["step"]  = "await_amount"
        tg_send(token, chat_id, (
            f"Bước 2/2 — Nhập <b>tổng số tiền (VNĐ)</b>:\n"
            f"<i>Ví dụ: 15000000</i>\n\n"
            f"(Không cần dấu phẩy, gõ /cancel để huỷ)"
        ))
        return

    if sess["step"] == "await_amount":
        try:
            val = float(text.replace(",", "").replace(".", "").replace(" ", ""))
            if val <= 0:
                raise ValueError
        except ValueError:
            tg_send(token, chat_id, "⚠️ Số tiền không hợp lệ. Nhập số VNĐ dương (vd: 15000000):")
            return
        sess["amount"] = val
        sess["step"]   = "confirm"

        units       = sess["units"]
        nav_implied = val / units
        cfg_funds   = config.get("funds", {})
        fund_name   = cfg_funds.get(fund_code, {}).get("name", fund_code)

        # Confirm với nút bấm
        kb = [
            [
                {"text": "✅ Xác nhận", "callback_data": f"trade_confirm:{fund_code}:{tx_type}:{units}:{val}:{sess['date']}"},
                {"text": "❌ Huỷ",      "callback_data": "trade_cancel"},
            ]
        ]
        tg_send_keyboard(token, chat_id, (
            f"{'🟢' if tx_type == 'buy' else '🔴'} <b>Xác nhận giao dịch</b>\n"
            f"──────────────\n"
            f"Loại: <b>{action}</b>\n"
            f"Quỹ: <b>{fund_code}</b> — {fund_name}\n"
            f"Số CCQ: <b>{units:,.2f}</b>\n"
            f"Tổng tiền: <b>{val:,.0f}đ</b>\n"
            f"NAV thực hiện: ~<b>{nav_implied:,.0f}đ</b>/CCQ\n"
            f"Ngày: <b>{sess['date']}</b>"
        ), kb)


def command_handler():
    offset = 0
    check_rate = _make_rate_checker()
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

                # ── Callback query (inline keyboard button tap) ──────────────
                cbq = upd.get("callback_query")
                if cbq:
                    tg_answer_callback(token, cbq["id"])
                    cbq_chat  = str(cbq["message"]["chat"]["id"])
                    cbq_data  = cbq.get("data", "")
                    cbq_prof  = find_profile_by_chat(config, cbq_chat)
                    try:
                        _handle_callback(token, cbq_chat, cbq_data, cbq_prof, config)
                    except Exception as _cbe:
                        log.error(f"[CALLBACK] {_cbe}", exc_info=True)
                    continue

                # ── Pre-checkout query (PAY-002: Stars payment confirm) ──────
                pq = upd.get("pre_checkout_query")
                if pq:
                    _handle_pre_checkout(token, pq)
                    continue

                msg    = upd.get("message") or upd.get("edited_message") or {}
                if not msg:
                    continue
                chat_id = str(msg["chat"]["id"])

                # ── Successful payment (PAY-003: upgrade tier) ───────────────
                if msg.get("successful_payment"):
                    try:
                        _handle_successful_payment(token, chat_id, msg)
                    except Exception as _pe:
                        log.error(f"[PAY] successful_payment error: {_pe}", exc_info=True)
                    continue

                text    = msg.get("text", "").strip()
                parts   = text.split()  # luôn định nghĩa sẵn, tránh NameError
                cmd     = parts[0].lower().split("@")[0] if parts else ""
                log.info(f"[CMD] {cmd!r} from chat {chat_id}")

                # ── Rate limit: tối đa 10 request/phút mỗi chat_id ──────────
                if cmd.startswith("/") and not check_rate(chat_id):
                    log.warning(f"[RATE-LIMIT] {chat_id} vượt hạn mức, bỏ qua {cmd!r}")
                    continue

                profile = find_profile_by_chat(config, chat_id)

                # ── Trade wizard: intercept free-text nếu đang trong session ──
                if chat_id in _TRADE_SESSIONS and not cmd.startswith("/"):
                    try:
                        _handle_trade_wizard_text(token, chat_id, text, profile, config)
                    except Exception as _we:
                        log.error(f"[WIZARD] {_we}", exc_info=True)
                    continue

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
                        # Nguồn chính: bảng bot_profiles trên PostgreSQL — persistent qua redeploy.
                        # Fallback: config.json (nếu DB tạm thời không khả dụng).
                        db_ok = False
                        if _DB_AVAILABLE and _db.is_available():
                            try:
                                _db.create_profile(chat_id, reg_name, default_funds)
                                db_ok = True
                            except Exception as e:
                                log.error(f"[REGISTER] DB lỗi, fallback config.json: {e}")
                        if not db_ok:
                            new_p = {"name": reg_name, "telegram_id": chat_id, "watched_funds": default_funds}
                            cfg_w.setdefault("profiles", []).append(new_p)
                            save_config(cfg_w)
                        log.info(f"[REGISTER] New profile: {reg_name} ({chat_id}) db={db_ok}")
                        tg_send(token, chat_id, (f"✅ <b>Tài khoản đã tạo!</b>\n\nTên: <b>{reg_name}</b>\nChat ID: <code>{chat_id}</code>\nQuỹ theo dõi: {', '.join(default_funds)}\n\nGõ /app để mở Mini App — xem danh mục, tín hiệu, giao dịch."))
                        admin_id = cfg_w.get("admin_telegram_id", "")
                        if admin_id and admin_id != chat_id:
                            total_profiles = len(get_profiles(cfg_w))
                            tg_send(token, admin_id, (f"🔔 <b>User mới đăng ký</b>\nTên: <b>{reg_name}</b>\nChat ID: <code>{chat_id}</code>\nTổng profiles: {total_profiles}"))
                        continue

                    if cmd in ("/start", "/help"):
                        profile_note = (f"\n\n✅ Xin chào <b>{profile['name']}</b>! Bot đã nhận diện bạn." if profile else f"\n\n👤 Bạn chưa có tài khoản. Gõ:\n<code>/register Tên Của Bạn</code>\nđể tạo tài khoản.")
                        tg_send(token, chat_id, (
                            "👋 <b>Quỹ Tracker Pro Bot</b>\n\n"
                            "📱 /app — Mở Mini App: danh mục, NAV, tín hiệu, nghiên cứu 5 trường phái, "
                            "giao dịch, DCA, lịch sử — <b>tất cả trong Mini App</b>\n\n"
                            "<b>Tài khoản:</b>\n"
                            "✍️ /register [tên] — Tạo tài khoản\n"
                            "🪪 /getid — Xem Chat ID\n\n"
                            "⭐ /buy_pro — Nâng cấp Pro (chọn gói tháng/quý/nửa năm/năm)\n\n"
                            "🔔 <b>Tự động:</b>\n"
                            "• Sáng T2–T6: báo cáo NAV + tín hiệu danh mục\n"
                            "• Cảnh báo ngay khi tín hiệu MUA/BÁN thay đổi\n\n"
                            "<i>Bot không cung cấp khuyến nghị đầu tư.</i>"
                        ) + profile_note)

                    elif cmd in ("/nav", "/navall", "/signal"):
                        tg_send(token, chat_id,
                            "📱 Xem tín hiệu và NAV đầy đủ trong <b>Mini App</b>.\n"
                            "Gõ /app để mở.")

                    elif cmd == "/portfolio":
                        if not profile:
                            tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên</code> để đăng ký.")
                            continue
                        # Dùng config.json portfolio (đầy đủ avg_cost + units cho tất cả mã)
                        port_codes = {h["code"] for h in profile.get("portfolio", []) if h.get("units", 0) > 0}
                        if not port_codes:
                            port_codes = set(profile.get("watched_funds", []))
                        nav_data_port = fetch_all(config, port_codes)
                        tg_send(token, chat_id, msg_portfolio(profile, nav_data_port))

                    elif cmd in ("/add-trade", "/buy", "/sell"):
                        tg_send(token, chat_id,
                            "📱 Giao dịch được quản lý trong <b>Mini App</b>.\n"
                            "Gõ /app để mở.")

                    elif cmd in ("/explain", "/research", "/explain2", "/rsi", "/macd", "/bb",
                                  "/stoch", "/atr", "/sharpe", "/momentum", "/mom", "/mpt",
                                  "/kelly", "/riskparity", "/rp", "/valueinvesting",
                                  "/contrarian", "/momentuminvesting", "/dcainvesting", "/learn"):
                        pass  # Đã bỏ — không còn hỗ trợ


                    elif cmd in ("/dca", "/funds", "/watch", "/unwatch"):
                        tg_send(token, chat_id,
                            "📱 Chức năng này đã chuyển vào <b>Mini App</b>.\n"
                            "Gõ /app để mở.")

                    elif cmd == "/admin":
                        admin_id = str(config.get("admin_telegram_id", "")).strip()
                        if not admin_id or chat_id != admin_id:
                            tg_send(token, chat_id, "⛔ Lệnh chỉ dành cho admin.")
                            continue
                        sub = text.split()[1].lower() if len(text.split()) > 1 else ""
                        if sub == "users":
                            profiles_list = get_profiles(config)
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
                            deleted = False
                            if _DB_AVAILABLE and _db.is_available():
                                try:
                                    deleted = _db.delete_profile(target_id)
                                except Exception as e:
                                    log.error(f"[admin kick] DB lỗi: {e}")
                            cfg_w = load_config()
                            before = len(cfg_w.get("profiles", []))
                            cfg_w["profiles"] = [p for p in cfg_w.get("profiles", []) if str(p.get("telegram_id")) != target_id]
                            if len(cfg_w["profiles"]) < before:
                                save_config(cfg_w)
                                deleted = True
                            if deleted:
                                tg_send(token, chat_id, f"✅ Đã xóa profile <code>{target_id}</code>")
                            else:
                                tg_send(token, chat_id, f"⚠️ Không tìm thấy <code>{target_id}</code>")
                        elif sub == "broadcast" and len(text.split()) > 2:
                            bcast_msg = " ".join(text.split()[2:])
                            sent_count = 0
                            for p in get_profiles(config):
                                tg = str(p.get("telegram_id", ""))
                                if tg.lstrip("-").isdigit():
                                    if tg_send(token, tg, f"📢 <b>Thông báo</b>\n\n{bcast_msg}"):
                                        sent_count += 1
                            tg_send(token, chat_id, f"✅ Đã gửi tới {sent_count} users")
                        elif sub == "fixportfolio" and len(text.split()) >= 4:
                            # /admin fixportfolio TCBF avg_cost [units]
                            parts_fp = text.split()
                            fp_code = parts_fp[2].upper()
                            try:
                                fp_cost = float(parts_fp[3])
                                fp_units = float(parts_fp[4]) if len(parts_fp) > 4 else None
                            except ValueError:
                                tg_send(token, chat_id, "⚠️ avg_cost và units phải là số.")
                                continue
                            cfg_w = load_config()
                            admin_id2 = str(cfg_w.get("admin_telegram_id", "")).strip()
                            admin_p = next((p for p in cfg_w.get("profiles", []) if str(p.get("telegram_id")) == admin_id2), None)
                            if not admin_p:
                                tg_send(token, chat_id, "⚠️ Không tìm thấy profile admin trong config.")
                                continue
                            pf = admin_p.get("portfolio", [])
                            entry = next((e for e in pf if e.get("code") == fp_code), None)
                            if entry:
                                old_cost = entry.get("avg_cost")
                                old_units = entry.get("units")
                                entry["avg_cost"] = fp_cost
                                if fp_units is not None:
                                    entry["units"] = fp_units
                                save_config(cfg_w)
                                reply = (
                                    f"✅ Đã cập nhật <b>{fp_code}</b>:\n"
                                    f"  avg_cost: {old_cost:,.0f} → {fp_cost:,.0f}\n"
                                )
                                if fp_units is not None:
                                    reply += f"  units: {old_units} → {fp_units}\n"
                                tg_send(token, chat_id, reply)
                            else:
                                tg_send(token, chat_id, f"⚠️ Không tìm thấy <code>{fp_code}</code> trong portfolio admin.")

                        else:
                            tg_send(token, chat_id, (
                                "🔧 <b>Admin Commands</b>\n\n"
                                "<code>/admin users</code> — Xem tất cả users\n"
                                "<code>/admin kick CHATID</code> — Xóa user\n"
                                "<code>/admin broadcast TIN NHẮN</code> — Broadcast tới tất cả\n"
                                "<code>/admin fixportfolio MÃ avg_cost [units]</code> — Sửa portfolio\n"
                                "\n📱 Cập nhật TCBS token: dùng <b>Mini App (tab Admin))"
                            ))

                    elif cmd == "/morning":
                        tg_send(token, chat_id,
                            "📱 Xem báo cáo NAV + tín hiệu mới nhất trong <b>Mini App</b>.\n"
                            "Gõ /app để mở. (Bot vẫn tự động gửi báo cáo sáng T2–T6 lúc 08:00)")

                    elif cmd == "/evening":
                        tg_send(token, chat_id,
                            "📱 Xem báo cáo NAV + danh mục mới nhất trong <b>Mini App</b>.\n"
                            "Gõ /app để mở. (Bot vẫn tự động gửi báo cáo chiều T2–T6 lúc 17:30)")

                    elif cmd == "/app" or cmd == "/miniapp":
                        _cmd_app(token, chat_id, profile)

                    elif cmd == "/beta":
                        _cmd_beta(token, chat_id)

                    elif cmd == "/buy_pro":
                        _cmd_buy_pro(token, chat_id, profile)

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
# PAYMENT — TELEGRAM STARS
# ═══════════════════════════════════════

from pricing import PRO_PLANS, PLAN_ORDER, DEFAULT_PLAN, resolve_plan


def _parse_plan_from_payload(payload: str) -> dict:
    """payload dạng 'pro:<plan_key>:<chat_id>' (mới) hoặc 'pro_30d:<chat_id>' (cũ,
    trước khi có multi-tier — coi như gói tháng để không phá invoice đang bay)."""
    parts = payload.split(":")
    if len(parts) >= 3 and parts[0] == "pro":
        return resolve_plan(parts[1])
    return PRO_PLANS[DEFAULT_PLAN]


def _handle_pre_checkout(token: str, pq: dict) -> None:
    """PAY-002: Xác nhận pre_checkout_query trong <10s — bắt buộc để payment proceed."""
    pq_id = pq.get("id", "")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/answerPreCheckoutQuery",
            json={"pre_checkout_query_id": pq_id, "ok": True},
            timeout=8
        )
        if not r.ok:
            log.error(f"[PAY] answerPreCheckoutQuery fail: {r.text[:200]}")
        else:
            log.info(f"[PAY] pre_checkout OK for query {pq_id}")
    except Exception as e:
        log.error(f"[PAY] answerPreCheckoutQuery exception: {e}")


def _handle_successful_payment(token: str, chat_id: str, msg: dict) -> None:
    """PAY-003: Nâng cấp tier=pro theo gói đã chọn sau khi Stars payment thành công.
    Dùng extend_pro (cộng dồn) thay vì set_tier(now+days) để user gia hạn sớm
    không bị mất số ngày Pro còn lại."""
    sp         = msg["successful_payment"]
    stars      = sp.get("total_amount", 0)
    charge_id  = sp.get("telegram_payment_charge_id", "")
    payload    = sp.get("invoice_payload", "")
    plan       = _parse_plan_from_payload(payload)
    days       = plan["days"]
    log.info(f"[PAY] successful_payment: chat={chat_id} stars={stars} charge={charge_id} payload={payload} plan={plan['label']}")

    expires_at = None
    try:
        if _DB_AVAILABLE and _db.is_available():
            # GOV-003: Telegram có thể gửi lại successful_payment nếu bot không ACK kịp —
            # chặn xử lý trùng bằng charge_id (unique per transaction từ Telegram).
            if not _db.record_payment_once("stars", charge_id, chat_id):
                log.warning(f"[PAY][DUP] Stars charge={charge_id} đã xử lý trước đó — bỏ qua extend_pro")
                _db.log_audit(None, "duplicate_payment_blocked", "processed_payments", charge_id,
                               note=f"stars chat={chat_id} stars={stars}")
                admin_id = str(load_config().get("admin_telegram_id", "")).strip()
                if admin_id:
                    tg_send(token, admin_id, f"⚠️ <b>Thanh toán Stars trùng lặp bị chặn</b>\nchat={chat_id} charge={charge_id}")
                return
            result = _db.extend_pro(chat_id, days, note=f"stars {plan['label']} ({stars}⭐)")
            expires_at = result.get("pro_expires_at")
            log.info(f"[PAY] tier=pro extended {days}d for {chat_id}, expires {expires_at}")
            try:
                _db.grant_referral_purchase_bonus(chat_id)
            except Exception as _rbe:
                log.warning(f"[PAY] grant_referral_purchase_bonus lỗi: {_rbe}")
        else:
            log.error(f"[PAY] DB unavailable — cannot persist tier for {chat_id}")
    except Exception as e:
        log.error(f"[PAY] extend_pro error: {e}", exc_info=True)

    exp_str = expires_at.strftime("%d/%m/%Y") if expires_at else "?"
    tg_send(token, chat_id, (
        f"🌟 <b>Chào mừng bạn đến với Fund Tracker Pro!</b>\n\n"
        f"✅ Thanh toán {stars} ⭐ Stars thành công — gói <b>{plan['label']}</b>\n"
        f"📅 Gói Pro có hiệu lực đến: <b>{exp_str}</b>\n\n"
        f"🔓 <b>Đã mở khóa:</b>\n"
        f"• Theo dõi không giới hạn số quỹ\n"
        f"• Phân tích chuyên sâu RSI/MACD/Sharpe/Sortino\n"
        f"• Phân tích giá vàng\n"
        f"• Cảnh báo tự động\n"
        f"• Dự báo NAV T+2 (sắp ra mắt)\n\n"
        f"Gõ /app để mở Mini App ngay. 🚀"
    ))


def _cmd_buy_pro(token: str, chat_id: str, profile: Optional[dict]) -> None:
    """PAY-001: Hiện menu chọn gói Premium (tháng/quý/nửa năm/năm), sau đó gửi
    Telegram Stars invoice cho gói được chọn qua callback buyplan:<key>."""
    # Kiểm tra tier hiện tại
    if _DB_AVAILABLE and _db.is_available():
        try:
            tier_info = _db.get_tier(chat_id)
            if tier_info.get("tier") == "pro":
                exp = tier_info.get("pro_expires_at")
                exp_str = exp.strftime("%d/%m/%Y") if exp else "vĩnh viễn"
                tg_send(token, chat_id,
                    f"✅ Bạn đã là thành viên <b>Pro</b> rồi!\n"
                    f"📅 Hiệu lực đến: <b>{exp_str}</b>\n\n"
                    f"Muốn gia hạn thêm? Chọn gói bên dưới — số ngày sẽ được cộng dồn.")
            # Không return — vẫn cho gia hạn sớm (extend_pro cộng dồn, không mất ngày còn lại)
        except Exception:
            pass

    buttons = []
    for key in PLAN_ORDER:
        p = PRO_PLANS[key]
        tag = " 🏆 TIẾT KIỆM NHẤT" if key == "y1" else (f" (-{p['discount_pct']}%)" if p["discount_pct"] else "")
        buttons.append([{
            "text": f"{p['label']} — {p['stars']}⭐{tag}",
            "callback_data": f"buyplan:{key}",
        }])
    tg_send_keyboard(token, chat_id, (
        "🌟 <b>Chọn gói Fund Tracker Pro</b>\n\n"
        "Trả theo năm giúp bạn tiết kiệm nhất — giá/tháng giảm dần theo kỳ hạn dài hơn."
    ), buttons)


def _send_stars_invoice(token: str, chat_id: str, plan_key: str) -> None:
    """Gửi Stars invoice cho gói plan_key đã chọn (từ menu /buy_pro hoặc Mini App)."""
    plan = resolve_plan(plan_key)
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendInvoice",
            json={
                "chat_id": chat_id,
                "title": "Fund Tracker Pro",
                "description": (
                    f"{plan['label']}: theo dõi không giới hạn quỹ, "
                    f"phân tích sâu RSI/MACD/Sharpe/Sortino, cảnh báo tự động, "
                    f"phân tích giá vàng."
                ),
                "payload": f"pro:{plan_key}:{chat_id}",
                "currency": "XTR",
                "prices": [{"label": f"Fund Tracker Pro — {plan['label']}", "amount": plan["stars"]}],
            },
            timeout=15
        )
        if not r.ok:
            err = r.json().get("description", r.text[:200])
            log.error(f"[PAY] sendInvoice fail: {err}")
            tg_send(token, chat_id, "⚠️ Không thể tạo invoice. Vui lòng thử lại sau.")
        else:
            log.info(f"[PAY] sendInvoice ({plan_key}) sent to {chat_id}")
    except Exception as e:
        log.error(f"[PAY] sendInvoice exception: {e}")
        tg_send(token, chat_id, "⚠️ Lỗi kết nối. Vui lòng thử lại sau.")


# ═══════════════════════════════════════
# MINI APP
# ═══════════════════════════════════════

def _get_miniapp_url(user_id: int, beta: bool = False) -> str:
    """Tạo URL mini app với user_id embed. beta=True → thêm &beta=1, miniapp sẽ
    dùng tài khoản test cô lập (telegram_id âm) thay vì tài khoản thật, nhưng
    vẫn đọc chung NAV/tín hiệu/dự báo thật (xem _effective_tg_id trong
    miniapp_server.py)."""
    base = os.environ.get(
        "MINIAPP_URL",
        f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost:8443')}"
    )
    url = f"{base}?user_id={user_id}"
    return f"{url}&beta=1" if beta else url


def _cmd_beta(token: str, chat_id: int) -> None:
    """/beta — CHỈ admin. Mở Mini App ở chế độ test: tài khoản/portfolio/giao dịch
    hoàn toàn cô lập khỏi tài khoản thật (lưu dưới telegram_id âm), nhưng NAV,
    tín hiệu, giá vàng, dự báo T+2 vẫn dùng chung dữ liệu thật — để admin test
    tính năng mới mà không sợ ảnh hưởng dữ liệu production của chính mình."""
    admin_id = str(load_config().get("admin_telegram_id", ""))
    if not admin_id or str(chat_id) != admin_id:
        tg_send(token, str(chat_id), "⚠️ Lệnh này chỉ dành cho admin.")
        return
    url = _get_miniapp_url(chat_id, beta=True)
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat_id,
            "text": (
                "🧪 <b>BETA MODE</b>\n\n"
                "Tài khoản/portfolio/giao dịch trong chế độ này hoàn toàn tách biệt "
                "khỏi tài khoản thật của bạn (không ảnh hưởng dữ liệu production). "
                "NAV, tín hiệu, giá vàng, dự báo T+2 vẫn là dữ liệu thật để test sát thực tế."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "🧪 Mở Beta Mode", "web_app": {"url": url}}
            ]]},
        }, timeout=15)
        if not r.ok:
            log.error(f"[/beta] Telegram reject web_app button: {r.json().get('description', r.text[:200])}")
    except Exception as e:
        log.error(f"[/beta] {e}")


def _cmd_app(token: str, chat_id: int, profile: Optional[dict]):
    if not profile:
        tg_send(token, chat_id, "⚠️ Bạn chưa đăng ký.\nGõ <code>/register Tên Của Bạn</code> để đăng ký.")
        return
    url = _get_miniapp_url(chat_id)
    # Thử gửi WebApp button trước
    tg_url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(tg_url, json={
            "chat_id": chat_id,
            "text": "📱 <b>Fund Tracker Pro</b>\n\nMở app để xem danh mục, tín hiệu, DCA và thêm giao dịch:",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "📊 Mở Fund Tracker Pro", "web_app": {"url": url}}
            ]]},
        }, timeout=15)
        if r.ok:
            return
        err = r.json().get("description", r.text[:200])
        log.error(f"[/app] Telegram reject web_app button: {err}")
    except Exception as e:
        log.error(f"[/app] {e}")
    # Fallback: gửi link thường
    tg_send(token, str(chat_id),
            f"📱 <b>Fund Tracker Pro</b>\n\n"
            f'<a href="{url}">Mở Mini App</a>\n\n'
            f"<i>Hoặc copy link: {url}</i>")


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
    # Reconcile profile admin (Harvey): đảm bảo đủ 5 quỹ + portfolio, ghi vào DB (chính)
    # + config.json (fallback) — xem reconcile_admin_profile() cho chi tiết.
    if reconcile_admin_profile(config):
        save_config(config)
        log.info("[reconcile] config.json đã cập nhật profile admin")
    startup_profiles = get_profiles(config)
    log.info(f"[STARTUP] {len(startup_profiles)} profiles đã đăng ký (nguồn: "
             f"{'DB' if _DB_AVAILABLE and _db.is_available() else 'config.json'}) — "
             f"{[p.get('name') for p in startup_profiles]}")
    sched  = config.get("schedule", {})
    t_morn = sched.get("morning_report", "08:00")
    t_eve  = sched.get("evening_report", "17:30")
    t_int  = int(sched.get("signal_check_interval_minutes", 60))

    log.info(f"Lịch: sáng={t_morn}, chiều={t_eve}, signal_check={t_int}m")
    log.info(f"Tất cả quỹ theo dõi: {sorted(all_watched_codes(config))}")

    for day in (schedule.every().monday, schedule.every().tuesday,
                schedule.every().wednesday, schedule.every().thursday,
                schedule.every().friday):
        day.at(t_morn).do(job_morning)
        day.at(t_eve).do(job_evening)

    schedule.every(t_int).minutes.do(job_check_signals)
    schedule.every(t_int).minutes.do(job_nav_change_alert)
    schedule.every().day.at("09:00").do(job_backfill_settlement)
    schedule.every().day.at("09:00").do(job_dca_reminder)
    schedule.every().day.at("18:30").do(job_harvest_nav)
    schedule.every().day.at("18:31").do(job_t2_predict)
    schedule.every().day.at("18:32").do(job_t2_score)
    schedule.every().day.at("18:33").do(job_check_alerts)
    # Second pass: sửa giá trị provisional sau khi TCinvest finalize NAV (~19:30-20:00)
    schedule.every().day.at("20:00").do(job_harvest_nav)
    # GOV-008/T2-014: re-verify 3 lớp T+1/T+8/T+31 — chạy sau cả 2 lần harvest,
    # cho NAV hôm nay/gần đây đủ thời gian để TCBS tự sửa nếu là số tạm tính
    schedule.every().day.at("21:00").do(job_nav_reverify)
    schedule.every().day.at("21:30").do(job_nav_integrity_check)
    schedule.every().sunday.at("02:00").do(job_t2_retrain)
    schedule.every(30).days.at("03:00").do(job_t2_reweight)
    schedule.every().day.at("03:30").do(job_backup_db)
    schedule.every().monday.at("04:00").do(job_nav_source_audit)
    schedule.every().day.at("07:30").do(job_check_tcbs_token)
    # job_watchdog_ping đã bỏ — tin nhắn "Bot alive" không cần thiết

    # Start Telegram Mini App HTTP server TRƯỚC để Railway health check pass
    try:
        from miniapp_server import start_in_thread as _start_miniapp
        _start_miniapp()
        _miniapp_url = _get_miniapp_url(0).replace("?user_id=0", "")
        log.info(f"[miniapp] Server started on :{os.environ.get('PORT', os.environ.get('PORT_MINIAPP', 8443))}")
        log.info(f"[miniapp] Public URL = {_miniapp_url}")
        if "localhost" in _miniapp_url:
            log.warning("[miniapp] ⚠️ URL vẫn là localhost — cần đặt MINIAPP_URL hoặc RAILWAY_PUBLIC_DOMAIN trong Railway Variables")
    except Exception as _e:
        log.warning(f"[miniapp] Could not start mini app server: {_e}")

    # Chạy signal check khởi động ở background để không block HTTP server
    threading.Thread(target=job_check_signals, daemon=True, name="startup-signal-check").start()
    log.info("Chạy signal check khởi động (background)...")

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
