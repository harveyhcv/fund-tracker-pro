#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harvest_nav.py — Master NAV Data Pipeline cho toàn bộ quỹ mở Việt Nam

Modes:
  --discover          Quét fmarket catalog + IDs để build fund registry
  --backfill          Fetch full history từ ngày thành lập (idempotent)
  --backfill --code X Chỉ backfill 1 quỹ
  --daily             Fetch NAV mới nhất (chạy hàng ngày lúc 18:30)
  --status            Tổng quan database: bao nhiêu quỹ, bao nhiêu datapoints

Yêu cầu:
  pip install psycopg2-binary
  DATABASE_URL env var (hoặc khai báo trong telegram-bot/config.json)

Chạy lần đầu:
  python3 scripts/harvest_nav.py --discover
  python3 scripts/harvest_nav.py --backfill

Chạy hàng ngày (cron 18:30):
  python3 scripts/harvest_nav.py --daily
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent

# ── Database connection ────────────────────────────────────────────────────────

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    # Thử đọc từ config.json
    cfg_path = ROOT / "telegram-bot" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            url = cfg.get("database_url", "")
            if url:
                return url
        except Exception:
            pass
    sys.exit("❌ DATABASE_URL không tìm thấy. Set env var hoặc thêm 'database_url' vào config.json")


def connect_db():
    try:
        import psycopg2
        return psycopg2.connect(_get_db_url())
    except ImportError:
        sys.exit("❌ psycopg2 chưa cài: pip install psycopg2-binary")


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS funds_master (
    code            TEXT PRIMARY KEY,
    name            TEXT,
    fmarket_id      INTEGER UNIQUE,
    tcbs            BOOLEAN NOT NULL DEFAULT false,
    source          TEXT    NOT NULL DEFAULT 'fmarket',
    category        TEXT,
    active          BOOLEAN NOT NULL DEFAULT true,
    discovered_at   DATE    NOT NULL DEFAULT CURRENT_DATE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_funds_master_fmarket
    ON funds_master (fmarket_id) WHERE fmarket_id IS NOT NULL;

-- Đảm bảo nav_history có cột source và fetched_at (an toàn nếu đã có)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='nav_history' AND column_name='source'
    ) THEN ALTER TABLE nav_history ADD COLUMN source TEXT; END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='nav_history' AND column_name='fetched_at'
    ) THEN ALTER TABLE nav_history ADD COLUMN fetched_at TIMESTAMPTZ DEFAULT NOW(); END IF;
