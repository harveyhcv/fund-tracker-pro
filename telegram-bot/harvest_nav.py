#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harvest_nav.py — Master NAV Data Pipeline cho toàn bộ quỹ mở Việt Nam

Modes:
  --discover          Quét fmarket catalog + IDs để build fund registry
  --backfill          Fetch full history từ ngày thành lập (idempotent)
  --backfill --code X Chỉ backfill 1 quỹ
  --daily             Fetch NAV mới nhất (chạy hàng ngày lúc 18:30)
  --reverify          GOV-008: re-verify 3 lớp T+1/T+8/T+31 cho NAV tcinvest đã
                      lưu — NAV ngày mới nhất TCBS công bố có thể còn tạm tính,
                      tự sửa lại sau; khớp thì nâng độ tin cậy, lệch thì cập
                      nhật + reset (chạy hàng ngày, sau --daily)
  --status            Tổng quan database: bao nhiêu quỹ, bao nhiêu datapoints

Yêu cầu:
  pip install psycopg2-binary
  DATABASE_URL env var (hoặc khai báo trong telegram-bot/config.json)

Chạy lần đầu:
  python3 scripts/harvest_nav.py --discover
  python3 scripts/harvest_nav.py --backfill

Chạy hàng ngày (cron 18:30):
  python3 scripts/harvest_nav.py --daily
  python3 scripts/harvest_nav.py --reverify
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


# ── TCinvest confirmed fund list (từ screenshot 2026-06-21, "Toàn thị trường") ─
# Đây là danh sách CHÍNH XÁC 31 quỹ có trên tài khoản TCinvest của Harvey.
# source = "tcinvest" → dùng JWT để fetch (--tcinvest mode)
# source = "tcbs"     → TCBS-managed, fetch qua public nav-history endpoint
# Tất cả 31 quỹ này có thể fetch qua TCBS API với hoặc không có JWT.

TCINVEST_FUNDS: dict[str, dict] = {
    # Mã       Tên đầy đủ                                        Loại         NAV hiện tại
    "TCFF":    {"name": "Quỹ Cân Bằng Techcombank",              "category": "BALANCE"},    # 15,605
    "TCSME":   {"name": "Quỹ Cổ Phiếu SME Techcombank",         "category": "STOCK"},      # 14,169
    "VDEF":    {"name": "Quỹ Đầu Tư Tăng Trưởng VietFund",      "category": "STOCK"},      # 12,264
    "VCBFFIF": {"name": "Quỹ Thu Nhập Cố Định VCB Fund",         "category": "BOND"},       # 15,901
    "TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",            "category": "BOND"},       # 20,728
    "VMPF":    {"name": "Quỹ Cổ Phiếu VietFund Emerging",        "category": "STOCK"},      # 16,736 (code thực: VMPF, alias VMEEF)
    "VMEEF":   {"name": "Quỹ Cổ Phiếu VietFund Emerging",        "category": "STOCK"},      # alias — fallback
    "VCBFMGF": {"name": "Quỹ Tăng Trưởng VCB Fund",             "category": "STOCK"},      # 14,628
    "LHCDF":   {"name": "Quỹ Cổ Phiếu Lion Holdings",            "category": "STOCK"},      # 11,819
    "DFIX":    {"name": "Quỹ Trái Phiếu Dragon Capital Fixed",   "category": "BOND"},       # 12,152
    "VCBFTBF": {"name": "Quỹ Cân Bằng VCB Fund",                "category": "BALANCE"},    # 38,928
    "VESAF":   {"name": "Quỹ Cổ Phiếu VietFund Equity",          "category": "STOCK"},      # 33,818
    "VCBFAIF": {"name": "Quỹ Cổ Phiếu AI VCB Fund",             "category": "STOCK"},      # 11,595
    "VCAMDF":  {"name": "Quỹ Đầu Tư Năng Động VCAM",            "category": "STOCK"},      # 11,062
    "VIBF":    {"name": "Quỹ Cân Bằng VIB",                      "category": "BALANCE"},    # 19,909
    "UVDIF":   {"name": "Quỹ Cân Bằng UOB Vietnam",              "category": "BALANCE"},    # 11,087
    "VCBFBCF": {"name": "Quỹ Cổ Phiếu VCB Fund",                "category": "STOCK"},      # 43,686
    "TVPF":    {"name": "Quỹ Cổ Phiếu NTP",                      "category": "STOCK"},      # 10,584 (code thực: TVPF, alias NTPPF)
    "NTPPF":   {"name": "Quỹ Cổ Phiếu NTP",                      "category": "STOCK"},      # alias — fallback
    "VCAMBF":  {"name": "Quỹ Cân Bằng VCAM",                     "category": "BALANCE"},    # 21,568
    "VEOF":    {"name": "Quỹ Cổ Phiếu VietFund Equity Opport.",  "category": "STOCK"},      # 34,760
    "DCAF":    {"name": "Quỹ Cổ Phiếu Dragon Capital",           "category": "STOCK"},      # 17,306
    "TCEF":    {"name": "Quỹ Cổ Phiếu Techcombank Equity",       "category": "STOCK"},      # 20,640
    "MAGEF":   {"name": "Quỹ Cổ Phiếu Tăng Trưởng Manulife",   "category": "STOCK"},      # 21,598
    "TCGF":    {"name": "Quỹ Tăng Trưởng Techcombank TCGF",     "category": "STOCK"},      # 11,702
    "PHVSF":   {"name": "Quỹ Cổ Phiếu Phú Hưng",                "category": "STOCK"},      # 12,979
    "TCRES":   {"name": "Quỹ Bất Động Sản Techcombank",          "category": "REAL_ESTATE"},# 12,988
    "SSISCA":  {"name": "Quỹ Cổ Phiếu SSI",                     "category": "STOCK"},      # 43,535
    "UVEEF":   {"name": "Quỹ Cổ Phiếu UOB Vietnam Emerging",     "category": "STOCK"},      # 17,180
    "DCDS":    {"name": "Quỹ Cổ Phiếu Dragon Capital DS",        "category": "STOCK"},      # 99,846 — MỚI, chưa có trong KNOWN_FUNDS
    "TCFIN":   {"name": "Quỹ Tài Chính Techcombank",             "category": "STOCK"},      # 13,924
    "DCDE":    {"name": "Quỹ Cổ Phiếu Việt Nam Dragon Capital",  "category": "STOCK"},      # 28,702
    "KDEF":    {"name": "Quỹ Cổ Phiếu KIM Định Hướng DN",        "category": "STOCK"},      # 11,824
}

