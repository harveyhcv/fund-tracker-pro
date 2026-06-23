#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — Local server cho Quỹ Tracker Dashboard
  • Serve static files (như http.server)
  • GET  /bot-config         → đọc config.json của bot
  • POST /bot-config         → lưu config.json của bot
  • GET  /nav-data           → đọc nav_data.json (NAV cache tách riêng)
  • POST /save-nav           → lưu NAV data vào nav_data.json (không còn patch HTML)
  • POST /refresh-nav        → fetch NAV từ fmarket/TCBS, lưu vào nav_data.json
  • POST /tcbs-auth/otp      → gửi OTP về SĐT (proxy → TCBS)
  • POST /tcbs-auth/verify   → xác nhận OTP, trả về token (proxy → TCBS)
  • GET  /core/status        → tổng quan DB (total, pending, stale funds)
  • GET  /core/gaps          → danh sách quỹ thiếu NAV hôm nay
  • GET  /core/nav?code=X    → full NAV history của quỹ X
  • POST /core/nav           → nhập NAV thủ công {fund_code, date, nav, note}
  • POST /core/verify        → verify records {fund_code, from_date, to_date}
"""

import http.server
import json
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

PORT          = 8080
BASE          = Path(__file__).parent                      # = dashboard/
ROOT          = BASE.parent                                # = Fund Tracker Pro/
BOT_CFG       = ROOT / "telegram-bot" / "config.json"
NAV_DATA_FILE = BASE / "nav_data.json"                     # NAV cache tách ra khỏi HTML
CORE_DB       = ROOT / "core_data" / "nav.db"             # Core NAV database
TCINVEST_JSON = ROOT / "scripts" / "tcinvest_nav_2026-06-21.json"  # Master NAV database
TRANSACTIONS_FILE = BASE / "transactions.json"            # Portfolio transactions

# Số điểm NAV giữ lại mỗi quỹ
NAV_KEEP_POINTS = 500

# ── Fund config cho /refresh-nav ──────────────────────────────
# fmarket_id: từ config.json (nguồn chính xác nhất)
# Quỹ TC (TCBF, TCFF, TCGF): TCBS only — fmarket_id=None
FUNDS_CONFIG = {
    "VCBFTBF": {"source": "fmarket", "fmarket_id": 31},
    "SSISCA":  {"source": "fmarket", "fmarket_id": 11},
    "VCBFBCF": {"source": "fmarket", "fmarket_id": 32},
    "TCBF":    {"source": "fmarket", "fmarket_id": 22, "tcbs_fallback": True},
    "TCFF":    {"source": "tcbs",    "fmarket_id": None, "tcbs_fallback": True},
    "TCGF":    {"source": "tcbs",    "fmarket_id": None, "tcbs_fallback": True},
}
# Ngày cuối cùng đã baked vào HIST.chart — chỉ fetch delta sau ngày này
HIST_CUTOFF = {code: "2026-06-23" for code in FUNDS_CONFIG}

FMARKET_URL = "https://api.fmarket.vn/res/product/get-nav-history"
FMARKET_HEADERS = {
    "Content-Type": "application/json",
    "Origin":       "https://fmarket.vn",
    "Referer":      "https://fmarket.vn/",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
TCBS_NAV_BASE = "https://apiextaws.tcbs.com.vn/fund/v1"

# ── TCBS auth endpoints (thử theo thứ tự) ─────────────────────
TCBS_OTP_ENDPOINTS = [
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/authentication",
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/otp-request",
]
TCBS_VERIFY_ENDPOINTS = [
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/authentication/otp",
    "https://apipubaws.tcbs.com.vn/oauth/v1/me/otp-verify",
]
TCBS_HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "Origin":       "https://tcinvest.tcbs.com.vn",
    "Referer":      "https://tcinvest.tcbs.com.vn/",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


# ── NAV fetch helpers (dùng trong /refresh-nav) ──────────────

def _fetch_fmarket_nav(fmarket_id: int, from_date: str = None) -> list:
    """Fetch lịch sử NAV từ fmarket.vn. Trả về list {date, nav}."""
    today_ymd = date.today().strftime("%Y%m%d")
    payload = {"isAllData": 1, "productId": fmarket_id, "fromDate": None, "toDate": today_ymd}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        FMARKET_URL, data=body,
        headers={**FMARKET_HEADERS, "Content-Length": str(len(body))},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data_resp = json.loads(r.read().decode())
        inner = data_resp.get("data") or {}
        if isinstance(inner, dict):
            navs = inner.get("navHistories") or []
        elif isinstance(inner, list):
            navs = inner
        else:
            navs = data_resp.get("navHistories") or []
        pts = []
        for n in navs:
            d = (n.get("navDate") or n.get("tradingDate") or n.get("date") or "")[:10]
            v_raw = n.get("nav") or n.get("navPerShare") or n.get("navValue") or 0
            try:
                v = float(v_raw)
            except (TypeError, ValueError):
                continue
            if d and v > 0:
                if from_date and d <= from_date:
                    continue
                pts.append({"date": d, "nav": v})
        return sorted(pts, key=lambda x: x["date"])
    except Exception as ex:
        print(f"[refresh-nav] fmarket id={fmarket_id}: {ex}", flush=True)
        return []


class _TcbsAuthError(Exception):
    """Raised khi TCBS trả về 401/403 — token hết hạn hoặc không hợp lệ."""
    pass


def _fetch_tcbs_nav(code: str, token: str = "", from_date: str = None) -> list:
    """Fetch lịch sử NAV từ TCBS. Trả về list {date, nav}.
    Raises _TcbsAuthError nếu TCBS trả 401/403 (token hết hạn).
    """
    start = from_date or "2023-01-01"
    today = date.today().isoformat()
    hdrs = {"Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    urls = [
        f"{TCBS_NAV_BASE}/fund-nav/{code}?startDate={start}&endDate={today}",
        f"{TCBS_NAV_BASE}/nav-history/{code}?page=0&size=600",
    ]
    auth_failed = False
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=12) as r:
                data_resp = json.loads(r.read().decode())
            navs = data_resp.get("data") or data_resp.get("navHistory") or data_resp.get("list") or []
            pts = []
            for n in navs:
                d = (n.get("navDate") or n.get("tradingDate") or n.get("date") or "")[:10]
                v_raw = n.get("nav") or n.get("navValue") or n.get("close") or 0
                try:
                    v = float(v_raw)
                except (TypeError, ValueError):
                    continue
                if d and v > 0:
                    if from_date and d <= from_date:
                        continue
                    pts.append({"date": d, "nav": v})
            if pts:
                return sorted(pts, key=lambda x: x["date"])
        except urllib.error.HTTPError as ex:
            if ex.code in (401, 403):
                auth_failed = True
                print(f"[refresh-nav] TCBS {code}: token hết hạn (HTTP {ex.code})", flush=True)
                break  # Không thử URL thứ 2 — cùng token sẽ fail
            print(f"[refresh-nav] TCBS {code} {url}: HTTP {ex.code}", flush=True)
        except Exception as ex:
            print(f"[refresh-nav] TCBS {code} {url}: {ex}", flush=True)
    if auth_failed:
        raise _TcbsAuthError(f"TCBS token không hợp lệ hoặc đã hết hạn cho {code}")
    return []


# ── Core DB helpers ───────────────────────────────────────────────────────────

def _core_db():
    """Trả về kết nối tới Core DB, hoặc None nếu DB chưa khởi tạo."""
    if not CORE_DB.exists():
        return None
    conn = sqlite3.connect(CORE_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5  # 0=Mon … 4=Fri


def _last_n_business_days(n: int) -> list[str]:
    days, cur = [], date.today()
    while len(days) < n:
        if _is_business_day(cur):
            days.append(cur.isoformat())
        cur -= timedelta(days=1)
    return days


def _json_resp(handler, data: dict, status: int = 200):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(body)


def _proxy_post(url: str, payload: dict) -> tuple[int, dict]:
    """POST tới URL bên ngoài, trả về (status_code, response_dict)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={**TCBS_HEADERS, "Content-Length": str(len(body))},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as ex:
        return 0, {"error": str(ex)}


