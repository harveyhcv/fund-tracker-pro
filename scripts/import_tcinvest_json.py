#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_tcinvest_json.py — Import tcinvest_nav_*.json vào PostgreSQL Railway

Usage:
    python scripts/import_tcinvest_json.py scripts/tcinvest_nav_2026-06-21.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent

DB_URL = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"

# fund_type enum: bond | equity | balanced | money_market | etf
FUND_META = {
    # code: (fund_type, fund_company)
    "TCBF":    ("bond",     "Techcom Capital"),
    "TCFF":    ("equity",   "Techcom Capital"),
    "TCGF":    ("equity",   "Techcom Capital"),
    "TCSME":   ("equity",   "Techcom Capital"),
    "TCEF":    ("equity",   "Techcom Capital"),
    "TCRES":   ("balanced", "Techcom Capital"),
    "TCFIN":   ("equity",   "Techcom Capital"),
    "VCBFTBF": ("bond",     "VCB Fund"),
    "VCBFBCF": ("bond",     "VCB Fund"),
    "VCBFFIF": ("bond",     "VCB Fund"),
    "VCBFMGF": ("equity",   "VCB Fund"),
    "VCBFAIF": ("equity",   "VCB Fund"),
    "VCAMDF":  ("balanced", "VinaCapital"),
    "VCAMBF":  ("bond",     "VinaCapital"),
    "SSISCA":  ("bond",     "SSIAM"),
    "VDEF":    ("equity",   "VietFund Management"),
    "VEOF":    ("equity",   "VietFund Management"),
    "VESAF":   ("equity",   "VietFund Management"),
    "VIBF":    ("bond",     "VietFund Management"),
    "VMEEF":   ("equity",   "VietFund Management"),
    "VMPF":    ("equity",   "VietFund Management"),
    "UVDIF":   ("equity",   "UOB Asset Management"),
    "UVEEF":   ("equity",   "UOB Asset Management"),
    "DCAF":    ("balanced", "Dragon Capital"),
    "DCDE":    ("equity",   "Dragon Capital"),
    "DCDS":    ("equity",   "Dragon Capital"),
    "DFIX":    ("bond",     "Dragon Capital"),
    "KDEF":    ("equity",   "KIM Vietnam"),
    "LHCDF":   ("balanced", "Lien Hiep"),
    "MAGEF":   ("equity",   "Manulife"),
    "PHVSF":   ("equity",   "Phu Hung"),
    "NTPPF":   ("equity",   "NTP Capital"),
    "TVPF":    ("equity",   "NTP Capital"),
}

FUND_NAMES = {
    "TCBF":    "Quỹ Trái Phiếu Techcombank",
    "TCFF":    "Quỹ Tăng Trưởng Techcombank",
    "TCGF":    "Quỹ Tăng Trưởng Toàn Cầu Techcombank",
    "TCSME":   "Quỹ Cổ Phiếu SME Techcombank",
    "TCEF":    "Quỹ Cổ Phiếu Techcombank",
    "TCRES":   "Quỹ Bất Động Sản Techcombank",
    "TCFIN":   "Quỹ Tài Chính Techcombank",
    "VCBFTBF": "Quỹ TPDN Có Bảo Đảm VCB Fund",
    "VCBFBCF": "Quỹ Trái Phiếu Bền Vững VCB Fund",
    "VCBFFIF": "Quỹ Thu Nhập Cố Định VCB Fund",
    "VCBFMGF": "Quỹ Tăng Trưởng VCB Fund",
    "VCBFAIF": "Quỹ Cổ Phiếu VCB Fund",
    "VCAMDF":  "Quỹ Cân Bằng VinaCapital",
    "VCAMBF":  "Quỹ Trái Phiếu VinaCapital",
    "SSISCA":  "Quỹ Tích Lũy Bền Vững SSI",
    "VDEF":    "Quỹ Đầu Tư Tăng Trưởng VietFund",
    "VEOF":    "Quỹ Cổ Phiếu Tăng Trưởng VietFund",
    "VESAF":   "Quỹ Cổ Phiếu Tiếp Cận Thị Trường VietFund",
    "VIBF":    "Quỹ Trái Phiếu VietFund",
    "VMEEF":   "Quỹ Cổ Phiếu VietFund Emerging",
    "VMPF":    "Quỹ Cổ Phiếu VietFund Emerging",
    "UVDIF":   "Quỹ Đầu Tư Cổ Phiếu UOB",
    "UVEEF":   "Quỹ Cổ Phiếu Tăng Trưởng UOB",
    "DCAF":    "Quỹ Cân Bằng Dragon Capital",
    "DCDE":    "Quỹ Cổ Phiếu Dragon Capital",
    "DCDS":    "Quỹ Tăng Trưởng Dragon Capital",
    "DFIX":    "Quỹ Trái Phiếu Dragon Capital",
    "KDEF":    "Quỹ Cổ Phiếu KIM",
    "LHCDF":   "Quỹ Cân Bằng Liên Hiệp",
    "MAGEF":   "Quỹ Cổ Phiếu Manulife",
    "PHVSF":   "Quỹ Cổ Phiếu Phú Hưng",
    "NTPPF":   "Quỹ Cổ Phiếu NTP",
    "TVPF":    "Quỹ Cổ Phiếu NTP",
}