# KNOWN_FUNDS = TCINVEST_FUNDS + các quỹ khác không có trên TCinvest
# (fmarket-only: MAFPF1, MBBF, ESSCF, ESBF, VNDAF, VCBFEF, TCCF)
KNOWN_FUNDS: dict[str, dict] = {
    **TCINVEST_FUNDS,
    # ── Có trên fmarket nhưng KHÔNG có trên TCinvest ─────────────────────────
    "MAFPF1":  {"name": "Quỹ Tiết Kiệm Manulife",               "category": "BOND"},
    "VCBFEF":  {"name": "Quỹ Cổ Phiếu VCB (cũ)",               "category": "STOCK"},
    "TCCF":    {"name": "Quỹ Tiền Tệ Techcombank",              "category": "BOND"},
    "MBBF":    {"name": "Quỹ Trái Phiếu MB",                    "category": "BOND"},
    "ESSCF":   {"name": "Quỹ Cổ Phiếu Eastspring",              "category": "STOCK"},
    "ESBF":    {"name": "Quỹ Trái Phiếu Eastspring",            "category": "BOND"},
    "VNDAF":   {"name": "Quỹ VND Anh Minh",                     "category": "STOCK"},
}

# TCBS public NAV endpoint — không cần token, lấy được ~3000 điểm (~12 năm)
TCBS_NAV_URL = "https://apipubaws.tcbs.com.vn/fund/v1/nav-history/{code}?page=0&size=3000"

# TCinvest authenticated endpoints (cần JWT từ /otp)
# Dùng để fetch TẤT CẢ quỹ trên platform (không chỉ TCBS-managed)
TCINVEST_CATALOG_URL = "https://apiextaws.tcbs.com.vn/visionary-port/v1/market/fund"
TCINVEST_NAV_AUTH_URL = "https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={code}&timeline=ALL"
TCINVEST_NAV_HIST_URL = "https://apiextaws.tcbs.com.vn/visionary-port/v1/chart-nav?code={code}&timeline=ALL"

# Alias: mã cũ ↔ mã mới trên TCinvest (thử cả hai khi fetch)
# Format: canonical_code -> [alt_code, ...] để thử lần lượt khi canonical trả về 0 điểm
TCINVEST_CODE_ALIASES: dict[str, list[str]] = {
    "VMEEF": ["VMPF"],   # VietFund Emerging — TCinvest hiện dùng VMPF
    "NTPPF": ["TVPF"],   # NTP Fund — TCinvest hiện dùng TVPF
}

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
    data = resp.get("data")
    if isinstance(data, dict):
        rows = data.get("navHistories") or data.get("rows") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = resp.get("navHistories") or resp.get("rows") or []
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
            data = resp.get("data")
            if isinstance(data, dict):
                rows = data.get("navHistories") or data.get("rows") or []
            elif isinstance(data, list):
                rows = data
            else:
                rows = resp.get("navHistories") or []
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

def _yesterday_nav_map(conn) -> dict:
    """Trả {fund_code: nav} cho ngày hôm qua (bỏ qua provisional)."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fund_code, nav FROM nav_history
            WHERE nav_date = %s AND source NOT IN ('provisional')
        """, (yesterday,))
        return {r[0]: float(r[1]) for r in cur.fetchall()}


