#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — Lấy giá vàng SJC + DOJI + XAU/USD và lưu vào PostgreSQL

Sản phẩm theo dõi:
  SJC_1L      Vàng miếng SJC 1 lượng          (từ sjc.com.vn)
  DOJI_SJC_1L Vàng miếng SJC 1 lượng tại DOJI (từ doji.vn)
  DOJI_NHAN   Vàng nhẫn DOJI 999.9            (từ doji.vn)
  XAU_USD     Vàng quốc tế                    (Yahoo Finance, USD/troy oz)

Chạy daily (cron 18:30):
    python3 scripts/fetch_gold.py --daily
    python3 scripts/fetch_gold.py --status
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent


# ── DB ────────────────────────────────────────────────────────────────────────

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    cfg = ROOT / "telegram-bot" / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("database_url", "")
        except Exception:
            pass
    sys.exit("❌ DATABASE_URL không tìm thấy")


def connect_db():
    try:
        import psycopg2
        return psycopg2.connect(_get_db_url(), connect_timeout=10)
    except ImportError:
        sys.exit("❌ psycopg2 chưa cài: pip install psycopg2-binary")


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
        # Migrate cũ: nếu cột product chưa tồn tại, thêm vào
        try:
            cur.execute("""
                ALTER TABLE gold_prices ADD COLUMN IF NOT EXISTS product TEXT NOT NULL DEFAULT 'default';
            """)
        except Exception:
            pass
        # Thêm unique constraint mới nếu cần
        try:
            cur.execute("""
                ALTER TABLE gold_prices
                    DROP CONSTRAINT IF EXISTS gold_prices_price_date_source_key;
            """)
        except Exception:
            pass
    conn.commit()


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _parse_price(val) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(" ", "").replace(",", "")
    # Nếu có dấu chấm mà độ dài phần thập phân <= 3 → dấu thập phân
    # VD: "89.500.000" → 89500000; "3.141" → 3141 (VND thường không có thập phân)
    s = s.replace(".", "")
    try:
        v = float(s)
        # Sanity check: giá vàng VN dao động 5M–200M VND/lượng
        if v < 1_000:       # quá nhỏ → có thể đơn vị triệu
            v *= 1_000_000
        elif v > 500_000_000:  # > 500M → có thể đơn vị đồng nhưng sai
            v /= 1000
        return v
    except Exception:
        return None


def _req(url: str, timeout: int = 12) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0) AppleWebKit/605.1.15",
        "Accept": "application/json, text/html, */*",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── Fetch SJC official ────────────────────────────────────────────────────────

def fetch_sjc_official() -> Optional[dict]:
    """
    Lấy giá SJC miếng 1 lượng (VND/lượng).
    Thử: (1) SJC XML chính thức, (2) scrape giavang.doji.vn (họ niêm yết giá SJC).
    """
    # Thử 1: SJC XML — sjc.com.vn/xml/tygia.xml (có thể 403/404 tùy thời điểm)
    for sjc_url in ("https://sjc.com.vn/xml/tygia.xml", "https://www.sjc.com.vn/xml/tygia.xml"):
        try:
            raw = _req(sjc_url).decode("utf-8", errors="replace")
            root = ET.fromstring(raw)
            candidates = []
            for item in root.iter():
                name = (item.get("name") or item.findtext("name") or "").lower()
                buy_raw  = item.get("buy")  or item.findtext("buy")
                sell_raw = item.get("sell") or item.findtext("sell")
                if not buy_raw or not sell_raw:
                    continue
                buy  = _parse_price(buy_raw)
                sell = _parse_price(sell_raw)
                if buy and sell and 50_000_000 < sell < 250_000_000:
                    score = 0
                    if "1l" in name or "1 l" in name: score += 3
                    if "sjc" in name:                  score += 2
                    if "mieng" in name or "miếng" in name: score += 1
                    candidates.append((score, buy, sell, name))
            if candidates:
                candidates.sort(reverse=True)
                _, buy, sell, matched_name = candidates[0]
                return {"buy": buy, "sell": sell, "name": matched_name}
        except Exception:
            pass

    # Thử 2: scrape giavang.doji.vn (có giá SJC bán lẻ chính xác)
    try:
        html = _req(_DOJI_GOLD_URL).decode("utf-8", errors="replace")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            if len(cells) < 3:
                continue
            name = re.sub(r"<[^>]+>", " ", cells[0]).strip().lower()
            if "sjc" not in name or "bán lẻ" not in name:
                continue
            nums = []
            for c in cells[1:]:
                txt = re.sub(r"<[^>]+>", "", c).strip().replace(".", "").replace(",", "")
                try:
                    v = float(txt)
                    if 5_000 < v < 500_000:
                        nums.append(v)
                except ValueError:
                    pass
            if len(nums) >= 2:
                return {"buy": round(nums[0] * 10_000), "sell": round(nums[1] * 10_000),
                        "name": "SJC bán lẻ (nguồn DOJI)"}
    except Exception as e:
        print(f"  ⚠ SJC từ DOJI: {e}", file=sys.stderr)
    return None


# ── Fetch DOJI ────────────────────────────────────────────────────────────────

_DOJI_GOLD_URL = "https://giavang.doji.vn/"

