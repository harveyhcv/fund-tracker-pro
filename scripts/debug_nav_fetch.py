"""
Debug TCBF/TCFF:
1. Kiểm tra Railway DB hiện có data gì
2. Test fmarket API trực tiếp
3. Test TCinvest API (có/không token)
Chạy: python scripts/debug_nav_fetch.py [tcbs_token]
"""
import sys, json, requests, psycopg2
from datetime import date

TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""
DB_URL = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"

# ── 1. Check Railway DB ──────────────────────────────────────────────────────
print("=== Railway DB — TCBF & TCFF ===")
try:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for code in ["TCBF", "TCFF"]:
        cur.execute("""
            SELECT date, nav FROM nav_history
            WHERE fund_code=%s ORDER BY date DESC LIMIT 5
        """, (code,))
        rows = cur.fetchall()
        if rows:
            print(f"  {code}: latest={rows[0][0]} NAV={rows[0][1]:,.2f} ({len(rows)} recent rows shown)")
        else:
            print(f"  {code}: NO DATA in DB")
    conn.close()
except Exception as e:
    print(f"  DB error: {e}")

# ── 2. Test fmarket for TCBF (fmarket_id=22) ─────────────────────────────────
print("\n=== fmarket API — TCBF (id=22) ===")
try:
    today = date.today().strftime("%Y%m%d")
    r = requests.post("https://api.fmarket.vn/res/product/get-nav-history", json={
        "isAllData": 1, "productId": 22,
        "fromDate": "20260601", "toDate": today
    }, headers={"Content-Type": "application/json"}, timeout=15)
    print(f"  HTTP {r.status_code}")
    if r.ok:
        data = r.json()
        # find the list
        navs = None
        d = data.get("data", {})
        if isinstance(d, dict):
            navs = d.get("navHistories") or d.get("navHistory") or list(d.values())[0] if d else []
        elif isinstance(d, list):
            navs = d
        pts = []
        for n in (navs or []):
            dt = (n.get("navDate") or n.get("date") or "")[:10]
            v = float(n.get("nav") or n.get("navValue") or 0)
            if dt and v > 0:
                pts.append((dt, v))
        pts.sort()
        if pts:
            print(f"  TCBF fmarket: {len(pts)} pts, latest={pts[-1][0]} NAV={pts[-1][1]:,.2f}")
        else:
            print(f"  TCBF fmarket: NO PTS — raw keys={list(data.keys())}")
            print(f"  data.data type: {type(data.get('data'))}")
            print(f"  sample: {str(data)[:400]}")
except Exception as e:
    print(f"  fmarket error: {e}")

# ── 3. Test TCinvest API ──────────────────────────────────────────────────────
print(f"\n=== TCinvest API {'(với token)' if TOKEN else '(không token)'} ===")
TCINVEST_URL = "https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={code}&timeline=ALL"

for code in ["TCBF", "TCFF"]:
    hdrs = {
        "Accept": "application/json",
        "Origin": "https://tcinvest.tcbs.com.vn",
        "Referer": "https://tcinvest.tcbs.com.vn/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    if TOKEN:
        hdrs["Authorization"] = f"Bearer {TOKEN}"
    url = TCINVEST_URL.format(code=code)
    try:
        r = requests.get(url, headers=hdrs, timeout=15)
        print(f"  {code}: HTTP {r.status_code}")
        if r.status_code in (401, 403):
            # Try without token
            hdrs2 = {k:v for k,v in hdrs.items() if k != "Authorization"}
            r2 = requests.get(url, headers=hdrs2, timeout=15)
            print(f"    Không token: HTTP {r2.status_code}")
            if r2.ok:
                rows2 = r2.json() if isinstance(r2.json(), list) else r2.json().get("data", [])
                print(f"    → API mở! {len(rows2)} rows")
        elif r.ok:
            data = r.json()
            rows = data if isinstance(data, list) else (data.get("data") or [])
            pts = []
            for row in rows:
                d = (row.get("matchedDate") or row.get("navDate") or row.get("date") or "")[:10]
                v = float(row.get("navCurrent") or row.get("nav") or row.get("navValue") or 0)
                if d and v > 0:
                    pts.append((d, v))
            pts.sort()
            if pts:
                print(f"    OK: {len(pts)} pts, latest={pts[-1][0]} NAV={pts[-1][1]:,.2f}")
            else:
                print(f"    NO PTS — type={type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'list'}")
                print(f"    sample: {str(data)[:300]}")
        else:
            print(f"    raw: {r.text[:200]}")
    except Exception as e:
        print(f"  {code} error: {e}")