def cmd_daily(conn, only_code: Optional[str] = None, jwt: Optional[str] = None) -> int:
    """
    Fetch NAV mới nhất với confidence workflow:
    - provisional   → fetch == yesterday (API chưa update)
    - pending_confirm → fetch ≠ manual (cần admin xác nhận)
    - confirmed     → fetch ≈ manual (tự động khóa)
    Chạy lúc 18:30 và 20:00 (second pass để sửa provisional).
    Returns: số records thay đổi.
    """
    funds = _get_fetchable_funds(conn, only_code)
    if not funds:
        log("⚠ Không có quỹ. Chạy --discover trước.")
        return 0

    jwt = jwt or _load_jwt_from_config()
    if jwt:
        log("🔑 Có JWT TCinvest — quỹ tcbs sẽ fetch qua chart-nav")
    else:
        log("⚠ Không có JWT — quỹ TCinvest-only sẽ bị bỏ qua hôm nay")

    # Load db module cho confidence-aware upsert
    sys.path.insert(0, str(ROOT / "telegram-bot"))
    import db as _db
    _db.init_pool()

    # Fetch yesterday NAVs một lần cho tất cả quỹ
    yesterday_navs = _yesterday_nav_map(conn)

    # GOV-003: ngưỡng cảnh báo NAV nhảy bất thường trong 1 phiên — không phải lỗi
    # confirm-mismatch (đã có ở pending_confirm) mà là data glitch/API trả sai thang
    # đo (vd thiếu/thừa số 0), có thể xảy ra ở NAV auto-harvest bình thường (fmarket/tcbs).
    NAV_JUMP_THRESHOLD_PCT = 15.0
    jump_list = []   # [(code, yesterday_nav, new_nav, pct)]

    total_new       = 0
    pending_list    = []
    updated_list    = []
    provisional_list = []   # quỹ fetch được nhưng NAV == hôm qua (API chưa update, chưa chắc đúng)

    PROVISIONAL_PROTECTED = ('fixed', 'confirmed', 'manual', 'pending_confirm', 'tcinvest')

    for code, fmarket_id, is_tcbs in funds:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(nav_date) FROM nav_history WHERE fund_code = %s",
                (code,)
            )
            last = cur.fetchone()[0]

        if last is None:
            from_date = FROM_EVER
        else:
            next_day = (last + timedelta(days=1)).isoformat()
            if next_day > TODAY_ISO:
                # Đã có dữ liệu đến hôm nay. Chỉ re-fetch nếu là provisional
                # (auto-fetched == yesterday, chưa finalize).
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT source FROM nav_history WHERE fund_code=%s AND nav_date=%s",
                        (code, TODAY_ISO)
                    )
                    row = cur.fetchone()
                existing_src = row[0] if row else None
                if existing_src in PROVISIONAL_PROTECTED or existing_src is None:
                    continue  # confirmed/manual/fixed/pending → skip
                from_date = TODAY_ISO  # provisional → re-fetch để correction
            else:
                from_date = next_day

        # GOV-007 (2026-07-14): TCinvest là nguồn CHUẨN — luôn thử trước, fmarket chỉ
        # dùng để lấp chỗ trống khi quỹ không có trên TCinvest hoặc JWT hết hạn. Trước
        # đây fmarket được thử TRƯỚC bất kể is_tcbs, nên 1 fmarket_id cấu hình sai (vụ
        # VCBFTBF) đã âm thầm ghi đè NAV đúng từ TCinvest — DB layer giờ cũng khóa cứng
        # 'tcinvest' (xem db.py upsert_nav/upsert_nav_with_confidence) nhưng đổi thứ tự
        # thử ở đây để dữ liệu ĐÚNG được ưu tiên ngay từ đầu, không chỉ chặn ở lớp ghi.
        pts, source = [], None
        if is_tcbs and jwt:
            pts = tcinvest_fetch_nav_hist(code, jwt)
            if last:
                pts = [p for p in pts if p["date"] >= from_date]
            if pts:
                source = "tcinvest"
        if not pts and fmarket_id:
            pts = fetch_fmarket_nav(fmarket_id, from_date=from_date)
            source = "fmarket"
        if not pts:
            time.sleep(0.2)
            continue

        yesterday_nav = yesterday_navs.get(code)
        for p in pts:
            nav_dt = date.fromisoformat(p["date"])
            # Chỉ dùng confidence logic cho điểm hôm nay
            # Điểm lịch sử dùng smart upsert đơn giản (append-only trừ provisional)
            if p["date"] == TODAY_ISO:
                result = _db.upsert_nav_with_confidence(
                    code, nav_dt, p["nav"], source, yesterday_nav=yesterday_nav
                )
                if result in ('inserted', 'updated'):
                    total_new += 1
                    updated_list.append(code)
                    if yesterday_nav:
                        pct = (p["nav"] - yesterday_nav) / yesterday_nav * 100
                        if abs(pct) > NAV_JUMP_THRESHOLD_PCT:
                            jump_list.append((code, yesterday_nav, p["nav"], pct))
                elif result == 'provisional':
                    provisional_list.append(code)
                elif result == 'pending_confirm':
                    pending_list.append(f"{code} {p['date']}")
                elif result == 'confirmed':
                    total_new += 1
                    updated_list.append(f"{code}✓")
            else:
                # Lịch sử: dùng _insert_nav_points (DO NOTHING trừ provisional)
                _insert_nav_points(conn, code, [p], source)
                total_new += 1

        time.sleep(0.2)

    # Quỹ hoàn toàn không có NAV cho hôm nay (fetch lỗi/không JWT/API rỗng) —
    # khác với provisional (có fetch nhưng bằng NAV hôm qua, chưa finalize).
    stuck_list = []
    for code, _fmarket_id, _is_tcbs in funds:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(nav_date) FROM nav_history WHERE fund_code = %s", (code,))
            last = cur.fetchone()[0]
        if last is None or last.isoformat() < TODAY_ISO:
            stuck_list.append(code)

    parts = [f"✅ Daily {TODAY_ISO}:"]
    if updated_list:
        parts.append(f"+{total_new} records ({', '.join(dict.fromkeys(updated_list))})")
    else:
        parts.append("không có NAV mới")
    if provisional_list:
        parts.append(f"⏳ {len(provisional_list)} provisional (bằng NAV hôm qua, API chưa update): {', '.join(sorted(set(provisional_list)))}")
    if pending_list:
        parts.append(f"⚠ {len(pending_list)} pending_confirm: {', '.join(pending_list)}")
    if stuck_list:
        parts.append(f"❌ {len(stuck_list)} chưa có NAV hôm nay: {', '.join(sorted(set(stuck_list)))}")
    log(" — ".join(parts))

    # Dòng riêng, dễ parse bằng script gọi qua subprocess (vd miniapp_server.py):
    # danh sách mã cần admin kiểm tra/nhập tay, gộp provisional + stuck.
    needs_check = sorted(set(provisional_list) | set(stuck_list))
    if needs_check:
        log(f"NEEDS_CHECK: {','.join(needs_check)}")

    # GOV-003: NAV nhảy >NAV_JUMP_THRESHOLD_PCT%/phiên — dòng riêng để bot.py (chạy
    # qua subprocess) parse và báo admin + ghi audit_log ngay (không chỉ log im lặng,
    # vì có thể là data glitch ảnh hưởng tín hiệu/dự báo cho user).
    if jump_list:
        parts_j = [f"{c}:{y:.0f}->{n:.0f}:{pct:+.1f}%" for c, y, n, pct in jump_list]
        log(f"JUMP_ALERT: {';'.join(parts_j)}")

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
            # CHỈ lấy quỹ tồn tại trong bảng `funds` (FK target của nav_history).
            # funds_master chứa cả placeholder FMKT_NN chưa map → nếu fetch sẽ gây
            # ForeignKeyViolation khi insert nav_history. EXISTS lọc bỏ chúng.
            cur.execute("""
                SELECT m.code, m.fmarket_id, m.tcbs
                FROM funds_master m
                WHERE m.active = true
                  AND (m.fmarket_id IS NOT NULL OR m.tcbs = true)
                  AND EXISTS (SELECT 1 FROM funds f WHERE f.code = m.code)
                ORDER BY m.code
            """)
        return cur.fetchall()