END $$;
"""

def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
    conn.commit()
    log("✅ Schema sẵn sàng (funds_master)")


# ── Known fund registry ────────────────────────────────────────────────────────
# Danh sách đầy đủ các quỹ mở Việt Nam đã biết.
# fmarket_id=None → TCBS-only hoặc chưa xác nhận.
# Sau khi chạy --discover, các fmarket_id sẽ được điền tự động.

KNOWN_FUNDS: dict[str, dict] = {
    # ── Techcombank Asset Management (TCBS platform) ─────────────────────────
    "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",           "tcbs": True,  "fmarket_id": None, "category": "BOND"},
    "TCFF":    {"name": "Quỹ Cân Bằng Techcombank",              "tcbs": True,  "fmarket_id": None, "category": "BALANCE"},
    "TCGF":    {"name": "Quỹ Tăng Trưởng Techcombank TCGF",     "tcbs": True,  "fmarket_id": None, "category": "STOCK"},
    "TCEF":    {"name": "Quỹ Cổ Phiếu Techcombank Equity",       "tcbs": True,  "fmarket_id": None, "category": "STOCK"},
    "TCSME":   {"name": "Quỹ Cổ Phiếu SME Techcombank",         "tcbs": True,  "fmarket_id": None, "category": "STOCK"},
    "TCRES":   {"name": "Quỹ Bất Động Sản Techcombank",          "tcbs": True,  "fmarket_id": None, "category": "REAL_ESTATE"},
    "TCFIN":   {"name": "Quỹ Tài Chính Techcombank",             "tcbs": True,  "fmarket_id": None, "category": "STOCK"},
    "TCCF":    {"name": "Quỹ Tiền Tệ Techcombank",              "tcbs": True,  "fmarket_id": None, "category": "BOND"},

    # ── fmarket funds (IDs đã xác nhận) ─────────────────────────────────────
    "SSISCA":  {"name": "Quỹ Cổ Phiếu SSI",                     "tcbs": False, "fmarket_id": 11,   "category": "STOCK"},
    "VCBFTBF": {"name": "Quỹ Trái Phiếu VCB",                   "tcbs": False, "fmarket_id": 27,   "category": "BOND"},
    "VCBFBCF": {"name": "Quỹ Cổ Phiếu VCB",                     "tcbs": False, "fmarket_id": 32,   "category": "STOCK"},
    "MAFPF1":  {"name": "Quỹ Tiết Kiệm Manulife",               "tcbs": False, "fmarket_id": 45,   "category": "BOND"},

    # ── fmarket funds (IDs chưa xác nhận — --discover sẽ tìm) ───────────────
    "VDEF":    {"name": "Quỹ Đầu Tư Tăng Trưởng VietFund",      "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VMEEF":   {"name": "Quỹ Cổ Phiếu VietFund Emerging",        "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VESAF":   {"name": "Quỹ Cổ Phiếu VietFund Equity",          "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VEOF":    {"name": "Quỹ Cổ Phiếu VietFund Equity Opport.",  "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VCBFMGF": {"name": "Quỹ Tăng Trưởng VCB Fund",             "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VCBFFIF": {"name": "Quỹ Thu Nhập Cố Định VCB Fund",         "tcbs": False, "fmarket_id": None, "category": "BOND"},
    "VCBFAIF": {"name": "Quỹ Cổ Phiếu AI VCB Fund",             "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VCBFEF":  {"name": "Quỹ Cổ Phiếu VCB Fund",                "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "DCAF":    {"name": "Quỹ Cân Bằng Dragon Capital",           "tcbs": False, "fmarket_id": None, "category": "BALANCE"},
    "DFIX":    {"name": "Quỹ Trái Phiếu Dragon Capital Fixed",   "tcbs": False, "fmarket_id": None, "category": "BOND"},
    "DCDE":    {"name": "Quỹ Cổ Phiếu Việt Nam Dragon Capital",  "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "LHCDF":   {"name": "Quỹ Cân Bằng Lion Holdings",            "tcbs": False, "fmarket_id": None, "category": "BALANCE"},
    "VIBF":    {"name": "Quỹ Cân Bằng VIB",                      "tcbs": False, "fmarket_id": None, "category": "BALANCE"},
    "VCAMDF":  {"name": "Quỹ Đầu Tư Năng Động VCAM",            "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "VCAMBF":  {"name": "Quỹ Cân Bằng VCAM",                     "tcbs": False, "fmarket_id": None, "category": "BALANCE"},
    "UVDIF":   {"name": "Quỹ Cân Bằng UOB Vietnam",              "tcbs": False, "fmarket_id": None, "category": "BALANCE"},
    "UVEEF":   {"name": "Quỹ Cổ Phiếu UOB Vietnam Emerging",     "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "MAGEF":   {"name": "Quỹ Cổ Phiếu Tăng Trưởng Manulife",   "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "NTPPF":   {"name": "Quỹ Cổ Phiếu NTP",                      "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "PHVSF":   {"name": "Quỹ Cổ Phiếu Phú Hưng",                "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "KDEF":    {"name": "Quỹ Cổ Phiếu KIM Định Hướng DN",        "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "MBBF":    {"name": "Quỹ Trái Phiếu MB",                     "tcbs": False, "fmarket_id": None, "category": "BOND"},
    "ESSCF":   {"name": "Quỹ Cổ Phiếu Eastspring",               "tcbs": False, "fmarket_id": None, "category": "STOCK"},
    "ESBF":    {"name": "Quỹ Trái Phiếu Eastspring",             "tcbs": False, "fmarket_id": None, "category": "BOND"},
    "VNDAF":   {"name": "Quỹ VND Anh Minh",                      "tcbs": False, "fmarket_id": None, "category": "STOCK"},
}

# TCBS public NAV endpoint — không cần token, lấy được ~3000 điểm (~12 năm)
TCBS_NAV_URL = "https://apipubaws.tcbs.com.vn/fund/v1/nav-history/{code}?page=0&size=3000"

# fmarket NAV endpoint (confirmed working từ api_docs.md)
FMARKET_NAV_URL = "https://api.fmarket.vn/res/product/get-nav-history"

# fmarket catalog endpoint candidates (thử theo thứ tự)
FMARKET_CATALOG_CANDIDATES = [
    "https://api.fmarket.vn/res/product/filter",
    "https://api.fmarket.vn/res/fund/filter",
    "https://api.fmarket.vn/res/public/product/filter",
]

FMARKET_HEADERS = {
    "Accept":       "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":      "https://fmarket.vn/",
    "Origin":       "https://fmarket.vn",
}

TODAY_ISO  = date.today().isoformat()
TODAY_FMKT = date.today().strftime("%Y%m%d")   # fmarket dùng format YYYYMMDD
FROM_EVER  = "2000-01-01"


# ── fmarket API helpers ────────────────────────────────────────────────────────

def _fmarket_post(url: str, body: dict, timeout: int = 15) -> Optional[dict]:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=FMARKET_HEADERS, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code not in (404, 400):
            log(f"  ⚠ HTTP {e.code} → {url}")
        return None
    except Exception as e:
        log(f"  ⚠ {e} → {url}")
        return None


def fetch_fmarket_nav(fmarket_id: int, from_date: str = FROM_EVER) -> list[dict]:
    """
    Fetch NAV history từ fmarket cho 1 quỹ.
    Returns: [{date: "YYYY-MM-DD", nav: float}]
    """
    from_fmkt = from_date.replace("-", "")  # "2000-01-01" → "20000101"
    body = {
        "isAllData": 1,
        "productId": fmarket_id,
        "fromDate":  from_fmkt if from_fmkt != "20000101" else None,
        "toDate":    TODAY_FMKT,
    }
    resp = _fmarket_post(FMARKET_NAV_URL, body)
    if not resp:
        return []

    # Parse 3 response shapes (theo api_docs.md)
    rows = (
        (resp.get("data") or {}).get("navHistories")
        or resp.get("data")
        or resp.get("navHistories")
        or []
    )
    if not isinstance(rows, list):
        return []

    result = []
    for r in rows:
        d = r.get("navDate") or r.get("date") or r.get("tradingDate") or ""
        v = r.get("nav") or r.get("navValue")
        if d and v:
            result.append({"date": str(d)[:10], "nav": float(v)})

    return sorted(result, key=lambda x: x["date"])


def fetch_tcbs_nav(fund_code: str) -> list[dict]:
    """
    Fetch NAV history từ TCBS public endpoint (không cần token).
    Returns: [{date: "YYYY-MM-DD", nav: float}]
    """
    url = TCBS_NAV_URL.format(code=fund_code)
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": FMARKET_HEADERS["User-Agent"]})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        rows = data.get("data") or []
        result = []
        for r in rows:
            d = r.get("navDate") or r.get("date") or ""
            v = r.get("nav") or r.get("navValue")
            if d and v:
                result.append({"date": str(d)[:10], "nav": float(v)})
        return sorted(result, key=lambda x: x["date"])
    except Exception as e:
        log(f"  ⚠ TCBS {fund_code}: {e}")
        return []


# ── Mode: DISCOVER ─────────────────────────────────────────────────────────────

def cmd_discover(conn, id_start: int = 1, id_end: int = 200, delay: float = 0.4) -> None:
    """
    Bước 1: Seed KNOWN_FUNDS vào funds_master.
    Bước 2: Thử fetch fmarket catalog để lấy tất cả quỹ còn lại.
    Bước 3: Scan productId range nếu catalog không hoạt động.
    """
    log("=" * 60)
    log("🔍 DISCOVER — Build fund registry")
    log("=" * 60)

    # Bước 1: Seed known funds
    seeded = _seed_known_funds(conn)
    log(f"✅ Seeded {seeded} quỹ từ KNOWN_FUNDS")

    # Bước 2: Thử catalog API
    catalog_found = _try_catalog_api(conn)
    if catalog_found > 0:
        log(f"✅ Catalog API: +{catalog_found} quỹ mới")
        return

    # Bước 3: Scan IDs (fallback)
    log(f"\n📡 Catalog API không hoạt động → Scan IDs {id_start}–{id_end}...")
    log("   (Mỗi ID ~0.4s, tổng ~80-160 giây)")
    _scan_fmarket_ids(conn, id_start, id_end, delay)


def _seed_known_funds(conn) -> int:
    count = 0
    with conn.cursor() as cur:
        for code, info in KNOWN_FUNDS.items():
            cur.execute("""
                INSERT INTO funds_master (code, name, fmarket_id, tcbs, source, category)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name       = COALESCE(EXCLUDED.name, funds_master.name),
                    fmarket_id = COALESCE(EXCLUDED.fmarket_id, funds_master.fmarket_id),
                    category   = COALESCE(EXCLUDED.category, funds_master.category),
                    updated_at = NOW()
            """, (
                code,
                info.get("name"),
                info.get("fmarket_id"),
                bool(info.get("tcbs", False)),
                "tcbs" if info.get("tcbs") else "fmarket",
                info.get("category"),
            ))
            if cur.rowcount > 0:
                count += 1
    conn.commit()
    return count


def _try_catalog_api(conn) -> int:
    """Thử các URL catalog. Returns số quỹ mới tìm được."""
    payload = json.dumps({
        "types":    ["STOCK", "BOND", "BALANCE", "REAL_ESTATE", "ETF"],
        "pageSize": 200,
        "page":     1,
        "isIpo":    False,
    }).encode()

    for url in FMARKET_CATALOG_CANDIDATES:
        req = urllib.request.Request(url, data=payload, headers=FMARKET_HEADERS, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())

            rows = (
                (data.get("data") or {}).get("rows")
                or data.get("data")
                or data.get("rows")
                or []
            )
            if not isinstance(rows, list) or not rows:
                continue

            log(f"✅ Catalog OK: {url} → {len(rows)} quỹ")
            new_count = 0
            with conn.cursor() as cur:
                for item in rows:
                    code = (item.get("code") or item.get("shortName") or
                            item.get("fundCode") or "").upper().strip()
                    pid  = item.get("id") or item.get("productId") or item.get("fmProductId")
                    name = item.get("name") or item.get("shortName") or code
                    if not code or not pid:
                        continue
                    cur.execute("""
                        INSERT INTO funds_master (code, name, fmarket_id, source)
                        VALUES (%s, %s, %s, 'fmarket')
                        ON CONFLICT (code) DO UPDATE SET
                            fmarket_id = EXCLUDED.fmarket_id,
                            name       = COALESCE(funds_master.name, EXCLUDED.name),
                            updated_at = NOW()
                    """, (code, name, int(pid)))
                    if cur.rowcount > 0:
                        new_count += 1
            conn.commit()
            return new_count

        except urllib.error.HTTPError:
            continue
        except Exception as e:
            log(f"  ⚠ {url}: {e}")
            continue

    return 0


def _scan_fmarket_ids(conn, id_start: int, id_end: int, delay: float) -> None:
    """
    Scan productId range. Với mỗi ID valid, ghi vào funds_master.
    Vì NAV response không chứa fund_code, ta lưu tạm code='FMKT_{id}'
    và user có thể update sau, hoặc dùng --discover lại khi catalog API fix.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT fmarket_id FROM funds_master WHERE fmarket_id IS NOT NULL")
        known_ids = {r[0] for r in cur.fetchall()}

    found = 0
    week_ago = (date.today() - timedelta(days=7)).strftime("%Y%m%d")

    for pid in range(id_start, id_end + 1):
        if pid in known_ids:
            continue

        body = {"isAllData": 0, "productId": pid,
                "fromDate": week_ago, "toDate": TODAY_FMKT}
        resp = _fmarket_post(FMARKET_NAV_URL, body, timeout=8)

        if resp:
            rows = ((resp.get("data") or {}).get("navHistories")
                    or resp.get("data") or [])
            if isinstance(rows, list) and rows:
                temp_code = f"FMKT_{pid}"
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO funds_master (code, fmarket_id, source, active)
                        VALUES (%s, %s, 'fmarket', true)
                        ON CONFLICT DO NOTHING
                    """, (temp_code, pid))
                conn.commit()
                log(f"  ✅ ID {pid} → {temp_code} (có data, code TBD)")
                found += 1
                known_ids.add(pid)

        time.sleep(delay)

    log(f"\n📊 Scan xong: {found} ID mới (cần map fund_code thủ công nếu catalog API vẫn 404)")


# ── Mode: BACKFILL ─────────────────────────────────────────────────────────────

def cmd_backfill(conn, only_code: Optional[str] = None) -> None:
    """
    Fetch toàn bộ lịch sử NAV từ ngày thành lập đến hôm nay.
    Idempotent — ON CONFLICT (fund_code, nav_date) DO NOTHING.
    """
    log("=" * 60)
    log("📥 BACKFILL — Full history từ ngày thành lập")
    log("=" * 60)

    funds = _get_fetchable_funds(conn, only_code)
    if not funds:
        log("⚠ Không có quỹ nào để backfill. Chạy --discover trước.")
        return

    log(f"→ {len(funds)} quỹ cần backfill\n")
    total_new = 0
    errors    = []

    for code, fmarket_id, is_tcbs in funds:
        # Tìm ngày cuối trong DB để tránh fetch lại dữ liệu cũ
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(nav_date) FROM nav_history WHERE fund_code = %s",
                (code,)
            )
            last = cur.fetchone()[0]
        from_date = FROM_EVER if last is None else str(last)

        if is_tcbs:
            log(f"  {code:10} [TCBS]    from {from_date}...")
            pts = fetch_tcbs_nav(code)
            # Filter chỉ lấy từ from_date trở đi
            if last:
                pts = [p for p in pts if p["date"] > from_date]
            source = "tcbs"
        elif fmarket_id:
            log(f"  {code:10} [fmarket] id={fmarket_id} from {from_date}...")
            pts = fetch_fmarket_nav(fmarket_id, from_date=from_date)
            source = "fmarket"
        else:
            log(f"  {code:10} ⚠ Không có fmarket_id và không phải TCBS → bỏ qua")
            errors.append(code)
            continue

        if not pts:
            log(f"    → 0 điểm (API không trả về data hoặc đã up-to-date)")
            time.sleep(0.3)
            continue

        new_rows = _insert_nav_points(conn, code, pts, source)
        total_new += new_rows
        log(f"    → {len(pts):>5} điểm, +{new_rows:>5} mới | "
            f"range: {pts[0]['date']} → {pts[-1]['date']} | "
            f"nav={pts[-1]['nav']:>10,.0f}")
        time.sleep(0.3)

    log(f"\n{'=' * 60}")
    log(f"✅ Backfill hoàn tất: +{total_new:,} records mới")
    if errors:
        log(f"⚠ Bỏ qua (thiếu source): {', '.join(errors)}")
        log("  → Cập nhật fmarket_id trong funds_master hoặc đánh dấu tcbs=true")


# ── Mode: DAILY ────────────────────────────────────────────────────────────────

def cmd_daily(conn, only_code: Optional[str] = None) -> int:
    """
    Chỉ fetch điểm NAV MỚI (từ nav_date cuối trong DB + 1 ngày đến hôm nay).
    Thiết kế để chạy hàng ngày lúc 18:30 — nhẹ, nhanh (~30-60s cho 50 quỹ).
    Returns: số records mới.
    """
    funds = _get_fetchable_funds(conn, only_code)
    if not funds:
        log("⚠ Không có quỹ. Chạy --discover trước.")
        return 0

    total_new    = 0
    updated_list = []

    for code, fmarket_id, is_tcbs in funds:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(nav_date) FROM nav_history WHERE fund_code = %s",
                (code,)
            )
            last = cur.fetchone()[0]

        if last is None:
            from_date = FROM_EVER  # backfill nếu chưa có gì
        else:
            next_day = (last + timedelta(days=1)).isoformat()
            if next_day > TODAY_ISO:
                continue  # đã cập nhật đến hôm nay
            from_date = next_day

        if is_tcbs:
            pts = fetch_tcbs_nav(code)
            if last:
                pts = [p for p in pts if p["date"] >= from_date]
            source = "tcbs"
        elif fmarket_id:
            pts = fetch_fmarket_nav(fmarket_id, from_date=from_date)
            source = "fmarket"
        else:
            continue

        if pts:
            new_rows = _insert_nav_points(conn, code, pts, source)
            if new_rows > 0:
                total_new += new_rows
                updated_list.append(f"{code}(+{new_rows})")

        time.sleep(0.2)

    if updated_list:
        log(f"✅ Daily: +{total_new} records — {', '.join(updated_list)}")
    else:
        log(f"✅ Daily: không có NAV mới hôm nay ({TODAY_ISO})")

    return total_new


# ── Mode: STATUS ───────────────────────────────────────────────────────────────

def cmd_status(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM funds_master WHERE active=true")
        total_funds = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM nav_history")
        total_pts = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT fund_code) FROM nav_history")
        funds_with_data = cur.fetchone()[0]

        cur.execute("""
            SELECT h.fund_code,
                   COUNT(*) AS cnt,
                   MIN(h.nav_date)::text AS first_date,
                   MAX(h.nav_date)::text AS last_date,
                   COALESCE(m.name, '')  AS name
            FROM nav_history h
            LEFT JOIN funds_master m ON m.code = h.fund_code
            GROUP BY h.fund_code, m.name
            ORDER BY h.fund_code
        """)
        rows = cur.fetchall()

        cur.execute("""
            SELECT code FROM funds_master
            WHERE active=true
              AND code NOT IN (SELECT DISTINCT fund_code FROM nav_history)
        """)
        no_data = [r[0] for r in cur.fetchall()]

    log(f"\n{'=' * 70}")
    log(f"📊 MASTER DATA STATUS — {TODAY_ISO}")
    log(f"{'=' * 70}")
    log(f"Quỹ đăng ký: {total_funds} | Có data: {funds_with_data} | Tổng datapoints: {total_pts:,}")
    log(f"{'─' * 70}")
    log(f"{'Quỹ':10} {'Điểm':>7} {'Từ':>12} {'Đến':>12}  Tên")
    log(f"{'─' * 70}")
    for code, cnt, first, last, name in rows:
        log(f"{code:10} {cnt:>7,} {first:>12} {last:>12}  {name[:30]}")
    if no_data:
        log(f"\n⚠ Chưa có data ({len(no_data)}): {', '.join(no_data)}")
        log("  → Chạy: python3 scripts/harvest_nav.py --backfill")
    log(f"{'=' * 70}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_fetchable_funds(conn, only_code: Optional[str]) -> list[tuple]:
    """Returns [(code, fmarket_id, is_tcbs)] for active funds with a data source."""
    with conn.cursor() as cur:
        if only_code:
            cur.execute("""
                SELECT code, fmarket_id, tcbs
                FROM funds_master
                WHERE code = %s AND active = true
            """, (only_code.upper(),))
        else:
            cur.execute("""
                SELECT code, fmarket_id, tcbs
                FROM funds_master
                WHERE active = true
                  AND (fmarket_id IS NOT NULL OR tcbs = true)
                ORDER BY code
            """)
        return cur.fetchall()


def _insert_nav_points(conn, fund_code: str, pts: list[dict], source: str) -> int:
    """
    Upsert NAV points. Append-only: ON CONFLICT DO NOTHING để bảo toàn history.
    Returns: số rows thực sự mới (không tính duplicate).
    """
    inserted = 0
    with conn.cursor() as cur:
        for p in pts:
            cur.execute("""
                INSERT INTO nav_history (fund_code, nav_date, nav, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (fund_code, nav_date) DO NOTHING
            """, (fund_code, p["date"], p["nav"], source))
            if cur.rowcount > 0:
                inserted += 1
    conn.commit()
    return inserted


# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master NAV Data Pipeline — Fund Tracker Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Lần đầu:
  python3 scripts/harvest_nav.py --discover
  python3 scripts/harvest_nav.py --backfill

Hàng ngày (cron 18:30):
  python3 scripts/harvest_nav.py --daily

Kiểm tra:
  python3 scripts/harvest_nav.py --status
        """
    )
    parser.add_argument("--discover",  action="store_true", help="Build/update fund registry")
    parser.add_argument("--backfill",  action="store_true", help="Fetch full history từ ngày thành lập")
    parser.add_argument("--daily",     action="store_true", help="Fetch NAV mới nhất (daily job)")
    parser.add_argument("--status",    action="store_true", help="Tổng quan DB")
    parser.add_argument("--code",      type=str, default=None, metavar="CODE",
                        help="Giới hạn 1 quỹ (dùng với --backfill hoặc --daily)")
    parser.add_argument("--id-start",  type=int, default=1,   help="ID scan start (default: 1)")
    parser.add_argument("--id-end",    type=int, default=200,  help="ID scan end (default: 200)")
    args = parser.parse_args()

    if not any([args.discover, args.backfill, args.daily, args.status]):
        parser.print_help()
        return

    conn = connect_db()
    ensure_schema(conn)

    try:
        if args.status:
            cmd_status(conn)
        if args.discover:
            cmd_discover(conn, args.id_start, args.id_end)
        if args.backfill:
            cmd_backfill(conn, only_code=args.code)
        if args.daily:
            cmd_daily(conn, only_code=args.code)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
