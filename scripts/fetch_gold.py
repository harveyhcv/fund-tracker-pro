#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — Lấy giá vàng SJC + XAU/USD và lưu vào PostgreSQL

Sources:
  SJC  : sjc.com.vn/xml/tygia.xml  (giá mua/bán vàng miếng SJC, VND/lượng)
  XAU  : Yahoo Finance GC=F         (giá vàng quốc tế, USD/troy oz)
  USD  : Vietcombank exchange rate   (để quy đổi XAU → VND/lượng)

Chạy daily (cron 18:30 sau giờ thị trường vàng đóng):
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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
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
    buy_price   NUMERIC(18,2),
    sell_price  NUMERIC(18,2),
    currency    TEXT            NOT NULL DEFAULT 'VND',
    extra       JSONB,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (price_date, source)
);
CREATE INDEX IF NOT EXISTS idx_gold_date ON gold_prices (price_date DESC);
"""


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
    conn.commit()


# ── Fetch SJC ─────────────────────────────────────────────────────────────────

_SJC_URL  = "https://sjc.com.vn/xml/tygia.xml"
_DOJI_URL = "https://edge-api.doji.vn/api/v1/prices/sjc"

def _fetch_sjc() -> Optional[dict]:
    """Trả về {buy, sell} VND/lượng từ SJC XML endpoint."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FundTracker/1.0)"}
    # Thử SJC XML
    try:
        req = urllib.request.Request(_SJC_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        # Tìm item vàng miếng SJC 1 lượng
        for item in root.iter():
            name = (item.get("name") or item.findtext("name") or "").lower()
            if "sjc" in name and ("1l" in name or "1k" in name or "mieng" in name or "lượng" in name.lower()):
                buy  = _parse_price(item.get("buy")  or item.findtext("buy"))
                sell = _parse_price(item.get("sell") or item.findtext("sell"))
                if buy and sell:
                    return {"buy": buy, "sell": sell, "source_detail": "sjc_xml"}
        # Thử parse bằng regex nếu XML structure khác
        m_buy  = re.search(r'"buy"\s*:\s*"?([\d,\.]+)"?', raw)
        m_sell = re.search(r'"sell"\s*:\s*"?([\d,\.]+)"?', raw)
        if m_buy and m_sell:
            buy  = _parse_price(m_buy.group(1))
            sell = _parse_price(m_sell.group(1))
            if buy and sell and buy > 1_000_000:
                return {"buy": buy, "sell": sell, "source_detail": "sjc_xml_regex"}
    except Exception as e:
        print(f"  ⚠ SJC XML lỗi: {e}", file=sys.stderr)

    # Thử DOJI API
    try:
        req = urllib.request.Request(_DOJI_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        # DOJI trả về list, tìm SJC 1 lượng
        items = data if isinstance(data, list) else data.get("data", [])
        for it in items:
            n = (it.get("name") or "").lower()
            if "1l" in n or "mieng" in n or ("sjc" in n and "1" in n):
                buy  = _parse_price(it.get("buy") or it.get("buyPrice"))
                sell = _parse_price(it.get("sell") or it.get("sellPrice"))
                if buy and sell:
                    return {"buy": buy, "sell": sell, "source_detail": "doji_api"}
    except Exception as e:
        print(f"  ⚠ DOJI API lỗi: {e}", file=sys.stderr)

    return None


def _parse_price(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace(".", "").replace(" ", "")) / _infer_unit(str(val))
    except Exception:
        return None


def _infer_unit(s: str) -> float:
    """SJC có khi quote x1000 (nghìn đồng), cần detect."""
    clean = float(s.replace(",", "").replace(".", "").replace(" ", ""))
    # Giá vàng SJC hiện tại ~85-100 triệu VND/lượng
    if clean > 1_000_000_000:   # > 1 tỷ → chắc là nghìn đồng
        return 1000.0
    if clean < 10_000:           # < 10k → có thể là triệu đồng
        return 1.0 / 1_000_000
    return 1.0


# ── Fetch XAU/USD (Yahoo Finance) ─────────────────────────────────────────────

_YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"

def _fetch_xauusd() -> Optional[float]:
    """Trả về giá XAU/USD hiện tại (USD/troy oz)."""
    for symbol in ("GC=F", "XAUUSD=X"):
        try:
            url = _YF_URL.format(symbol=urllib.parse.quote(symbol))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                return round(closes[-1], 2)
        except Exception as e:
            print(f"  ⚠ XAU/USD ({symbol}) lỗi: {e}", file=sys.stderr)
    return None


def _fetch_usdt_vnd() -> Optional[float]:
    """Lấy tỷ giá USD/VND từ Vietcombank."""
    try:
        url = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        for item in root.iter("Exrate"):
            if item.get("CurrencyCode") == "USD":
                sell = item.get("Sell", "")
                return float(sell.replace(",", "")) if sell else None
    except Exception as e:
        print(f"  ⚠ USD/VND lỗi: {e}", file=sys.stderr)
    return None


# urllib.parse thêm vào phần trên
import urllib.parse


# ── DB upsert ─────────────────────────────────────────────────────────────────

def upsert_price(conn, today: date, source: str, buy: float, sell: float,
                 currency: str = "VND", extra: dict = None) -> bool:
    sql = """
        INSERT INTO gold_prices (price_date, source, buy_price, sell_price, currency, extra)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (price_date, source) DO UPDATE
          SET buy_price  = EXCLUDED.buy_price,
              sell_price = EXCLUDED.sell_price,
              extra      = EXCLUDED.extra
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (today, source, buy, sell, currency, json.dumps(extra or {})))
        return cur.fetchone() is not None


# ── Main fetch pipeline ────────────────────────────────────────────────────────

def run_daily(verbose: bool = True) -> dict:
    today    = date.today()
    results  = {}
    conn     = connect_db()
    ensure_schema(conn)

    # 1. SJC
    sjc = _fetch_sjc()
    if sjc:
        upsert_price(conn, today, "SJC", sjc["buy"], sjc["sell"],
                     currency="VND", extra={"source_detail": sjc.get("source_detail")})
        results["sjc"] = sjc
        if verbose:
            buy_m  = sjc["buy"]  / 1_000_000
            sell_m = sjc["sell"] / 1_000_000
            print(f"  ✅ SJC  {today}  Mua: {buy_m:.3f}M  Bán: {sell_m:.3f}M  VND/lượng")
    else:
        results["sjc_error"] = "Không fetch được giá SJC"
        if verbose:
            print(f"  ❌ SJC  {today}  Không lấy được giá")

    # 2. XAU/USD
    xau = _fetch_xauusd()
    if xau:
        usd_vnd = _fetch_usdt_vnd() or 25400.0   # fallback tỷ giá
        # Quy đổi: XAU (USD/troy oz) → VND/lượng
        # 1 lượng = 37.5g, 1 troy oz = 31.1035g
        xau_vnd_luong = xau * usd_vnd * (37.5 / 31.1035)
        upsert_price(conn, today, "XAU_USD", xau, xau, currency="USD",
                     extra={"usd_vnd": usd_vnd, "xau_vnd_luong": round(xau_vnd_luong, 0)})
        results["xau"] = {"price_usd": xau, "usd_vnd": usd_vnd,
                          "vnd_luong": round(xau_vnd_luong, 0)}
        if verbose:
            print(f"  ✅ XAU  {today}  {xau:,.2f} USD/oz  ≈ {xau_vnd_luong/1_000_000:.2f}M VND/lượng")
    else:
        results["xau_error"] = "Không fetch được XAU/USD"
        if verbose:
            print(f"  ❌ XAU  {today}  Không lấy được giá")

    conn.commit()
    conn.close()
    return results


def run_status():
    conn = connect_db()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source, COUNT(*) AS cnt,
                   MIN(price_date) AS first_date,
                   MAX(price_date) AS last_date,
                   MAX(sell_price) AS latest_sell
            FROM gold_prices
            GROUP BY source ORDER BY source
        """)
        rows = cur.fetchall()
    conn.close()
    print(f"\n📊 Gold Price DB Status")
    print(f"{'Source':<12} {'Count':>6}  {'First':>12}  {'Last':>12}  {'Latest':>18}")
    print("-" * 65)
    for r in rows:
        src, cnt, first, last, sell = r
        val = f"{sell:,.0f}" if sell else "N/A"
        print(f"{src:<12} {cnt:>6}  {str(first):>12}  {str(last):>12}  {val:>18}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daily",  action="store_true", help="Fetch giá hôm nay và lưu DB")
    p.add_argument("--status", action="store_true", help="Xem tổng quan DB gold_prices")
    args = p.parse_args()

    if args.daily:
        print(f"🔄 Fetch gold prices ({date.today()})...")
        run_daily()
    elif args.status:
        run_status()
    else:
        p.print_help()
