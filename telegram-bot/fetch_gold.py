#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — Lấy giá vàng SJC + DOJI + XAU/USD và lưu vào PostgreSQL

Nguồn chính   : giavang.org/trong-nuoc/sjc/lich-su/YYYY-MM-DD.html (scrape HTML)
Nguồn dự phòng: giavang.doji.vn (scrape)
Quốc tế       : Yahoo Finance (XAU/USD) + Vietcombank (USD/VND)
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"


# ── DB ────────────────────────────────────────────────────────────────────────

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    for cfg_path in [
        Path(__file__).parent / "config.json",
        ROOT / "telegram-bot" / "config.json",
    ]:
        if cfg_path.exists():
            try:
                return json.loads(cfg_path.read_text(encoding="utf-8")).get("database_url", "")
            except Exception:
                pass
    sys.exit("DATABASE_URL không tìm thấy")


def connect_db():
    try:
        import psycopg2
        return psycopg2.connect(_get_db_url(), connect_timeout=10)
    except ImportError:
        sys.exit("psycopg2 chưa cài: pip install psycopg2-binary")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS gold_prices (
    id          SERIAL PRIMARY KEY,
    price_date  DATE            NOT NULL,
    source      TEXT            NOT NULL,
    product     TEXT            NOT NULL DEFAULT 'default',
    buy_price   NUMERIC(18,2),
    sell_price  NUMERIC(18,2),
    currency    TEXT            NOT NULL DEFAULT 'VND',
    extra       JSONB,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (price_date, source, product)
);
CREATE INDEX IF NOT EXISTS idx_gold_date ON gold_prices (price_date DESC);
"""


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
        try:
            cur.execute("ALTER TABLE gold_prices DROP CONSTRAINT IF EXISTS gold_prices_price_date_source_key")
        except Exception:
            pass
    conn.commit()


def upsert(conn, today: date, source: str, product: str,
           buy: float, sell: float, currency: str = "VND", extra: dict = None):
    sql = """
        INSERT INTO gold_prices (price_date, source, product, buy_price, sell_price, currency, extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (price_date, source, product) DO UPDATE
          SET buy_price  = EXCLUDED.buy_price,
              sell_price = EXCLUDED.sell_price,
              extra      = EXCLUDED.extra
    """
    with conn.cursor() as cur:
        cur.execute(sql, (today, source, product, buy, sell, currency, json.dumps(extra or {})))


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _req(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── Nguồn 1: giavang.org ─────────────────────────────────────────────────────

def fetch_giavang_org(today: date) -> Optional[dict]:
    """
    Scrape giavang.org main page — khối "GIÁ VÀNG SJC HÔM NAY" ở đầu trang chứa
    đúng 2 <span class="gold-price"> đầu tiên: Mua vào rồi Bán ra của SJC Miếng.
    Giá dạng "145.400" = 145,400 nghìn đồng/lượng = 145,400,000 VND/lượng.

    KHÔNG dùng heuristic quét toàn trang lấy cặp số đầu tiên trong khoảng hợp lệ —
    cách đó từng vô tình bắt nhầm giá của tổ chức khác (PNJ/DOJI/Bảo Tín...) xuất
    hiện sớm hơn trong HTML, cho ra giá sai ~3M VND/lượng so với giá SJC thật.
    """
    url = "https://giavang.org/"
    try:
        html = _req(url, timeout=15).decode("utf-8", errors="replace")
        spans = re.findall(r'<span class="gold-price">\s*([\d.]+)', html)
        if len(spans) >= 2:
            buy  = int(spans[0].replace(".", "")) * 1000
            sell = int(spans[1].replace(".", "")) * 1000
            if 80_000_000 < buy < 250_000_000 and buy < sell:
                return {"buy": buy, "sell": sell, "source_url": url}
    except Exception as e:
        print(f"  giavang.org: {e}", file=sys.stderr)
    return None


def fetch_giavang_org_history(days: int = 14) -> "list[dict]":
    """Lấy lịch sử SJC Mua/Bán từ biểu đồ nhúng sẵn trong trang (var seriesOptions).
    Trả về [{date, buy, sell}] — dùng để backfill các ngày bị miss (vd: job chưa
    chạy do bot restart/deploy). Giá trị chart tính theo triệu đồng (vd 148.4 → 148,400,000đ).
    """
    url = "https://giavang.org/"
    try:
        html = _req(url, timeout=15).decode("utf-8", errors="replace")
        buy_m  = re.search(r'name:"Mua vào",data:(\[\[.*?\]\])', html)
        sell_m = re.search(r'name:"Bán ra",data:(\[\[.*?\]\])', html)
        if not (buy_m and sell_m):
            return []
        import json as _json
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        vn_tz = _tz(_td(hours=7))
        buy_pts  = _json.loads(buy_m.group(1))
        sell_pts = _json.loads(sell_m.group(1))
        buy_by_date  = {_dt.fromtimestamp(t/1000, tz=vn_tz).date().isoformat(): v for t, v in buy_pts}
        sell_by_date = {_dt.fromtimestamp(t/1000, tz=vn_tz).date().isoformat(): v for t, v in sell_pts}
        result = []
        for d in sorted(buy_by_date.keys())[-days:]:
            if d in sell_by_date:
                result.append({
                    "date": d,
                    "buy":  round(buy_by_date[d]  * 1_000_000),
                    "sell": round(sell_by_date[d] * 1_000_000),
                })
        return result
    except Exception as e:
        print(f"  giavang.org history: {e}", file=sys.stderr)
        return []


# ── Nguồn 2: DOJI scrape (cross-check + nhẫn) ────────────────────────────────

def fetch_doji_scrape() -> dict:
    results = {}
    try:
        html = _req("https://giavang.doji.vn/").decode("utf-8", errors="replace")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            if len(cells) < 3:
                continue
            name = re.sub(r"<[^>]+>", " ", cells[0]).strip()
            nums = []
            for c in cells[1:]:
                txt = re.sub(r"<[^>]+>", "", c).strip().replace(".", "").replace(",", "")
                try:
                    v = float(txt)
                    if 5_000 < v < 500_000:
                        nums.append(v)
                except ValueError:
                    pass
            if len(nums) < 2:
                continue
            buy  = round(nums[0] * 10_000)
            sell = round(nums[1] * 10_000)
            nl   = name.lower()
            if "sjc" in nl and "bán lẻ" in nl and "SJC_1L" not in results:
                results["SJC_1L"] = {"buy": buy, "sell": sell, "name": "SJC (DOJI)"}
            elif ("nhẫn" in nl or "nhan" in nl) and "9999" in nl and "DOJI_NHAN_9999" not in results:
                results["DOJI_NHAN_9999"] = {"buy": buy, "sell": sell, "name": name[:50]}
    except Exception as e:
        print(f"  DOJI scrape: {e}", file=sys.stderr)
    return results


# ── Nguồn 3: XAU/USD Yahoo Finance + Vietcombank ─────────────────────────────

def fetch_xauusd_yahoo() -> Optional[float]:
    for symbol in ("GC=F", "XAUUSD=X"):
        try:
            url  = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                    f"{urllib.parse.quote(symbol)}?interval=1d&range=2d")
            data = json.loads(_req(url))
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                return round(closes[-1], 2)
        except Exception as e:
            print(f"  XAU/USD Yahoo ({symbol}): {e}", file=sys.stderr)
    return None


def fetch_usd_vnd() -> Optional[float]:
    try:
        url  = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
        raw  = _req(url).decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        for item in root.iter("Exrate"):
            if item.get("CurrencyCode") == "USD":
                sell = item.get("Sell", "").replace(",", "")
                return float(sell) if sell else None
    except Exception:
        pass
    return None


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_daily(verbose: bool = True) -> dict:
    today  = date.today()
    conn   = connect_db()
    ensure_schema(conn)
    saved  = {}

    # 1. giavang.org — nguồn chính SJC
    gvo = fetch_giavang_org(today)
    if gvo:
        upsert(conn, today, "VANGTODAYAPI", "SJC_1L", gvo["buy"], gvo["sell"],
               extra={"source": "giavang.org", "source_url": gvo["source_url"]})
        saved["SJC_1L"] = gvo
        if verbose:
            print(f"  SJC_1L (giavang.org)  Mua:{gvo['buy']/1e6:.3f}M  Ban:{gvo['sell']/1e6:.3f}M")
    else:
        if verbose:
            print("  giavang.org: no data — trying DOJI fallback")

    # 2. DOJI scrape — nhẫn + fallback SJC nếu giavang.org lỗi
    doji = fetch_doji_scrape()
    for product, d in doji.items():
        upsert(conn, today, "DOJI_SCRAPE", product, d["buy"], d["sell"],
               extra={"name": d["name"]})
    if verbose and doji:
        for p, d in doji.items():
            print(f"  {p:<20} Ban:{d['sell']/1e6:.3f}M  (DOJI scrape)")

    if "SJC_1L" not in saved and "SJC_1L" in doji:
        d = doji["SJC_1L"]
        upsert(conn, today, "VANGTODAYAPI", "SJC_1L", d["buy"], d["sell"],
               extra={"name": d["name"], "fallback": "doji_scrape"})
        saved["SJC_1L"] = d
        if verbose:
            print(f"  SJC_1L (fallback DOJI) Mua:{d['buy']/1e6:.3f}M  Ban:{d['sell']/1e6:.3f}M")

    # 3. XAU/USD
    xau = fetch_xauusd_yahoo()
    if xau:
        usd_vnd = fetch_usd_vnd() or 25_400.0
        xau_vnd = round(xau * usd_vnd * (37.5 / 31.1035))
        upsert(conn, today, "VANGTODAYAPI", "XAUUSD", xau, xau, currency="USD",
               extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd})
        saved["XAUUSD"] = {"buy": xau, "sell": xau, "usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd}
        if verbose:
            print(f"  XAUUSD (Yahoo)         {xau:,.2f} USD/oz ~ {xau_vnd/1e6:.2f}M VND/luong")

    conn.commit()
    conn.close()
    return saved


def run_backfill(days: int = 14, verbose: bool = True) -> int:
    """Điền các ngày SJC_1L bị thiếu trong gold_prices (vd: bot restart/deploy làm
    job_morning bỏ lỡ vài ngày) bằng lịch sử nhúng sẵn trong giavang.org."""
    hist = fetch_giavang_org_history(days=days)
    if not hist:
        if verbose:
            print("  Không lấy được lịch sử giavang.org")
        return 0
    conn = connect_db()
    ensure_schema(conn)
    filled = 0
    for pt in hist:
        d = date.fromisoformat(pt["date"])
        upsert(conn, d, "VANGTODAYAPI", "SJC_1L", pt["buy"], pt["sell"],
               extra={"source": "giavang.org", "source_url": "https://giavang.org/", "backfilled": True})
        filled += 1
        if verbose:
            print(f"  ✅ {pt['date']}  Mua:{pt['buy']/1e6:.3f}M  Bán:{pt['sell']/1e6:.3f}M")
    conn.commit()
    conn.close()
    return filled


def run_status():
    conn = connect_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source, product, COUNT(*) AS cnt,
                   MIN(price_date) AS first, MAX(price_date) AS last,
                   MAX(sell_price) AS latest_sell
            FROM gold_prices
            GROUP BY source, product ORDER BY last DESC, source
        """)
        rows = cur.fetchall()
    conn.close()
    print(f"\nGold DB — {len(rows)} products")
    for r in rows:
        src, prod, cnt, first, last, sell = r
        print(f"  {src:<16} {prod:<20} #{cnt:<4} {str(first)} -> {str(last)}  sell={sell:,.0f}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--daily",  action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--backfill", type=int, metavar="DAYS", help="Điền N ngày gần nhất còn thiếu")
    args = p.parse_args()
    if args.daily:
        print(f"Fetch gold ({date.today()})...")
        run_daily()
        print("Done")
    elif args.status:
        run_status()
    elif args.backfill:
        print(f"Backfill {args.backfill} ngày gần nhất từ giavang.org...")
        n = run_backfill(days=args.backfill)
        print(f"Done — {n} ngày đã điền")
    else:
        p.print_help()
