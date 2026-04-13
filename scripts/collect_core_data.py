#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_core_data.py — Thu thập full NAV history vào Core DB

Chạy: python3 scripts/collect_core_data.py [--verify]

Nguồn dữ liệu:
  fmarket  → Tự động (urllib, không cần auth)
  tcbs     → Semi-auto: import từ file JSON export của browser
             (do TCBS dùng RSA-signed requests, không thể gọi trực tiếp)

Flow:
  1. Fetch tất cả quỹ có fmarket_id → lưu vào nav_history với status='draft'
  2. Với quỹ TCBS (fmarket_id=null): đọc từ file core_data/<CODE>_export.json
     nếu file tồn tại; nếu không thì tạo placeholder 'pending' cho ngày hiện tại.
  3. Nếu --verify: set tất cả draft records thành 'verified' sau khi import.

Export TCBS từ browser:
  1. Vào tcinvest.tcbs.com.vn, mở Console (F12)
  2. Chạy:
     const d={TCBF:JSON.parse(localStorage.FUND_NAV_CHARTTCBF_All||'[]').map(p=>({date:p.matchedDate,nav:p.navCurrent})),
               TCFF:JSON.parse(localStorage.FUND_NAV_CHARTTCFF_All||'[]').map(p=>({date:p.matchedDate,nav:p.navCurrent})),
               TCGF:JSON.parse(localStorage.FUND_NAV_CHARTTCGF_All||'[]').map(p=>({date:p.matchedDate,nav:p.navCurrent}))};
     const b=new Blob([JSON.stringify(d)],{type:'application/json'});
     const a=document.createElement('a');a.href=URL.createObjectURL(b);
     a.download='tcbs_export.json';a.click();
  3. Copy file vào: core_data/tcbs_export.json
  4. Chạy lại script này