def fetch_doji() -> dict:
    """
    Scrape giavang.doji.vn — bảng giá HTML, đơn vị nghìn/chỉ → quy về VND/lượng.
    Trả về dict: {"SJC_1L": {"buy":..., "sell":...}, "DOJI_NHAN_9999": {...}, ...}
    """
    results = {}
    try:
        html = _req(_DOJI_GOLD_URL).decode("utf-8", errors="replace")
        # Mỗi row: <tr>...Tên sản phẩm...<td>MUA</td><td>BÁN</td>...</tr>
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            if len(cells) < 3:
                continue
            name = re.sub(r"<[^>]+>", " ", cells[0]).strip()
            # Tìm 2 số đầu tiên trong các ô còn lại
            nums = []
            for c in cells[1:]:
                txt = re.sub(r"<[^>]+>", "", c).strip().replace(".", "").replace(",", "")
                try:
                    v = float(txt)
                    if 5_000 < v < 500_000:   # nghìn/chỉ range
                        nums.append(v)
                except ValueError:
                    pass
            if len(nums) < 2:
                continue
            # Đơn vị: nghìn/chỉ → VND/lượng = value * 1000 * 10
            buy  = round(nums[0] * 10_000)
            sell = round(nums[1] * 10_000)
            nl   = name.lower()

            if "sjc" in nl and "bán lẻ" in nl:
                if "SJC_1L" not in results:
                    results["SJC_1L"] = {"buy": buy, "sell": sell, "name": f"SJC Bán lẻ (DOJI)"}
            elif "nhẫn" in nl or "nhan" in nl:
                key = "DOJI_NHAN_9999" if ("9999" in nl or "999.9" in nl or "hưng thịnh" in nl) else "DOJI_NHAN"
                if key not in results:
                    results[key] = {"buy": buy, "sell": sell, "name": name[:50]}
    except Exception as e:
        print(f"  ⚠ DOJI scrape: {e}", file=sys.stderr)
    return results


# ── Fetch XAU/USD ─────────────────────────────────────────────────────────────

def fetch_xauusd() -> Optional[float]:
    """Giá vàng quốc tế USD/troy oz."""
    for symbol in ("GC=F", "XAUUSD=X"):
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(symbol)}?interval=1d&range=2d")
            data   = json.loads(_req(url))
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                return round(closes[-1], 2)
        except Exception as e:
            print(f"  ⚠ XAU/USD ({symbol}): {e}", file=sys.stderr)
    return None


def fetch_usd_vnd() -> Optional[float]:
    """Tỷ giá USD/VND từ Vietcombank."""
    try:
        url = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
        raw  = _req(url).decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        for item in root.iter("Exrate"):
            if item.get("CurrencyCode") == "USD":
                sell = item.get("Sell", "").replace(",", "")
                return float(sell) if sell else None
    except Exception as e:
        print(f"  ⚠ USD/VND: {e}", file=sys.stderr)
    return None


# ── DB upsert ─────────────────────────────────────────────────────────────────

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


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_daily(verbose: bool = True) -> dict:
    today   = date.today()
    results = {}
    conn    = connect_db()
    ensure_schema(conn)

    # 1. SJC official
    sjc = fetch_sjc_official()
    if sjc:
        upsert(conn, today, "SJC", "SJC_1L", sjc["buy"], sjc["sell"])
        results["SJC_1L"] = sjc
        if verbose:
            print(f"  ✅ SJC official  Mua:{sjc['buy']/1e6:.3f}M  Bán:{sjc['sell']/1e6:.3f}M VND/lượng")
    else:
        results["SJC_error"] = "Không lấy được"
        if verbose:
            print("  ❌ SJC official — không lấy được giá")

    # 2. DOJI products
    doji = fetch_doji()
    for product, d in doji.items():
        upsert(conn, today, "DOJI", product, d["buy"], d["sell"],
               extra={"name": d["name"]})
        results[f"DOJI_{product}"] = d
        if verbose:
            print(f"  ✅ DOJI {product:15s} Mua:{d['buy']/1e6:.3f}M  Bán:{d['sell']/1e6:.3f}M")
    if not doji and verbose:
        print("  ⚠ DOJI — không lấy được giá (API có thể thay đổi)")

    # 3. XAU/USD + tỷ giá
    xau = fetch_xauusd()
    if xau:
        usd_vnd         = fetch_usd_vnd() or 25_400.0
        xau_vnd_luong   = round(xau * usd_vnd * (37.5 / 31.1035))
        upsert(conn, today, "INTERNATIONAL", "XAU_USD", xau, xau, currency="USD",
               extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd_luong})
        results["XAU_USD"] = {"price_usd": xau, "usd_vnd": usd_vnd,
                               "vnd_luong": xau_vnd_luong}
        if verbose:
            print(f"  ✅ XAU/USD  {xau:,.2f} USD/oz ≈ {xau_vnd_luong/1e6:.2f}M VND/lượng")
    else:
        if verbose:
            print("  ❌ XAU/USD — không lấy được")

    conn.commit()
    conn.close()
    return results


def run_status():
    conn = connect_db()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source, product, COUNT(*) AS cnt,
                   MIN(price_date) AS first, MAX(price_date) AS last,
                   MAX(sell_price) AS latest_sell
            FROM gold_prices
            GROUP BY source, product ORDER BY source, product
        """)
        rows = cur.fetchall()
    conn.close()
    print(f"\n📊 Gold DB Status — {len(rows)} sản phẩm")
    print(f"{'Source':<14} {'Product':<18} {'#':>5}  {'First':>12}  {'Last':>12}  {'Sell':>18}")
    print("-" * 85)
    for r in rows:
        src, prod, cnt, first, last, sell = r
        print(f"{src:<14} {prod:<18} {cnt:>5}  {str(first):>12}  {str(last):>12}  "
              f"{sell:>18,.0f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daily",  action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.daily:
        print(f"🔄 Fetch gold prices ({date.today()})...")
        run_daily()
        print("✅ Done")
    elif args.status:
        run_status()
    else:
        p.print_help()