def _insert_nav_points(conn, fund_code: str, pts: list[dict], source: str) -> int:
    """
    Upsert NAV points với smart conflict policy:
    - 'manual'/'fixed' không bao giờ bị ghi đè bởi auto-harvest
    - 'tcinvest' chỉ tự nó mới được ghi đè chính nó (self-correction) — KHÔNG
      cho phép 'fmarket'/'tcbs' cũ ghi đè, cùng logic PROTECTED_SOURCES đã có
      trong db.py::upsert_nav(). BUG đã xảy ra thật (2026-07-14, xem GOV-007
      phần 3): funds_master.tcbs=False cho 26/33 quỹ khiến harvest_nav.py
      --daily bỏ qua tcinvest, dùng fmarket_id SAI (VCBFTBF trỏ nhầm sang
      DCBF — quỹ trái phiếu khác hẳn) rồi hàm này (trước khi sửa) ghi đè
      thẳng lên dữ liệu tcinvest đã khoá đúng trước đó vì chỉ chặn
      fixed/manual, không chặn tcinvest. Đây là lớp phòng thủ thứ 2 (lớp 1
      là sửa funds_master) — dù cấu hình lại sai lần nữa, hàm này vẫn không
      cho ghi đè NAV đã khoá.
    - 'fmarket'/'tcbs' có thể được cập nhật lẫn nhau khi API trả về giá trị
      mới hơn (dùng cho correction pass lúc 20:00 sau khi NAV đã finalize)
    Returns: số rows thực sự thay đổi (insert + update).
    """
    inserted = 0
    with conn.cursor() as cur:
        # Guard FK: nav_history.fund_code phải tồn tại trong `funds`.
        cur.execute("SELECT 1 FROM funds WHERE code = %s", (fund_code,))
        if cur.fetchone() is None:
            log(f"  ⚠ {fund_code}: chưa có trong bảng funds — bỏ qua insert")
            return 0
        for p in pts:
            cur.execute("""
                INSERT INTO nav_history (fund_code, nav_date, nav, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (fund_code, nav_date) DO UPDATE
                    SET nav        = CASE
                                       WHEN nav_history.source IN ('fixed', 'manual') THEN nav_history.nav
                                       WHEN nav_history.source = 'tcinvest' AND EXCLUDED.source <> 'tcinvest' THEN nav_history.nav
                                       ELSE EXCLUDED.nav
                                     END,
                        source     = CASE
                                       WHEN nav_history.source IN ('fixed', 'manual') THEN nav_history.source
                                       WHEN nav_history.source = 'tcinvest' AND EXCLUDED.source <> 'tcinvest' THEN nav_history.source
                                       ELSE EXCLUDED.source
                                     END,
                        fetched_at = NOW()
                WHERE nav_history.source NOT IN ('fixed', 'manual')
                   OR (nav_history.source = 'tcinvest' AND EXCLUDED.source = 'tcinvest')
            """, (fund_code, p["date"], p["nav"], source))
            if cur.rowcount > 0:
                inserted += 1
    conn.commit()
    return inserted


