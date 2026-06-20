"""
pg_init.py — Initialise PostgreSQL schema for Fund Tracker Pro.
Run once: python scripts/pg_init.py
Requires DATABASE_URL env var.
"""
import os
import sys
from pathlib import Path

SCHEMA = Path(__file__).parent.parent / "schema.sql"


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("ERROR: DATABASE_URL not set.")
    try:
        import psycopg2
    except ImportError:
        sys.exit("ERROR: psycopg2-binary not installed. Run: pip install psycopg2-binary")

    print(f"Connecting to DB...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    sql = SCHEMA.read_text(encoding="utf-8")
    print(f"Executing {SCHEMA.name} ({len(sql)} bytes)...")
    cur.execute(sql)

    cur.execute("SELECT count(*) FROM funds;")
    count = cur.fetchone()[0]
    print(f"OK — funds table has {count} rows (expect 19)")

    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