def main():
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "scripts" / "tcinvest_nav_2026-06-21.json"

    if not json_path.exists():
        sys.exit(f"File not found: {json_path}")

    print(f"Loading {json_path.name}...")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    funds: dict = data.get("funds", {})
    total_pts = sum(len(v) for v in funds.values())
    print(f"  {len(funds)} quy | {total_pts:,} diem NAV")

    try:
        import psycopg2
    except ImportError:
        sys.exit("pip install psycopg2-binary")

    print("Connecting to Railway DB...")
    conn = psycopg2.connect(DB_URL)

    # Step 1: Seed funds table (parent of FK)
    print("Seeding funds table...")
    with conn.cursor() as cur:
        for code in funds:
            ftype, company = FUND_META.get(code, ("equity", "Unknown"))
            name = FUND_NAMES.get(code, code)
            cur.execute("""
                INSERT INTO funds (code, name, fund_type, fund_company, active)
                VALUES (%s, %s, %s::fund_type, %s, true)
                ON CONFLICT (code) DO UPDATE SET
                    name         = COALESCE(funds.name, EXCLUDED.name),
                    fund_company = COALESCE(funds.fund_company, EXCLUDED.fund_company),
                    active       = true
            """, (code, name, ftype, company))
    conn.commit()
    print(f"  {len(funds)} quy seeded vao funds")

    # Step 2: Insert nav_history (batched via execute_values — nhanh hơn nhiều
    # so với executemany row-by-row, đặc biệt qua proxy Railway từ xa).
    from psycopg2.extras import execute_values

    # Bỏ qua quỹ đã import đầy đủ (resume an toàn nếu chạy lại sau khi gián đoạn)
    with conn.cursor() as cur:
        cur.execute("SELECT fund_code, COUNT(*) FROM nav_history GROUP BY fund_code")
        existing_counts = dict(cur.fetchall())

    print(f"Inserting {total_pts:,} NAV points (batched)...")
    total_new = 0
    for i, (code, pts) in enumerate(sorted(funds.items()), 1):
        if not pts:
            continue
        # Nếu DB đã có >= số điểm trong JSON cho quỹ này → coi như xong, skip
        if existing_counts.get(code, 0) >= len(pts):
            print(f"  [{i:2d}/{len(funds)}] {code:10} skip (da co {existing_counts[code]} >= {len(pts)})")
            continue
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO nav_history (fund_code, nav_date, nav, source)
                VALUES %s
                ON CONFLICT (fund_code, nav_date) DO NOTHING
            """, [(code, p["date"], p["nav"], "tcinvest") for p in pts],
                template="(%s, %s, %s, %s::data_src)", page_size=1000)
            new = cur.rowcount
        conn.commit()
        total_new += new
        print(f"  [{i:2d}/{len(funds)}] {code:10} {len(pts):>5} pts +{new} moi | "
              f"{pts[0]['date']} -> {pts[-1]['date']}", flush=True)

    # Summary
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM nav_history")
        total_db = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT fund_code) FROM nav_history")
        n_funds = cur.fetchone()[0]
    conn.close()

    print(f"\nDone! +{total_new:,} records moi")
    print(f"DB hien co: {total_db:,} diem | {n_funds} quy")


if __name__ == "__main__":
    main()