# ── Mode: TCINVEST BULK FETCH (dùng JWT từ /otp) ──────────────────────────────

def _tcinvest_headers(jwt: str) -> dict:
    return {
        "Authorization":   f"Bearer {jwt}",
        "Content-Type":    "application/json",
        "Accept":          "application/json",
        "Accept-language": "vi",
        "Origin":          "https://tcinvest.tcbs.com.vn",
        "Referer":         "https://tcinvest.tcbs.com.vn/",
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }


def _tcinvest_get(url: str, jwt: str, timeout: int = 15) -> Optional[dict]:
    req = urllib.request.Request(url, headers=_tcinvest_headers(jwt))
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log("  ❌ JWT hết hạn hoặc không hợp lệ. Chạy /otp trong Telegram để làm mới.")
            return None
        log(f"  ⚠ HTTP {e.code}: {url}")
        return None
    except Exception as e:
        log(f"  ⚠ {e}")
        return None


def tcinvest_get_catalog(jwt: str) -> list[dict]:
    """
    Lấy danh sách TẤT CẢ quỹ trên TCinvest platform (không chỉ TCBS-managed).
    Returns: [{code, name, category, ...}]
    """
    log("  Đang lấy catalog quỹ từ TCinvest...")
    # Thử các endpoint catalog candidates
    catalog_urls = [
        TCINVEST_CATALOG_URL,
        "https://apipubaws.tcbs.com.vn/fund/v1/fund-product/list?page=0&size=500&type=OPEN_END",
        "https://apipubaws.tcbs.com.vn/fund/v1/list?page=0&size=500",
        "https://apipubaws.tcbs.com.vn/fund/v1/products?page=0&size=500",
    ]
    for url in catalog_urls:
        resp = _tcinvest_get(url, jwt)
        if not resp:
            continue
        data = resp.get("data") or resp
        items = (
            data.get("content") or data.get("data") or data.get("rows")
            or (data if isinstance(data, list) else [])
        )
        if items and isinstance(items, list) and len(items) > 0:
            log(f"  ✅ Catalog: {len(items)} quỹ từ {url.split('?')[0]}")
            return items
    log("  ⚠ Không lấy được catalog — sẽ dùng danh sách KNOWN_FUNDS")
    return []


def _parse_chart_nav_response(resp) -> list[dict]:
    """Parse chart-nav response: list hoặc {"data": [...]}"""
    if isinstance(resp, list):
        rows = resp
    elif isinstance(resp, dict):
        rows = resp.get("data") or []
        if not isinstance(rows, list):
            rows = []
    else:
        return []
    result = []
    for r in rows:
        d = (r.get("matchedDate") or r.get("t") or r.get("navDate")
             or r.get("date") or r.get("tradingDate") or "")
        v = (r.get("navCurrent") or r.get("v") or r.get("nav")
             or r.get("navValue") or r.get("ccqNav"))
        if d and v:
            result.append({"date": str(d)[:10], "nav": float(v)})
    return sorted(result, key=lambda x: x["date"])


def tcinvest_fetch_nav_hist(code: str, jwt: str) -> list[dict]:
    """
    Fetch full NAV history qua TCinvest JWT.
    Thử code chính trước, sau đó thử alias trong TCINVEST_CODE_ALIASES nếu 0 điểm.
    """
    codes_to_try = [code] + TCINVEST_CODE_ALIASES.get(code, [])
    for try_code in codes_to_try:
        url = TCINVEST_NAV_HIST_URL.format(code=try_code)
        resp = _tcinvest_get(url, jwt)
        if not resp:
            continue
        result = _parse_chart_nav_response(resp)
        if result:
            if try_code != code:
                log(f"    (dùng alias {try_code} thay cho {code})")
            return result
    return []


