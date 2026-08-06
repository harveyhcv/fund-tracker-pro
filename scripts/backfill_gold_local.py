#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_gold_local.py — Lấy toàn bộ lịch sử giá vàng vào local SQLite

Nguồn:
  SJC_1L   : giavang.org (biểu đồ nhúng, ~40-60 ngày gần nhất)
  XAUUSD   : Yahoo Finance GC=F (10 năm lịch sử)

Chạy:
    python scripts/backfill_gold_local.py

Sau khi chạy xong, restart local_dev_server.py để dùng data mới.
"""

import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).parent.parent
DB_PATH = ROOT / "telegram-bot" / "miniapp" / "local_users.db"
UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0"


def _req(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_prices (
            price_date TEXT NOT NULL, source TEXT NOT NULL, product TEXT NOT NULL,
            buy_price REAL, sell_price REAL, currency TEXT DEFAULT 'VND', extra TEXT,
            updated_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
            PRIMARY KEY (price_date, source, product)
        )
    """)
    conn.commit()


def upsert(conn, price_date: str, source: str, product: str,
           buy: float, sell: float, currency: str = "VND", extra: dict = None):
    conn.execute("""
        INSERT INTO gold_prices (price_date, source, product, buy_price, sell_price, currency, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(price_date, source, product) DO UPDATE SET
            buy_price=excluded.buy_price, sell_price=excluded.sell_price,
            extra=excluded.extra, updated_at=strftime('%Y-%m-%d %H:%M:%S','now')
    """, (price_date, source, product, buy, sell, currency,
          json.dumps(extra or {})))


# ── Nguồn 1: giavang.org — SJC_1L chart data ─────────────────────────────────

def fetch_sjc_giavang_org() -> list:
    """Lấy toàn bộ lịch sử SJC từ biểu đồ nhúng trong giavang.org."""
    print("► giavang.org (SJC lịch sử)...")
    try:
        html = _req("https://giavang.org/").decode("utf-8", errors="replace")
        buy_m  = re.search(r'name:"Mua vào",data:(\[\[.*?\]\])', html)
        sell_m = re.search(r'name:"Bán ra",data:(\[\[.*?\]\])', html)
        if not (buy_m and sell_m):
            print("  Không tìm thấy chart data trong giavang.org")
            return []
        buy_pts  = json.loads(buy_m.group(1))
        sell_pts = json.loads(sell_m.group(1))
        vn_tz = timezone(timedelta(hours=7))
        buy_by_date  = {datetime.fromtimestamp(t/1000, tz=vn_tz).date().isoformat(): v
                        for t, v in buy_pts}
        sell_by_date = {datetime.fromtimestamp(t/1000, tz=vn_tz).date().isoformat(): v
                        for t, v in sell_pts}
        result = []
        for d in sorted(buy_by_date):
            if d in sell_by_date:
                result.append({
                    "date": d,
                    "buy":  round(buy_by_date[d]  * 1_000_000),
                    "sell": round(sell_by_date[d] * 1_000_000),
                })
        print(f"  Tìm thấy {len(result)} ngày ({result[0]['date'] if result else '?'} → {result[-1]['date'] if result else '?'})")
        return result
    except Exception as e:
        print(f"  Lỗi: {e}")
        return []


# ── Nguồn 2: Yahoo Finance — XAU/USD 10 năm ──────────────────────────────────

def fetch_xauusd_yahoo(years: int = 10) -> list:
    """Lấy lịch sử XAU/USD từ Yahoo Finance (GC=F futures)."""
    print(f"► Yahoo Finance XAU/USD ({years} năm)...")
    for symbol in ("GC=F", "XAUUSD=X"):
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(symbol)}?interval=1d&range={years}y")
            data   = json.loads(_req(url))
            result_data = data["chart"]["result"][0]
            timestamps = result_data["timestamp"]
            closes     = result_data["indicators"]["quote"][0]["close"]
            out = []
            for ts, c in zip(timestamps, closes):
                if c is None:
                    continue
                d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
                out.append({"date": d, "close": round(c, 2)})
            if out:
                print(f"  {symbol}: {len(out)} ngày ({out[0]['date']} → {out[-1]['date']})")
                return out
        except Exception as e:
            print(f"  {symbol}: {e}")
    return []


def fetch_usd_vnd() -> float:
    """Tỷ giá USD/VND từ Vietcombank."""
    try:
        url = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
        import xml.etree.ElementTree as ET
        root = ET.fromstring(_req(url))
        for item in root.iter("Exrate"):
            if item.get("CurrencyCode") == "USD":
                sell = item.get("Sell", "").replace(",", "")
                if sell:
                    return float(sell)
    except Exception:
        pass
    return 25_400.0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import urllib.parse  # needed for Yahoo URL

    print(f"\nDB: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    ensure_table(conn)

    # Lấy existing dates để tránh overwrite
    existing_sjc  = {r[0] for r in conn.execute(
        "SELECT price_date FROM gold_prices WHERE product='SJC_1L'"
    ).fetchall()}
    existing_xau  = {r[0] for r in conn.execute(
        "SELECT price_date FROM gold_prices WHERE product='XAUUSD'"
    ).fetchall()}
    print(f"Hiện có: {len(existing_sjc)} ngày SJC, {len(existing_xau)} ngày XAU/USD\n")

    # ── SJC từ giavang.org ──
    sjc_data = fetch_sjc_giavang_org()
    sjc_new = 0
    for pt in sjc_data:
        upsert(conn, pt["date"], "VANGTODAYAPI", "SJC_1L", pt["buy"], pt["sell"],
               extra={"source": "giavang.org", "backfilled": True})
        if pt["date"] not in existing_sjc:
            sjc_new += 1
    conn.commit()
    print(f"  Đã lưu {len(sjc_data)} điểm SJC (+{sjc_new} mới)\n")

    # ── XAU/USD từ Yahoo ──
    usd_vnd  = fetch_usd_vnd()
    print(f"  USD/VND: {usd_vnd:,.0f}")
    xau_data = fetch_xauusd_yahoo(years=10)
    xau_new  = 0
    for pt in xau_data:
        xau_vnd = round(pt["close"] * usd_vnd * (37.5 / 31.1035))
        upsert(conn, pt["date"], "VANGTODAYAPI", "XAUUSD", pt["close"], pt["close"],
               currency="USD",
               extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd, "backfilled": True})
        if pt["date"] not in existing_xau:
            xau_new += 1
    conn.commit()
    print(f"  Đã lưu {len(xau_data)} điểm XAU/USD (+{xau_new} mới)\n")

    # ── Summary ──
    rows = conn.execute("""
        SELECT product, COUNT(*) AS cnt, MIN(price_date), MAX(price_date)
        FROM gold_prices GROUP BY product ORDER BY product
    """).fetchall()
    conn.close()
    print("─" * 55)
    print(f"{'Product':<25} {'Ngày':>6}  {'Từ':<12} {'Đến':<12}")
    print("─" * 55)
    for prod, cnt, first, last in rows:
        print(f"  {prod:<23} {cnt:>6}  {first}  {last}")
    print("─" * 55)
    print("\nXong! Restart local_dev_server.py để dùng data mới.")


if __name__ == "__main__":
    import urllib.parse
    main()