class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    # ── CORS ──────────────────────────────────────────────────────
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/bot-config":
            self._get_bot_config()
        elif path == "/nav-data":
            self._get_nav_data()
        elif path == "/nav-json":
            self._get_nav_json()
        elif path == "/transactions":
            self._get_transactions()
        elif path == "/core/status":
            self._core_status()
        elif path == "/core/gaps":
            self._core_gaps()
        elif path == "/core/nav":
            self._core_get_nav()
        else:
            super().do_GET()

    def _get_bot_config(self):
        if not BOT_CFG.exists():
            _json_resp(self, {"ok": False, "error": "config.json không tồn tại"}, 404)
            return
        try:
            cfg = json.loads(BOT_CFG.read_text(encoding="utf-8"))
            safe = dict(cfg)
            if safe.get("bot_token") and not safe["bot_token"].startswith("NHAP"):
                safe["bot_token_set"] = True
                safe["bot_token"] = ""
            if safe.get("tcbs_token"):
                safe["tcbs_token_set"] = True
                safe["tcbs_token"] = ""
            _json_resp(self, {"ok": True, "config": safe})
        except Exception as e:
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    def _get_nav_json(self):
        """GET /nav-json — trả về tcinvest master NAV JSON (83K datapoints)."""
        if not TCINVEST_JSON.exists():
            _json_resp(self, {"error": "tcinvest_nav JSON chưa tồn tại. Chạy: python scripts/harvest_nav.py --no-db"}, 404)
            return
        try:
            data = json.loads(TCINVEST_JSON.read_text(encoding="utf-8"))
            _json_resp(self, data)
        except Exception as e:
            _json_resp(self, {"error": str(e)}, 500)

    def _get_transactions(self):
        """GET /transactions — trả về lịch sử giao dịch."""
        if not TRANSACTIONS_FILE.exists():
            _json_resp(self, {"ok": True, "transactions": []})
            return
        try:
            data = json.loads(TRANSACTIONS_FILE.read_text(encoding="utf-8"))
            _json_resp(self, {"ok": True, "transactions": data})
        except Exception as e:
            _json_resp(self, {"error": str(e)}, 500)

    def _handle_save_transaction(self, data: dict):
        """POST /transactions — thêm giao dịch mới vào transactions.json."""
        try:
            existing = []
            if TRANSACTIONS_FILE.exists():
                existing = json.loads(TRANSACTIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data  # Full replace
            else:
                existing.append(data)
            TRANSACTIONS_FILE.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"[transactions] ✓ Saved {len(existing)} transactions", flush=True)
            _json_resp(self, {"ok": True, "count": len(existing)})
        except Exception as e:
            print(f"[transactions] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    def _get_nav_data(self):
        """GET /nav-data — trả về nav_data.json (NAV cache tách riêng khỏi HTML)."""
        if not NAV_DATA_FILE.exists():
            _json_resp(self, {})
            return
        try:
            data = json.loads(NAV_DATA_FILE.read_text(encoding="utf-8"))
            _json_resp(self, data)
        except Exception as e:
            _json_resp(self, {"error": str(e)}, 500)

    # ── POST ──────────────────────────────────────────────────────
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        path   = self.path.split("?")[0]

        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        if path == "/save-nav":
            self._handle_save_nav(data)
        elif path == "/refresh-nav":
            self._handle_refresh_nav(data)
        elif path == "/bot-config":
            self._handle_save_bot_config(data)
        elif path == "/transactions":
            self._handle_save_transaction(data)
        elif path == "/tcbs-auth/otp":
            self._handle_tcbs_otp(data)
        elif path == "/tcbs-auth/verify":
            self._handle_tcbs_verify(data)
        elif path == "/save-core-data":
            self._handle_save_core_data(data)
        elif path == "/import-nav-excel":
            self._handle_import_nav_excel(data)
        elif path == "/core/nav":
            self._core_post_nav(data)
        elif path == "/core/verify":
            self._core_post_verify(data)
        else:
            self.send_response(404)
            self.end_headers()

    # ── /bot-config POST ─────────────────────────────────────────
    def _handle_save_bot_config(self, data: dict):
        try:
            if not BOT_CFG.exists():
                _json_resp(self, {"ok": False, "error": "config.json không tồn tại"}, 404)
                return
            existing = json.loads(BOT_CFG.read_text(encoding="utf-8"))
            merged = {**existing, **data}
            if not data.get("bot_token"):
                merged["bot_token"] = existing.get("bot_token", "")
            if not data.get("tcbs_token"):
                merged["tcbs_token"] = existing.get("tcbs_token", "")
            for k in ("bot_token_set", "tcbs_token_set"):
                merged.pop(k, None)
            BOT_CFG.write_text(
                json.dumps(merged, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"[bot-config] ✓ Đã lưu config.json", flush=True)
            _json_resp(self, {"ok": True})
        except Exception as e:
            print(f"[bot-config] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /tcbs-auth/otp POST ──────────────────────────────────────
    def _handle_tcbs_otp(self, data: dict):
        phone = data.get("phone", "").strip()
        if not phone:
            _json_resp(self, {"ok": False, "error": "Thiếu số điện thoại"}, 400)
            return
        print(f"[tcbs-auth] Gửi OTP → {phone}", flush=True)
        last_status, last_resp = 0, {}
        for url in TCBS_OTP_ENDPOINTS:
            status, resp = _proxy_post(url, {"mobile": phone})
            print(f"[tcbs-auth] OTP endpoint {url}: {status} {resp}", flush=True)
            last_status, last_resp = status, resp
            if status in (200, 201):
                _json_resp(self, {"ok": True, "data": resp, "endpoint": url})
                return
        _json_resp(self, {
            "ok": False,
            "error": f"TCBS trả về {last_status}",
            "detail": last_resp
        }, 502)

    # ── /tcbs-auth/verify POST ───────────────────────────────────
    def _handle_tcbs_verify(self, data: dict):
        phone = data.get("phone", "").strip()
        otp   = data.get("otp", "").strip()
        session_id = data.get("session_id", "")
        if not phone or not otp:
            _json_resp(self, {"ok": False, "error": "Thiếu phone hoặc OTP"}, 400)
            return
        print(f"[tcbs-auth] Xác nhận OTP: {phone} / {otp}", flush=True)
        payload = {"mobile": phone, "otp": otp}
        if session_id:
            payload["sessionId"] = session_id
        last_status, last_resp = 0, {}
        for url in TCBS_VERIFY_ENDPOINTS:
            status, resp = _proxy_post(url, payload)
            print(f"[tcbs-auth] Verify {url}: {status}", flush=True)
            last_status, last_resp = status, resp
            if status in (200, 201):
                token = (
                    resp.get("data", {}).get("access_token")
                    or resp.get("access_token")
                    or resp.get("token")
                    or resp.get("data", {}).get("token")
                    or ""
                )
                if token:
                    try:
                        if BOT_CFG.exists():
                            cfg = json.loads(BOT_CFG.read_text(encoding="utf-8"))
                            cfg["tcbs_token"] = token
                            BOT_CFG.write_text(
                                json.dumps(cfg, indent=2, ensure_ascii=False),
                                encoding="utf-8"
                            )
                            print(f"[tcbs-auth] ✓ Token đã lưu vào config.json", flush=True)
                    except Exception as ex:
                        print(f"[tcbs-auth] Lỗi lưu token: {ex}", flush=True)
                    _json_resp(self, {"ok": True, "token": token, "full": resp})
                    return
                else:
                    _json_resp(self, {"ok": False, "error": "Không tìm thấy token", "raw": resp})
                    return
        _json_resp(self, {
            "ok": False,
            "error": f"TCBS trả về {last_status}",
            "detail": last_resp
        }, 502)

    # ── /refresh-nav POST ────────────────────────────────────────
    def _handle_refresh_nav(self, data: dict):
        """Fetch NAV từ fmarket/TCBS trực tiếp, lưu vào nav_data.json.

        Body (tuỳ chọn):
          funds     : list mã quỹ cần refresh ["TCBF", ...] — mặc định tất cả
          from_date : "yyyy-mm-dd" — mặc định dùng HIST_CUTOFF mỗi quỹ
        """
        try:
            requested_funds = data.get("funds") or list(FUNDS_CONFIG.keys())
            # Đọc TCBS token từ config.json nếu có
            tcbs_token = ""
            if BOT_CFG.exists():
                try:
                    tcbs_token = json.loads(BOT_CFG.read_text(encoding="utf-8")).get("tcbs_token", "")
                except Exception:
                    pass

            print(f"[refresh-nav] Bắt đầu fetch {requested_funds} …", flush=True)
            incremental: dict = {}
            errors: dict = {}
            tcbs_token_expired: bool = False

            for code in requested_funds:
                cfg = FUNDS_CONFIG.get(code)
                if not cfg:
                    errors[code] = "unknown fund"
                    continue
                cutoff = HIST_CUTOFF.get(code, "")

                pts = []
                # Bước 1: thử fmarket nếu có fmarket_id
                if cfg.get("fmarket_id"):
                    pts = _fetch_fmarket_nav(cfg["fmarket_id"], from_date=cutoff)
                # Bước 2: TCBS fallback (khi source=tcbs hoặc fmarket fail với tcbs_fallback=True)
                if not pts and (cfg["source"] == "tcbs" or cfg.get("tcbs_fallback")):
                    try:
                        pts = _fetch_tcbs_nav(code, tcbs_token, from_date=cutoff)
                    except _TcbsAuthError:
                        errors[code] = "tcbs_token_expired"
                        tcbs_token_expired = True
                        print(f"[refresh-nav] ❌ {code}: TCBS token hết hạn", flush=True)
                        continue

                if pts:
                    incremental[code] = pts
                    print(f"[refresh-nav] ✓ {code}: {len(pts)} điểm delta (sau {cutoff})", flush=True)
                else:
                    errors[code] = "no data returned"
                    print(f"[refresh-nav] ⚠ {code}: không có dữ liệu mới", flush=True)

            if not incremental:
                _json_resp(self, {
                    "ok": False,
                    "error": "Không fetch được dữ liệu từ API",
                    "errors": errors,
                    "tcbs_token_expired": tcbs_token_expired,
                })
                return

            # Merge với nav_data.json hiện tại
            existing: dict = {}
            if NAV_DATA_FILE.exists():
                try:
                    existing = json.loads(NAV_DATA_FILE.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
            merged = {**existing, **incremental}
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            merged["_lastRefresh"] = now_str

            NAV_DATA_FILE.write_text(
                json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            total_pts = sum(len(v) for v in incremental.values())
            latest = max(
                (p["date"] for pts in incremental.values() for p in pts if "date" in p),
                default="?",
            )
            print(
                f"[refresh-nav] ✓ Xong: {len(incremental)} quỹ, {total_pts} điểm → nav_data.json, mới nhất: {latest}",
                flush=True,
            )
            _json_resp(self, {
                "ok": True,
                "funds": list(incremental.keys()),
                "new_points": total_pts,
                "latest_date": latest,
                "lastRefresh": now_str,
                "errors": errors,
                "tcbs_token_expired": tcbs_token_expired,
            })
        except Exception as e:
            print(f"[refresh-nav] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /save-nav POST ───────────────────────────────────────────
    def _handle_save_nav(self, data: dict):
        try:
            updated = self._save_nav(data)
            _json_resp(self, {"ok": True, "updated": updated})
        except Exception as e:
            print(f"[save-nav] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    def _save_nav(self, data: dict) -> dict:
        """Ghi NAV delta vào nav_data.json — chỉ lưu điểm MỚI HƠN HIST cutoff.

        Frontend gửi:
          cachedNav   : dict {code: [{date, nav}, ...]}
          lastRefresh : str  "dd/mm/yyyy HH:MM"
          histCutoff  : dict {code: "yyyy-mm-dd"}  ← ngày cuối cùng trong HIST.chart

        Chỉ giữ điểm date > histCutoff[code]. Nếu thiếu histCutoff thì
        fallback về NAV_KEEP_POINTS (backward-compat với caller cũ).
        """
        cached_nav   = data.get("cachedNav", {})
        last_refresh = data.get("lastRefresh", "")
        hist_cutoff  = data.get("histCutoff", {})   # {code: "yyyy-mm-dd"}

        incremental: dict = {}
        for code, pts in cached_nav.items():
            if not isinstance(pts, list) or not pts:
                continue
            cutoff_date = hist_cutoff.get(code, "")
            if cutoff_date:
                # Chỉ giữ điểm sau HIST cutoff (delta thực sự mới)
                delta = [p for p in pts if isinstance(p, dict) and p.get("date", "") > cutoff_date]
            else:
                # Backward-compat: cắt 500 điểm cuối
                delta = pts[-NAV_KEEP_POINTS:]
            if delta:
                incremental[code] = delta

        if not incremental:
            # Không có điểm nào mới hơn HIST — vẫn trả ok
            print("[save-nav] ℹ Không có điểm mới hơn HIST cutoff, nav_data.json giữ nguyên", flush=True)
            return {"skipped": "no new points after hist cutoff"}

        # Đọc file hiện tại để merge (giữ điểm của các quỹ khác)
        existing: dict = {}
        if NAV_DATA_FILE.exists():
            try:
                existing = json.loads(NAV_DATA_FILE.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        # Merge: cập nhật quỹ có data mới, giữ nguyên quỹ không có trong payload
        merged = {**existing, **incremental}
        if last_refresh:
            merged["_lastRefresh"] = last_refresh

        NAV_DATA_FILE.write_text(
            json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        total_pts = sum(len(v) for v in incremental.values())
        latest = max(
            (p["date"] for pts in incremental.values() for p in pts if "date" in p),
            default="?",
        )
        print(
            f"[save-nav] ✓ {len(incremental)} quỹ, {total_pts} điểm mới → nav_data.json, mới nhất: {latest}",
            flush=True,
        )
        return {"funds": list(incremental.keys()), "latest_date": latest, "new_points": total_pts}

    # ── /import-nav-excel POST ─────────────────────────────────
    def _handle_import_nav_excel(self, data: dict):
        """Import NAV từ file Excel upload (base64 encoded).
        Input: {"code": "TCFF", "file_b64": "<base64>", "filename": "xxx.xlsx", "cutoff": "2026-04-02"}
        """
        try:
            import sys as _sys
            _sys.path.insert(0, str(ROOT / "scripts"))
            from import_nav_excel import parse_from_base64, update_nav_data_json, upsert_core_db
        except ImportError as e:
            _json_resp(self, {"ok": False, "error": f"import_nav_excel.py: {e}"}, 500)
            return

        b64 = data.get("file_b64", "")
        if not b64:
            _json_resp(self, {"ok": False, "error": "Thiếu file_b64"}, 400)
            return

        code_override = (data.get("code") or "").upper() or None
        cutoff = data.get("cutoff") or "2026-04-02"
        filename = data.get("filename", "upload.xlsx")

        try:
            result = parse_from_base64(b64, code_override=code_override)
            code   = result["code"]
            pts    = result["data"]
            if not pts:
                _json_resp(self, {"ok": False, "error": "Không parse được điểm NAV nào"}, 400)
                return
            n_nav  = update_nav_data_json(code, pts, hist_cutoff=cutoff)
            n_core = upsert_core_db(code, pts)
            print(f"[import-excel] ✓ {filename} → {code}: +{n_nav} nav_data, +{n_core} core DB", flush=True)
            _json_resp(self, {
                "ok": True, "fund_code": code,
                "total_parsed": len(pts),
                "nav_data_added": n_nav,
                "core_db_added": n_core,
                "date_range": {"from": pts[0]["date"], "to": pts[-1]["date"]},
            })
        except Exception as e:
            print(f"[import-excel] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /save-core-data POST ─────────────────────────────────────
    def _handle_save_core_data(self, data: dict):
        """Lưu NAV history đầy đủ từ browser vào core_data/<CODE>.json.
        Input: { "TCBF": [{date, nav}, ...], "TCFF": [...], ... }
        File được khóa cứng — chỉ append thêm điểm mới, không sửa/xoá điểm cũ.
        """
        try:
            core_dir = ROOT / "core_data"
            core_dir.mkdir(exist_ok=True)
            results = {}
            for code, pts in data.items():
                if not isinstance(pts, list) or not pts:
                    continue
                out_file = core_dir / f"{code}.json"
                # Nếu file đã có: merge, chỉ append điểm mới hơn
                if out_file.exists():
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                    existing_dates = {p["date"] for p in existing if "date" in p}
                    new_pts = [p for p in pts if p.get("date") not in existing_dates]
                    merged = existing + new_pts
                    merged.sort(key=lambda p: p["date"])
                    appended = len(new_pts)
                else:
                    merged = sorted(pts, key=lambda p: p.get("date", ""))
                    appended = len(merged)
                out_file.write_text(
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                results[code] = {
                    "total": len(merged),
                    "appended": appended,
                    "first": merged[0]["date"],
                    "last": merged[-1]["date"],
                }
                print(f"[core-data] ✓ {code}: {len(merged)} điểm (+{appended} mới) → core_data/{code}.json", flush=True)
            _json_resp(self, {"ok": True, "results": results})
        except Exception as e:
            print(f"[core-data] ERROR: {e}", flush=True)
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /core/status GET ─────────────────────────────────────────
    def _core_status(self):
        conn = _core_db()
        if not conn:
            _json_resp(self, {"ok": False, "error": "Core DB chưa khởi tạo. Chạy: python3 scripts/init_db.py"}, 503)
            return
        try:
            rows = conn.execute("""
                SELECT fund_code,
                       COUNT(*) as total,
                       SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) as verified,
                       SUM(CASE WHEN status='draft'    THEN 1 ELSE 0 END) as draft,
                       SUM(CASE WHEN status='pending'  THEN 1 ELSE 0 END) as pending,
                       MAX(CASE WHEN nav IS NOT NULL THEN date END) as last_nav_date
                FROM nav_history GROUP BY fund_code ORDER BY fund_code
            """).fetchall()
            today = date.today().isoformat()
            funds_status = []
            for r in rows:
                stale = (r["last_nav_date"] or "") < today
                funds_status.append({
                    "code": r["fund_code"], "total": r["total"],
                    "verified": r["verified"], "draft": r["draft"],
                    "pending": r["pending"], "last_date": r["last_nav_date"],
                    "stale": stale,
                })
            conn.close()
            _json_resp(self, {
                "ok": True,
                "total_records": sum(f["total"] for f in funds_status),
                "funds": funds_status,
                "db_path": str(CORE_DB),
            })
        except Exception as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /core/gaps GET ───────────────────────────────────────────
    def _core_gaps(self):
        conn = _core_db()
        if not conn:
            _json_resp(self, {"ok": False, "error": "Core DB chưa khởi tạo"}, 503)
            return
        try:
            last_3_bdays = _last_n_business_days(3)
            gaps = []
            all_funds = conn.execute("SELECT code, name FROM funds WHERE active=1").fetchall()
            for fund in all_funds:
                code = fund["code"]
                # Tìm ngày cuối có NAV thực
                row = conn.execute("""
                    SELECT MAX(date) as last_date FROM nav_history
                    WHERE fund_code=? AND nav IS NOT NULL
                """, (code,)).fetchone()
                last_date = row["last_date"] if row else None
                # Tìm pending records
                pending = conn.execute("""
                    SELECT date FROM nav_history
                    WHERE fund_code=? AND status='pending'
                    ORDER BY date DESC LIMIT 5
                """, (code,)).fetchall()
                if not last_date or last_date < last_3_bdays[-1] or pending:
                    gaps.append({
                        "fund_code": code,
                        "fund_name": fund["name"],
                        "last_nav_date": last_date,
                        "pending_dates": [r["date"] for r in pending],
                        "gap_days": (date.fromisoformat(last_3_bdays[0]) - date.fromisoformat(last_date)).days if last_date else 999,
                    })
            conn.close()
            _json_resp(self, {"ok": True, "gaps": gaps, "count": len(gaps)})
        except Exception as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /core/nav GET ?code=X&from=yyyy-mm-dd&status=draft ───────
    def _core_get_nav(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        code   = (qs.get("code", [""])[0]).upper()
        from_d = qs.get("from", [None])[0]
        status = qs.get("status", [None])[0]
        conn = _core_db()
        if not conn:
            _json_resp(self, {"ok": False, "error": "Core DB chưa khởi tạo"}, 503)
            return
        try:
            q = "SELECT date, nav, source, status, note FROM nav_history WHERE fund_code=?"
            params = [code]
            if from_d:
                q += " AND date >= ?"
                params.append(from_d)
            if status:
                q += " AND status=?"
                params.append(status)
            q += " ORDER BY date"
            rows = conn.execute(q, params).fetchall()
            conn.close()
            _json_resp(self, {
                "ok": True, "fund_code": code,
                "count": len(rows),
                "data": [dict(r) for r in rows],
            })
        except Exception as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /core/nav POST — nhập/cập nhật NAV thủ công ──────────────
    def _core_post_nav(self, data: dict):
        """Nhập NAV thủ công cho một ngày cụ thể.
        Input: {fund_code, date, nav, note (optional)}
        Chỉ cho phép tạo/cập nhật draft. Không được sửa verified.
        """
        code = (data.get("fund_code") or "").upper()
        day  = data.get("date", "")
        nav  = data.get("nav")
        note = data.get("note", "")
        if not code or not day or nav is None:
            _json_resp(self, {"ok": False, "error": "Thiếu fund_code, date hoặc nav"}, 400)
            return
        try:
            nav = float(nav)
            if nav <= 0:
                raise ValueError("nav phải > 0")
        except (TypeError, ValueError) as e:
            _json_resp(self, {"ok": False, "error": str(e)}, 400)
            return
        conn = _core_db()
        if not conn:
            _json_resp(self, {"ok": False, "error": "Core DB chưa khởi tạo"}, 503)
            return
        try:
            # Kiểm tra không ghi đè verified
            row = conn.execute(
                "SELECT status FROM nav_history WHERE fund_code=? AND date=?",
                (code, day)
            ).fetchone()
            if row and row["status"] == "verified":
                conn.close()
                _json_resp(self, {"ok": False, "error": f"LOCKED: {code}/{day} đã verified, không thể sửa"}, 403)
                return
            conn.execute("""
                INSERT INTO nav_history(fund_code, date, nav, source, status, note)
                VALUES (?,?,?,'manual','draft',?)
                ON CONFLICT(fund_code, date) DO UPDATE SET
                    nav=excluded.nav, source='manual', status='draft',
                    note=excluded.note,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                WHERE status != 'verified'
            """, (code, day, nav, note))
            conn.commit()
            conn.close()
            print(f"[core-nav] ✍ {code} {day}: {nav:,.2f} (manual draft)", flush=True)
            _json_resp(self, {"ok": True, "fund_code": code, "date": day, "nav": nav, "status": "draft"})
        except sqlite3.IntegrityError as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 403)
        except Exception as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    # ── /core/verify POST — lock records thành verified ──────────
    def _core_post_verify(self, data: dict):
        """Verify (lock) records từ from_date đến to_date cho một quỹ.
        Input: {fund_code, from_date, to_date (optional, default=today)}
        Chỉ verify records có nav IS NOT NULL và status='draft'.
        """
        code      = (data.get("fund_code") or "").upper()
        from_date = data.get("from_date", "2000-01-01")
        to_date   = data.get("to_date", date.today().isoformat())
        if not code:
            _json_resp(self, {"ok": False, "error": "Thiếu fund_code"}, 400)
            return
        conn = _core_db()
        if not conn:
            _json_resp(self, {"ok": False, "error": "Core DB chưa khởi tạo"}, 503)
            return
        try:
            cur = conn.execute("""
                UPDATE nav_history SET status='verified'
                WHERE fund_code=? AND date BETWEEN ? AND ?
                  AND status='draft' AND nav IS NOT NULL
            """, (code, from_date, to_date))
            count = cur.rowcount
            conn.commit()
            conn.close()
            print(f"[core-verify] 🔒 {code}: {count} records verified ({from_date} → {to_date})", flush=True)
            _json_resp(self, {
                "ok": True, "fund_code": code,
                "verified_count": count,
                "range": {"from": from_date, "to": to_date},
            })
        except Exception as e:
            conn.close()
            _json_resp(self, {"ok": False, "error": str(e)}, 500)

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ("200", "304"):
            print(f"[server] {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"🌐 Quỹ Tracker Server  →  http://localhost:{port}/Quy%20Tracker%20Dashboard.html")
    print(f"📁 Serving: {BASE}")
    print(f"📋 Bot config: {BOT_CFG}")
    print("   Ctrl+C để dừng\n")
    try:
        http.server.HTTPServer(("", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nServer dừng.")