def cmd_tcinvest(conn, jwt: str) -> None:
    """
    One-time bulk fetch 31 quỹ từ TCinvest dùng JWT.

    Quy trình:
    1. Seed TCINVEST_FUNDS (31 quỹ xác nhận từ screenshot 2026-06-21) vào funds_master
    2. Thử lấy catalog từ TCinvest API để bổ sung quỹ mới (nếu có)
    3. Fetch full NAV history mỗi quỹ qua TCBS/TCinvest API
    4. Upsert vào nav_history — tcinvest được phép nâng cấp mọi ngày đang có
       nguồn thấp hơn (fmarket/tcbs cũ), tôn trọng khoá fixed/manual đã có
       (xem _insert_nav_points). KHÔNG còn skip quỹ chỉ vì đã có data cũ —
       đây là điểm khác biệt quan trọng so với trước 2026-07-14 (xem GOV-007
       trong BACKLOG.md: skip-if-any-data từng khiến nhiều quỹ không bao giờ
       được tcinvest khoá, dẫn tới NAV bị fmarket ghi đè sai xen kẽ nhiều tháng).

    An toàn để chạy lại định kỳ như một lệnh RECONCILE toàn bộ 33 quỹ
    (không chỉ để build lần đầu) — dùng việc này để đối chiếu nguồn NAV
    theo chu kỳ (vd hàng tuần) thay vì chỉ tin daily fetch.
    """
    log("=" * 60)
    log(f"TCINVEST BULK FETCH — {len(TCINVEST_FUNDS)} quy xac nhan")
    log("=" * 60)

    # Step 1: Seed 31 quỹ xác nhận vào funds_master
    new_seeded = 0
    with conn.cursor() as cur:
        for code, info in TCINVEST_FUNDS.items():
            cur.execute("""
                INSERT INTO funds_master (code, name, source, category)
                VALUES (%s, %s, 'tcinvest', %s)
                ON CONFLICT (code) DO UPDATE SET
                    name       = COALESCE(funds_master.name, EXCLUDED.name),
                    source     = CASE WHEN funds_master.source IS NULL
                                      THEN 'tcinvest' ELSE funds_master.source END,
                    updated_at = NOW()
            """, (code, info.get("name", code), info.get("category", "")))
            if cur.rowcount > 0:
                new_seeded += 1
    conn.commit()
    log(f"Seed: {len(TCINVEST_FUNDS)} quy vao funds_master ({new_seeded} moi)")

    # Step 2: Thử catalog API — bổ sung nếu có quỹ mới
    catalog_items = tcinvest_get_catalog(jwt)
    extra = 0
    if catalog_items:
        with conn.cursor() as cur:
            for item in catalog_items:
                code = (
                    item.get("fundCode") or item.get("code") or
                    item.get("shortName") or item.get("symbol") or ""
                ).upper().strip()
                if not code or code in TCINVEST_FUNDS:
                    continue
                name = item.get("fundName") or item.get("name") or code
                cat  = item.get("fundType") or item.get("type") or ""
                cur.execute("""
                    INSERT INTO funds_master (code, name, source, category)
                    VALUES (%s, %s, 'tcinvest', %s)
                    ON CONFLICT DO NOTHING
                """, (code, name, cat))
                if cur.rowcount > 0:
                    extra += 1
        conn.commit()
        if extra:
            log(f"Catalog API: them {extra} quy moi ngoai danh sach 31")

    # Danh sách cuối cùng cần fetch
    codes_to_fetch = list(TCINVEST_FUNDS.keys())
    if extra:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code FROM funds_master WHERE source='tcinvest' AND active=true"
            )
            codes_to_fetch = [r[0] for r in cur.fetchall()]

    log(f"\nBat dau fetch NAV history cho {len(codes_to_fetch)} quy...")
    log("(Moi quy ~1-3s, tong ~2-5 phut)\n")

    log(f"\n📥 Bắt đầu fetch NAV history cho {len(codes_to_fetch)} quỹ...")
    log("   (Mỗi quỹ ~1-3s. Tổng ước tính: ~2-10 phút)\n")

    total_new   = 0
    ok_funds    = []
    skip_funds  = []

    for i, code in enumerate(sorted(codes_to_fetch), 1):
        # Skip quỹ temp (từ scan)
        if code.startswith("FMKT_"):
            skip_funds.append(code)
            continue

        # GOV-007 (2026-07-14): KHÔNG skip chỉ vì đã có data — data cũ đó có thể
        # là 'fmarket' (không đáng tin) chứ không phải 'tcinvest'. Bug trước đây:
        # skip-if-any-row khiến các quỹ có sẵn lịch sử fmarket (VD: VCBFTBF,
        # DCDS, TCBF...) KHÔNG BAO GIỜ được tcinvest backfill/khoá, nên job daily
        # fmarket-fallback tiếp tục ghi đè xen kẽ ("sawtooth") nhiều tháng liền
        # mà không ai phát hiện. Giờ luôn fetch rồi dùng _insert_nav_points()
        # (UPDATE có điều kiện, không phải ON CONFLICT DO NOTHING) để tcinvest
        # tự nâng cấp mọi ngày đang có nguồn thấp hơn (fmarket/tcbs cũ), đồng
        # thời vẫn tôn trọng khoá fixed/manual đã có.
        log(f"  [{i:3d}/{len(codes_to_fetch)}] {code:10} fetching...")
        pts = tcinvest_fetch_nav_hist(code, jwt)

        if not pts:
            log(f"    → 0 điểm")
            skip_funds.append(code)
            time.sleep(0.3)
            continue

        new_rows = _insert_nav_points(conn, code, pts, source="tcinvest")
        total_new += new_rows
        ok_funds.append(code)
        log(f"    → {len(pts):>5} điểm, +{new_rows} mới | {pts[0]['date']} → {pts[-1]['date']}")
        time.sleep(0.5)  # gentle rate limiting

    log(f"\n{'=' * 60}")
    log(f"✅ TCinvest bulk fetch hoàn tất!")
    log(f"   +{total_new:,} records mới vào nav_history")
    log(f"   {len(ok_funds)} quỹ có data: {', '.join(ok_funds[:20])}")
    if len(ok_funds) > 20:
        log(f"   ... và {len(ok_funds) - 20} quỹ khác")
    if skip_funds:
        log(f"   {len(skip_funds)} quỹ không có data: {', '.join(skip_funds[:10])}")