"""

import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date

ROOT     = Path(__file__).parent.parent
DB_PATH  = ROOT / "core_data" / "nav.db"
CONFIG   = ROOT / "telegram-bot" / "config.json"
TCBS_EXPORT = ROOT / "core_data" / "tcbs_export.json"

FMARKET_URL = "https://api.fmarket.vn/res/product/get-nav-history"
FMARKET_HEADERS = {
    "Content-Type": "application/json",
    "Origin":       "https://fmarket.vn",
    "Referer":      "https://fmarket.vn/",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}

VERIFY_AFTER = "--verify" in sys.argv


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    if not DB_PATH.exists():
        print("❌ nav.db chưa tồn tại. Chạy: python3 scripts/init_db.py trước.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def upsert_nav(conn, fund_code: str, pts: list, source: str) -> int:
    """Insert NAV points, bỏ qua nếu đã verified. Trả về số điểm mới."""
    count = 0
    for p in pts:
        d, v = p.get("date"), p.get("nav")
        if not d or not v or float(v) <= 0:
            continue
        # INSERT OR IGNORE để không đụng vào verified records
        cur = conn.execute("""
            INSERT OR IGNORE INTO nav_history(fund_code, date, nav, source, status)
            VALUES (?,?,?,?,'draft')
        """, (fund_code, d[:10], float(v), source))
        if cur.rowcount:
            count += 1
    return count


def set_verified(conn, fund_code: str) -> int:
    cur = conn.execute("""
        UPDATE nav_history SET status='verified'
        WHERE fund_code=? AND status='draft'
    """, (fund_code,))
    return cur.rowcount


def create_pending(conn, fund_code: str, for_date: str) -> bool:
    """Tạo placeholder pending nếu chưa có record cho ngày này."""
    cur = conn.execute("""
        INSERT OR IGNORE INTO nav_history(fund_code, date, nav, source, status)
        VALUES (?,?,NULL,NULL,'pending')
    """, (fund_code, for_date))
    return cur.rowcount > 0


# ── fmarket fetch ─────────────────────────────────────────────────────────────

def fetch_fmarket_full(fmarket_id: int) -> list[dict]:
    today_ymd = date.today().strftime("%Y%m%d")
    payload = json.dumps({
        "isAllData": 1,
        "productId": fmarket_id,
        "fromDate":  None,
        "toDate":    today_ymd,
    }).encode()
    headers = {**FMARKET_HEADERS, "Content-Length": str(len(payload))}
    req = urllib.request.Request(
        FMARKET_URL, data=payload,
        headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        resp = json.loads(r.read())

    # fmarket API: data là list trực tiếp [{nav, navDate, productId, ...}]
    raw = resp.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("navHistories") or raw.get("navHistory") or []
    pts = []
    for n in raw:
        d = (n.get("navDate") or n.get("tradingDate") or n.get("date") or "")[:10]
        v = float(n.get("nav") or n.get("navPerShare") or n.get("navValue") or 0)
        if d and v > 0:
            pts.append({"date": d, "nav": v})
    return sorted(pts, key=lambda p: p["date"])


# ── TCBS import từ browser export ─────────────────────────────────────────────

def import_tcbs_export(conn) -> dict:
    results = {}
    if not TCBS_EXPORT.exists():
        print(f"  ⚠ Không tìm thấy {TCBS_EXPORT.name}")
        print(f"    → Xem hướng dẫn export ở đầu file này.")
        return results

    data = json.loads(TCBS_EXPORT.read_text(encoding="utf-8"))
    for code, pts in data.items():
        if not isinstance(pts, list) or not pts:
            continue
        n = upsert_nav(conn, code, pts, "tcbs")
        results[code] = n
        action = f"+{n} mới" if n else "0 mới (đã có)"
        verified_count = set_verified(conn, code) if VERIFY_AFTER else 0
        v_str = f", {verified_count} verified" if VERIFY_AFTER else ""
        last = sorted(pts, key=lambda p: p["date"])[-1]
        print(f"  ✅ {code}: {len(pts)} pts total, {action}{v_str} | đến {last['date']} ({last['nav']:,.2f}đ)")
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    funds = cfg.get("funds", {})
    today = date.today().isoformat()

    conn = get_db()

    # ── Đảm bảo tất cả quỹ đã có trong bảng funds ──
    for code, info in funds.items():
        conn.execute("""
            INSERT OR IGNORE INTO funds(code, name, fmarket_id, tcbs)
            VALUES (?,?,?,?)
        """, (code, info.get("name", code), info.get("fmarket_id"), 1 if info.get("tcbs") else 0))
    conn.commit()

    # ── 1. fmarket funds ──────────────────────────────────────────────────────
    print("\n═══ FMARKET (tự động) ═══")
    fmarket_funds = {c: i for c, i in funds.items() if i.get("fmarket_id")}
    for code, info in fmarket_funds.items():
        fid = info["fmarket_id"]
        try:
            pts = fetch_fmarket_full(fid)
            n = upsert_nav(conn, code, pts, "fmarket")
            conn.commit()
            verified_count = 0
            if VERIFY_AFTER:
                verified_count = set_verified(conn, code)
                conn.commit()
            last = pts[-1] if pts else {}
            v_str = f", {verified_count} verified" if VERIFY_AFTER else ""
            print(f"  ✅ {code:12s} (id={fid:3d}): {len(pts):5d} pts, +{n} mới{v_str} | đến {last.get('date','')} ({last.get('nav',0):,.2f}đ)")
        except urllib.error.URLError as e:
            print(f"  ❌ {code:12s}: Network error — {e}")
        except Exception as e:
            print(f"  ❌ {code:12s}: {e}")
        time.sleep(0.4)

    # ── 2. TCBS funds — import từ browser export ──────────────────────────────
    print("\n═══ TCBS (semi-auto từ browser export) ═══")
    tcbs_funds = {c: i for c, i in funds.items() if i.get("tcbs") and not i.get("fmarket_id")}
    import_tcbs_export(conn)
    conn.commit()

    # Với quỹ TCBS chưa có data hôm nay → tạo pending placeholder
    for code in tcbs_funds:
        row = conn.execute(
            "SELECT nav FROM nav_history WHERE fund_code=? AND date=?",
            (code, today)
        ).fetchone()
        if not row:
            created = create_pending(conn, code, today)
            if created:
                print(f"  📋 {code}: Tạo placeholder 'pending' cho {today} — cần nhập tay")
    conn.commit()

    # ── 3. Summary ────────────────────────────────────────────────────────────
    print("\n═══ SUMMARY ═══")
    rows = conn.execute("""
        SELECT fund_code,
               COUNT(*) as total,
               SUM(CASE WHEN status='verified' THEN 1 ELSE 0 END) as verified,
               SUM(CASE WHEN status='draft'    THEN 1 ELSE 0 END) as draft,
               SUM(CASE WHEN status='pending'  THEN 1 ELSE 0 END) as pending,
               MAX(date) as last_date
        FROM nav_history
        GROUP BY fund_code
        ORDER BY fund_code
    """).fetchall()

    print(f"  {'Code':<12} {'Total':>7} {'Verified':>9} {'Draft':>7} {'Pending':>9} {'Last Date'}")
    print(f"  {'-'*12} {'-'*7} {'-'*9} {'-'*7} {'-'*9} {'-'*10}")
    for r in rows:
        print(f"  {r['fund_code']:<12} {r['total']:>7} {r['verified']:>9} {r['draft']:>7} {r['pending']:>9} {r['last_date']}")

    pending_funds = [r['fund_code'] for r in rows if r['pending'] > 0]
    if pending_funds:
        print(f"\n  ⚠ Cần nhập tay: {', '.join(pending_funds)}")
        print(f"    → Dùng Dashboard: POST /core/nav {{fund_code, date, nav}}")
        print(f"    → Sau đó verify: POST /core/verify")

    conn.close()
    print(f"\n✅ Xong. DB: {DB_PATH}")


if __name__ == "__main__":
    main()
