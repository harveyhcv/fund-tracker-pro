#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""
╔════════════════════════════════════════════════════════════╗
║   update_hist.py — Cập nhật HIST.chart trong Dashboard    ║
╠════════════════════════════════════════════════════════════╣
║  Dùng khi:  nav_data.json > 30 ngày (~30+ điểm/quỹ)      ║
║             Hoặc muốn reset baseline định kỳ hàng tháng  ║
║  Cách chạy: python3 scripts/update_hist.py                ║
║  Thời gian: ~30-60 giây (fetch 5 quỹ từ fmarket/TCBS)    ║
╚════════════════════════════════════════════════════════════╝

LOGIC TỔNG QUAN:
  1. Fetch toàn bộ lịch sử NAV từ fmarket/TCBS cho 5 quỹ
  2. Tìm và replace `const HIST={...}` trong Dashboard HTML
  3. Cập nhật HIST_CUTOFF trong server.py và _HIST_CUTOFF trong bot.py
  4. Reset nav_data.json về {}
  5. In báo cáo: số điểm/quỹ, ngày cutoff mới, HTML size delta
"""

import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
ROOT         = SCRIPT_DIR.parent                       # Fund Tracker Pro/
DASHBOARD    = ROOT / "dashboard"
HTML_FILE    = DASHBOARD / "Quy Tracker Dashboard.html"
SERVER_PY    = DASHBOARD / "server.py"
NAV_JSON     = DASHBOARD / "nav_data.json"
BOT_PY       = ROOT / "telegram-bot" / "bot.py"
BOT_CFG      = ROOT / "telegram-bot" / "config.json"

# ── Fund config (đồng bộ với server.py FUNDS_CONFIG) ───────────────
FUNDS_CONFIG = {
    "VCBFTBF": {"fmarket_id": 31,  "tcbs": False},
    "SSISCA":  {"fmarket_id": 11,  "tcbs": False},
    "VCBFBCF": {"fmarket_id": 32,  "tcbs": False},
    "TCBF":    {"fmarket_id": 22,  "tcbs": True},
    "TCFF":    {"fmarket_id": None, "tcbs": True},
}

FMARKET_URL = "https://api.fmarket.vn/res/product/get-nav-history"
FMARKET_HEADERS = {
    "Content-Type": "application/json",
    "Origin":       "https://fmarket.vn",
    "Referer":      "https://fmarket.vn/",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
TCBS_BASE = "https://apipubaws.tcbs.com.vn/fund/v1"

# ── Kiểm tra import ────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("❌ Thiếu thư viện requests. Chạy: pip3 install requests")


# ════════════════════════════════════════════════════════════════════
# FETCH
# ════════════════════════════════════════════════════════════════════

def fetch_fmarket_full(fmarket_id: int) -> list:
    """Fetch toàn bộ lịch sử NAV từ fmarket (isAllData=1)."""
    today = date.today().strftime("%Y%m%d")
    payload = {
        "isAllData": 1,
        "productId": fmarket_id,
        "fromDate":  None,
        "toDate":    today,
    }
    try:
        r = requests.post(FMARKET_URL, json=payload, headers=FMARKET_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        inner = data.get("data", {})
        if isinstance(inner, dict):
            navs = inner.get("navHistories") or inner.get("data") or []
        elif isinstance(inner, list):
            navs = inner
        else:
            navs = data.get("navHistories") or []
        pts = []
        for n in navs:
            d = (n.get("navDate") or n.get("date") or "")[:10]
            v = float(n.get("nav") or n.get("navValue") or 0)
            if d and v > 0:
                pts.append({"date": d, "nav": v})
        return sorted(pts, key=lambda x: x["date"])
    except Exception as e:
        print(f"  ⚠ fmarket id={fmarket_id}: {e}")
        return []


def fetch_tcbs_full(code: str, token: str = "") -> list:
    """Fetch toàn bộ lịch sử NAV từ TCBS (từ 2020-01-01)."""
    today = date.today().isoformat()
    hdrs = {"Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    urls = [
        f"{TCBS_BASE}/fund-nav/{code}?startDate=2020-01-01&endDate={today}",
        f"{TCBS_BASE}/nav-history/{code}?page=0&size=1500",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=hdrs, timeout=15)
            if r.status_code in (401, 403):
                print(f"  ⚠ TCBS {code}: Token hết hạn ({r.status_code})")
                return []
            if not r.ok:
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
                return sorted(pts, key=lambda x: x["date"])
        except Exception as e:
            print(f"  ⚠ TCBS {code}: {e}")
    return []


# ════════════════════════════════════════════════════════════════════
# HTML PATCH
# ════════════════════════════════════════════════════════════════════

def patch_html_hist(html: str, hist_data: dict, new_cutoff: str) -> str:
    """Replace const HIST={...} và _bkRef trong HTML.

    hist_data: {code: [{date, nav}, ...]} — dữ liệu đầy đủ cho mọi quỹ
    new_cutoff: "YYYY-MM-DD" — ngày mới nhất trong toàn bộ data
    """
    # Compact JSON (không có khoảng trắng thừa) để giảm kích thước
    hist_json = json.dumps(hist_data, ensure_ascii=False, separators=(",", ":"))

    # Replace const HIST = {...}; — hỗ trợ cả có/không có khoảng trắng quanh =
    new_hist_str = f"const HIST = {hist_json};"
    html_new = re.sub(
        r"const HIST\s*=\s*\{.*?\};",
        new_hist_str,
        html,
        count=1,
        flags=re.DOTALL,
    )
    if html_new == html:
        # Fallback: không có dấu chấm phẩy cuối
        html_new = re.sub(
            r"const HIST\s*=\s*\{.*?\}(?=\s*\n|<)",
            f"const HIST = {hist_json}",
            html,
            count=1,
            flags=re.DOTALL,
        )
    if html_new == html:
        print("  ⚠ Không tìm thấy pattern 'const HIST = {...}' trong HTML")
        return html

    # Cập nhật _bkRef (tham chiếu ngày bake) nếu có
    html_new = re.sub(
        r"(_bkRef\s*[=:]\s*['\"])[^'\"]*(['\"])",
        lambda m: m.group(1) + new_cutoff + m.group(2),
        html_new,
        count=1,
    )
    return html_new


# ════════════════════════════════════════════════════════════════════
# SOURCE CODE PATCH (server.py + bot.py)
# ════════════════════════════════════════════════════════════════════

def patch_hist_cutoff_in_file(filepath: Path, new_date: str, var_name: str) -> bool:
    """Cập nhật HIST_CUTOFF hoặc _HIST_CUTOFF dict trong file Python.

    var_name: "HIST_CUTOFF" (server.py) hoặc "_HIST_CUTOFF" (bot.py)
    Tìm pattern: "YYYY-MM-DD" trong block của var_name và replace tất cả.
    """
    text = filepath.read_text(encoding="utf-8")
    # Tìm block dict sau var_name và replace mọi date string "YYYY-MM-DD"
    pattern = rf'({re.escape(var_name)}\s*=\s*\{{[^}}]*\}})'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        print(f"  ⚠ Không tìm thấy {var_name} trong {filepath.name}")
        return False
    block = match.group(1)
    new_block = re.sub(r'"\d{4}-\d{2}-\d{2}"', f'"{new_date}"', block)
    filepath.write_text(text.replace(block, new_block), encoding="utf-8")
    return True


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════

def main():
    print("╔══════════════════════════════════════════════╗")
    print("║   update_hist.py — Cập nhật HIST Dashboard  ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"📅 Ngày chạy: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print()

    # Đọc TCBS token từ config.json (nếu có)
    tcbs_token = ""
    if BOT_CFG.exists():
        try:
            cfg = json.loads(BOT_CFG.read_text(encoding="utf-8"))
            tcbs_token = cfg.get("tcbs_token", "")
            if tcbs_token:
                print(f"✓ TCBS token: {len(tcbs_token)} ký tự")
        except Exception as e:
            print(f"⚠ Không đọc được config.json: {e}")

    # Kiểm tra HTML tồn tại
    if not HTML_FILE.exists():
        sys.exit(f"❌ Không tìm thấy: {HTML_FILE}")
    html_size_before = HTML_FILE.stat().st_size
    print(f"✓ HTML hiện tại: {html_size_before / 1024:.1f} KB")
    print()

    # ── BƯỚC 1: Fetch dữ liệu ────────────────────────────────────
    print("📡 Đang fetch NAV từ fmarket/TCBS...")
    hist_data = {}
    errors = []
    cutoff_dates = []

    for code, cfg in FUNDS_CONFIG.items():
        fid = cfg.get("fmarket_id")
        pts = []

        if fid:
            print(f"  [{code}] fmarket id={fid}... ", end="", flush=True)
            pts = fetch_fmarket_full(fid)
            if pts:
                print(f"✓ {len(pts)} điểm ({pts[0]['date']} → {pts[-1]['date']})")
            else:
                print("⚠ Không có data")

        if not pts and cfg.get("tcbs"):
            print(f"  [{code}] TCBS fallback... ", end="", flush=True)
            pts = fetch_tcbs_full(code, tcbs_token)
            if pts:
                print(f"✓ {len(pts)} điểm ({pts[0]['date']} → {pts[-1]['date']})")
            else:
                print("❌ Không có data")
                errors.append(code)

        if pts:
            hist_data[code] = pts
            cutoff_dates.append(pts[-1]["date"])

        time.sleep(0.5)  # Rate limit

    if not hist_data:
        sys.exit("❌ Không fetch được dữ liệu cho bất kỳ quỹ nào. Kiểm tra kết nối mạng.")

    if errors:
        print(f"\n⚠ Không fetch được: {', '.join(errors)}")
        ans = input("Tiếp tục với dữ liệu còn lại? (y/N): ").strip().lower()
        if ans != "y":
            sys.exit("Đã huỷ.")

    # Ngày cutoff mới = ngày mới nhất trong toàn bộ data
    new_cutoff = max(cutoff_dates)
    print(f"\n📌 Ngày cutoff mới: {new_cutoff}")
    print(f"📦 Tổng điểm NAV: {sum(len(v) for v in hist_data.values())}")

    # ── BƯỚC 2: Xác nhận trước khi ghi ──────────────────────────
    print()
    print("⚠ Sắp ghi đè:")
    print(f"   • {HTML_FILE.name}")
    print(f"   • HIST_CUTOFF trong {SERVER_PY.name}")
    print(f"   • _HIST_CUTOFF trong {BOT_PY.name}")
    print(f"   • {NAV_JSON.name} → reset về {{}}")
    ans = input("\nXác nhận? (y/N): ").strip().lower()
    if ans != "y":
        sys.exit("Đã huỷ.")

    # ── BƯỚC 3: Patch HTML ───────────────────────────────────────
    print("\n✏ Đang cập nhật HTML...")
    html = HTML_FILE.read_text(encoding="utf-8")
    html_new = patch_html_hist(html, hist_data, new_cutoff)
    if html_new != html:
        # Backup
        backup = HTML_FILE.with_suffix(".html.bak")
        backup.write_text(html, encoding="utf-8")
        print(f"  ✓ Backup: {backup.name}")
        HTML_FILE.write_text(html_new, encoding="utf-8")
        html_size_after = len(html_new.encode("utf-8"))
        delta = html_size_after - html_size_before
        sign = "+" if delta >= 0 else ""
        print(f"  ✓ HTML ghi xong: {html_size_after / 1024:.1f} KB ({sign}{delta / 1024:.1f} KB)")
    else:
        print("  ⚠ HTML không thay đổi — kiểm tra lại pattern const HIST")

    # ── BƯỚC 4: Patch server.py + bot.py ────────────────────────
    print("\n✏ Đang cập nhật HIST_CUTOFF trong server.py...")
    ok = patch_hist_cutoff_in_file(SERVER_PY, new_cutoff, "HIST_CUTOFF")
    print(f"  {'✓' if ok else '⚠'} server.py")

    print("\n✏ Đang cập nhật _HIST_CUTOFF trong bot.py...")
    ok = patch_hist_cutoff_in_file(BOT_PY, new_cutoff, "_HIST_CUTOFF")
    print(f"  {'✓' if ok else '⚠'} bot.py")

    # ── BƯỚC 5: Reset nav_data.json ─────────────────────────────
    print("\n✏ Đang reset nav_data.json...")
    NAV_JSON.write_text("{}", encoding="utf-8")
    print("  ✓ nav_data.json → {}")

    # ── BÁO CÁO ─────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║               KẾT QUẢ                       ║")
    print("╠══════════════════════════════════════════════╣")
    for code, pts in hist_data.items():
        print(f"║  {code:<10}  {len(pts):>5} điểm  đến {pts[-1]['date']}      ║")
    print(f"║                                              ║")
    print(f"║  Cutoff mới:  {new_cutoff}                   ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  BƯỚC TIẾP THEO:                             ║")
    print("║  1. Chạy tests: cd tests && python3 -m pytest║")
    print("║  2. Khởi động lại server.py                  ║")
    print("║  3. Mở Dashboard → Bấm 'Cập nhật NAV'       ║")
    print("╚══════════════════════════════════════════════╝")


def fetch_from_db(codes: list, db_url: str) -> dict:
    """Kéo toàn bộ lịch sử NAV từ Railway PostgreSQL.

    Nhanh hơn nhiều so với fetch từ API (không cần token, không rate-limit).
    Trả về {code: [{date, nav}, ...]} sorted theo date tăng dần.
    """
    try:
        import psycopg2
    except ImportError:
        sys.exit("❌ Thiếu psycopg2: pip install psycopg2-binary")

    print(f"🔌 Kết nối Railway DB...")
    conn = psycopg2.connect(db_url)
    result = {}
    with conn.cursor() as cur:
        placeholders = ",".join(["%s"] * len(codes))
        cur.execute(
            f"""SELECT fund_code, nav_date::text, nav::float
                FROM nav_history
                WHERE fund_code IN ({placeholders})
                ORDER BY fund_code, nav_date""",
            codes,
        )
        for fund_code, nav_date, nav in cur.fetchall():
            result.setdefault(fund_code, []).append({"date": nav_date, "nav": nav})
    conn.close()
    return result


def main_from_db(db_url: str, codes: list):
    """Mode --from-db: kéo từ Railway PostgreSQL thay vì fetch API."""
    print("=" * 48)
    print("  update_hist.py --from-db  (Railway DB)")
    print("=" * 48)
    print(f"📅 Ngày chạy: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"🎯 Quỹ: {', '.join(codes)}")
    print()

    if not HTML_FILE.exists():
        sys.exit(f"❌ Không tìm thấy: {HTML_FILE}")
    html_size_before = HTML_FILE.stat().st_size
    print(f"✓ HTML hiện tại: {html_size_before / 1024:.1f} KB")

    hist_data = fetch_from_db(codes, db_url)
    if not hist_data:
        sys.exit("❌ Không lấy được dữ liệu từ DB. Kiểm tra kết nối.")

    cutoff_dates = []
    for code, pts in hist_data.items():
        print(f"  [{code}] {len(pts)} điểm  {pts[0]['date']} → {pts[-1]['date']}")
        cutoff_dates.append(pts[-1]["date"])
    new_cutoff = max(cutoff_dates)
    total_pts   = sum(len(v) for v in hist_data.values())
    print(f"\n📌 Cutoff mới: {new_cutoff}  |  Tổng: {total_pts:,} điểm")
    print()

    ans = input("Xác nhận ghi đè HTML + reset nav_data.json? (y/N): ").strip().lower()
    if ans != "y":
        sys.exit("Đã huỷ.")

    # Patch HTML
    print("\n✏ Đang cập nhật HTML...")
    html = HTML_FILE.read_text(encoding="utf-8")
    html_new = patch_html_hist(html, {"chart": hist_data}, new_cutoff)
    if html_new != html:
        backup = HTML_FILE.with_suffix(".html.bak")
        backup.write_text(html, encoding="utf-8")
        print(f"  ✓ Backup: {backup.name}")
        HTML_FILE.write_text(html_new, encoding="utf-8")
        html_size_after = len(html_new.encode("utf-8"))
        delta = html_size_after - html_size_before
        sign = "+" if delta >= 0 else ""
        print(f"  ✓ HTML: {html_size_after / 1024:.1f} KB ({sign}{delta / 1024:.1f} KB)")
    else:
        print("  ⚠ HTML không thay đổi")

    # Patch cutoffs
    for fpath, varname in [(SERVER_PY, "HIST_CUTOFF"), (BOT_PY, "_HIST_CUTOFF")]:
        if fpath.exists():
            ok = patch_hist_cutoff_in_file(fpath, new_cutoff, varname)
            print(f"  {'✓' if ok else '⚠'} {fpath.name}: {varname} → {new_cutoff}")

    # Reset nav_data.json (điểm mới sẽ được fetch tự động khi dashboard refresh)
    NAV_JSON.write_text("{}", encoding="utf-8")
    print("  ✓ nav_data.json → reset")
    print(f"\n✅ Xong! Cutoff mới: {new_cutoff}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-db", action="store_true", help="Kéo từ Railway PostgreSQL")
    parser.add_argument(
        "--db-url",
        default="postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway",
    )
    parser.add_argument(
        "--funds",
        default="TCBF,VCBFTBF,SSISCA,VCBFBCF,TCFF",
        help="Danh sách mã quỹ cách nhau bởi dấu phẩy",
    )
    args = parser.parse_args()

    if args.from_db:
        main_from_db(args.db_url, args.funds.split(","))
    else:
        main()