def cmd_reverify(conn, jwt: str, only_code: Optional[str] = None) -> None:
    """GOV-008/T2-014 (2026-07-15): Cơ chế 3-layer re-verification cho NAV nguồn
    'tcinvest'. Bài học vụ VCBFTBF: script reconcile thủ công khóa cứng NAV ngay
    lần fetch đầu, nhưng TCBS công bố NAV ngày mới nhất có thể còn tạm tính, tự
    sửa lại vài giờ/vài ngày sau. Chạy hàng ngày: fetch lại tcinvest, so với giá
    trị đã lưu cho từng ngày — khớp thì nâng verify_tier (T+1/T+8/T+31), lệch
    thì coi là TCBS tự sửa, cập nhật + reset tier (xem db.reverify_nav_tier()).
    """
    sys.path.insert(0, str(ROOT / "telegram-bot"))
    import db as _db
    _db.init_pool()

    codes_to_fetch = [only_code.upper()] if only_code else list(TCINVEST_FUNDS.keys())
    log(f"Re-verify NAV (3-layer) cho {len(codes_to_fetch)} quỹ...")

    upgraded = corrected = unchanged = skipped = 0
    for i, code in enumerate(sorted(codes_to_fetch), 1):
        if code.startswith("FMKT_"):
            continue
        pts = tcinvest_fetch_nav_hist(code, jwt)
        if not pts:
            log(f"  [{i:3d}/{len(codes_to_fetch)}] {code:10} → 0 điểm, bỏ qua")
            skipped += 1
            time.sleep(0.3)
            continue

        code_upgraded = code_corrected = code_unchanged = 0
        for p in pts:
            try:
                nav_dt = date.fromisoformat(p["date"])
            except ValueError:
                continue
            result = _db.reverify_nav_tier(code, nav_dt, p["nav"])
            if result == "upgraded":
                code_upgraded += 1
            elif result == "corrected":
                code_corrected += 1
            elif result == "unchanged":
                code_unchanged += 1

        upgraded += code_upgraded
        corrected += code_corrected
        unchanged += code_unchanged
        if code_corrected:
            log(f"  [{i:3d}/{len(codes_to_fetch)}] {code:10} ⚠ {code_corrected} điểm bị TCBS tự sửa lại, "
                f"{code_upgraded} nâng tier, {code_unchanged} không đổi")
        else:
            log(f"  [{i:3d}/{len(codes_to_fetch)}] {code:10} {code_upgraded} nâng tier, {code_unchanged} không đổi")
        time.sleep(0.3)

    log(f"\n{'=' * 60}")
    log(f"✅ Re-verify hoàn tất: {upgraded} nâng tier, {corrected} bị TCBS tự sửa lại "
        f"(đã cập nhật + reset tier), {unchanged} không đổi, {skipped} quỹ bỏ qua")
    if corrected:
        log(f"⚠ Có {corrected} điểm NAV đã 'chốt' trước đó bị TCBS tự sửa lại — "
            f"xem audit_log (action=nav_reverify_corrected) để biết chi tiết quỹ/ngày nào.")


def cmd_tcinvest_nodb(jwt: str, out_path: Optional[str] = None) -> None:
    """
    Fetch NAV history toàn bộ 31 TCinvest funds mà KHÔNG cần database.
    Lưu kết quả ra file JSON local để import sau.
    """
    log("=" * 60)
    log(f"TCINVEST BULK FETCH (no-db mode) — {len(TCINVEST_FUNDS)} quy")
    log("=" * 60)

    result: dict[str, list] = {}
    ok_funds: list[str] = []
    skip_funds: list[str] = []
    total_pts = 0

    codes = sorted(TCINVEST_FUNDS.keys())
    for i, code in enumerate(codes, 1):
        log(f"  [{i:3d}/{len(codes)}] {code:10} fetching...")
        pts = tcinvest_fetch_nav_hist(code, jwt)
        if not pts:
            log(f"    → 0 điểm — skip")
            skip_funds.append(code)
            time.sleep(0.3)
            continue
        result[code] = pts
        ok_funds.append(code)
        total_pts += len(pts)
        log(f"    → {len(pts):>5} điểm | {pts[0]['date']} → {pts[-1]['date']}")
        time.sleep(0.5)

    # Save JSON
    if out_path is None:
        out_path = str(ROOT / "scripts" / f"tcinvest_nav_{date.today().isoformat()}.json")

    export = {
        "_exported_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
        "_source":       "TCinvest bulk fetch (--no-db)",
        "_total_funds":  len(ok_funds),
        "_total_points": total_pts,
        "_ok_funds":     ok_funds,
        "_skip_funds":   skip_funds,
        "funds": result,
    }
    Path(out_path).write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"\n{'=' * 60}")
    log(f"✅ Hoàn tất! Đã lưu → {out_path}")
    log(f"   {len(ok_funds)}/{len(codes)} quỹ có data | {total_pts:,} điểm NAV tổng cộng")
    if skip_funds:
        log(f"   Skip: {', '.join(skip_funds)}")
    log(f"\nBước tiếp theo (import vào DB khi có DATABASE_URL):")
    log(f"   python scripts/import_tcinvest_json.py {out_path}")


def _load_jwt_from_config() -> str:
    """Đọc TCBS JWT từ config.json.

    Ưu tiên $DATA_DIR/config.json (Railway volume — nơi bot.py/miniapp_server.py
    thực sự đọc/ghi tcbs_token qua /admin settoken). Fallback về
    telegram-bot/config.json (bản build-time trong Docker image, chỉ dùng khi
    chạy local không có DATA_DIR) — bản này KHÔNG BAO GIỜ được cập nhật bởi
    /admin settoken trên Railway nên có thể chứa token cũ/hết hạn.
    """
    candidates = []
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        candidates.append(Path(data_dir) / "config.json")
    candidates.append(ROOT / "telegram-bot" / "config.json")
    for cfg_path in candidates:
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                token = cfg.get("tcbs_token", "")
                if token:
                    return token
            except Exception:
                pass
    return ""


# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(f"[{ts}] {safe}", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master NAV Data Pipeline — Fund Tracker Pro",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Lần đầu (one-time core database từ TCinvest):
  python3 scripts/harvest_nav.py --tcinvest
  python3 scripts/harvest_nav.py --tcinvest --jwt eyJhbGci...  (nếu config.json không có token)

Khám phá + backfill từ fmarket:
  python3 scripts/harvest_nav.py --discover
  python3 scripts/harvest_nav.py --backfill

Hàng ngày (cron 18:30):
  python3 scripts/harvest_nav.py --daily

Kiểm tra:
  python3 scripts/harvest_nav.py --status
        """
    )
    parser.add_argument("--discover",   action="store_true", help="Build/update fund registry từ fmarket")
    parser.add_argument("--backfill",   action="store_true", help="Fetch full history từ fmarket")
    parser.add_argument("--tcinvest",   action="store_true", help="One-time bulk fetch từ TCinvest (dùng JWT)")
    parser.add_argument("--daily",      action="store_true", help="Fetch NAV mới nhất (daily job)")
    parser.add_argument("--reverify",   action="store_true",
                        help="GOV-008: re-verify NAV tcinvest 3 lớp T+1/T+8/T+31 (daily job)")
    parser.add_argument("--status",     action="store_true", help="Tổng quan DB")
    parser.add_argument("--code",       type=str, default=None, metavar="CODE",
                        help="Giới hạn 1 quỹ (dùng với --backfill hoặc --daily)")
    parser.add_argument("--jwt",        type=str, default=None, metavar="TOKEN",
                        help="TCBS JWT token (mặc định đọc từ telegram-bot/config.json)")
    parser.add_argument("--id-start",   type=int, default=1,   help="ID scan start (default: 1)")
    parser.add_argument("--id-end",     type=int, default=200,  help="ID scan end (default: 200)")
    parser.add_argument("--no-db",      action="store_true",
                        help="Chạy --tcinvest không cần DB, lưu kết quả ra JSON")
    args = parser.parse_args()

    if not any([args.discover, args.backfill, args.tcinvest, args.daily, args.reverify, args.status]):
        parser.print_help()
        return

    # --no-db mode: chỉ hỗ trợ --tcinvest, không cần DATABASE_URL
    if args.no_db:
        if not args.tcinvest:
            sys.exit("❌ --no-db chỉ dùng được với --tcinvest")
        jwt = args.jwt or _load_jwt_from_config()
        if not jwt:
            sys.exit(
                "❌ Cần TCBS JWT token.\n"
                "Truyền trực tiếp: --jwt eyJhbGci...\n"
                "Hoặc đảm bảo telegram-bot/config.json có 'tcbs_token'."
            )
        cmd_tcinvest_nodb(jwt)
        return

    conn = connect_db()
    ensure_schema(conn)

    try:
        if args.status:
            cmd_status(conn)
        if args.discover:
            cmd_discover(conn, args.id_start, args.id_end)
        if args.tcinvest:
            jwt = args.jwt or _load_jwt_from_config()
            if not jwt:
                sys.exit(
                    "❌ Cần TCBS JWT token.\n"
                    "Cách lấy: Gõ /otp trong Telegram bot để refresh token,\n"
                    "hoặc truyền trực tiếp: --jwt eyJhbGci...\n"
                    "Hoặc đảm bảo telegram-bot/config.json có 'tcbs_token'."
                )
            cmd_tcinvest(conn, jwt)
        if args.backfill:
            cmd_backfill(conn, only_code=args.code)
        if args.daily:
            cmd_daily(conn, only_code=args.code, jwt=args.jwt)
        if args.reverify:
            jwt = args.jwt or _load_jwt_from_config()
            if not jwt:
                sys.exit(
                    "❌ Cần TCBS JWT token cho --reverify.\n"
                    "Truyền trực tiếp: --jwt eyJhbGci...\n"
                    "Hoặc đảm bảo telegram-bot/config.json có 'tcbs_token'."
                )
            cmd_reverify(conn, jwt, only_code=args.code)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
