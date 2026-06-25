#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — Lấy giá vàng và lưu vào PostgreSQL

Nguồn chính   : vang.today/api/prices  (JSON, free, không cần auth)
Nguồn dự phòng: giavang.doji.vn scrape + Yahoo Finance (XAU/USD)
Cross-check   : so sánh vang.today vs DOJI scrape, cảnh báo nếu lệch >1%

Sản phẩm lưu (source : product):
  VANGTODAYAPI : SJC_1L           Vàng miếng SJC 1L
  VANGTODAYAPI : DOJI_NHAN_9999   DOJI nhẫn 9999 (Hà Nội)
  VANGTODAYAPI : XAUUSD           XAU/USD quốc tế
  DOJI_SCRAPE  : SJC_1L           Cross-check từ giavang.doji.vn
  DOJI_SCRAPE  : DOJI_NHAN_9999   Cross-check từ giavang.doji.vn

Chạy daily (cron 18:30):
    python3 scripts/fetch_gold.py --daily
    python3 scripts/fetch_gold.py --status
    python3 scripts/fetch_gold.py --crosscheck
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

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"

# Mapping vang.today type_code → product key của chúng ta
_VANGTODAY_MAP = {
    # SJC miếng vàng (chính thống Nhà nước)
    "SJL1L10":     ("SJC_1L",         "Vàng miếng SJC 9999 — 1 lượng"),
    # Nhẫn DOJI 9999 (2 chi nhánh, cùng sản phẩm — lưu chung key)
    "DOHNL":       ("DOJI_NHAN_9999", "Nhẫn tròn DOJI 9999 (Hà Nội)"),
    "DOHCML":      ("DOJI_NHAN_HCM",  "Nhẫn tròn DOJI 9999 (HCM)"),
    "DOJINHTV":    ("DOJI_JEWELRY",   "DOJI Trang sức (không đầu tư)"),
    # Nhẫn SJC 9999 (khác với miếng SJC)
    "SJ9999":      ("SJC_NHAN",       "Nhẫn tròn SJC 9999"),
    # PNJ — 2 dòng sản phẩm khác nhau
    "PQHNVM":      ("PNJ_VANGMY",     "Nhẫn vàng mỹ PNJ (Hà Nội)"),
    "PQHN24NTT":   ("PNJ_24K",        "Nhẫn 24K PNJ 9999"),
    # Bảo Tín Minh Châu
    "BT9999NTT":   ("BAOTINNGUYEN",   "Vàng nhẫn Bảo Tín 9999"),
    "BTSJC":       ("BAOTINSJC",      "Vàng SJC tại Bảo Tín"),
    # Đơn vị bán SJC khác
    "VNGSJC":      ("VNGOLD_SJC",     "Vàng SJC tại VN Gold"),
    "VIETTINMSJC": ("VIETTIN_SJC",    "Vàng SJC tại Việt Tín"),
    # Quốc tế
    "XAUUSD":      ("XAUUSD",         "Vàng quốc tế XAU/USD"),
}


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
            cur.execute("ALTER TABLE gold_prices ADD COLUMN IF NOT EXISTS product TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass
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
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ── Nguồn 1: vang.today API ──────────────────────────────────────────────────

_VANGTODAY_URL = "https://www.vang.today/api/prices"

def fetch_vangtoday() -> dict:
    """
    GET vang.today/api/prices — trả về toàn bộ sản phẩm.
    Result: {product_key: {"buy":..., "sell":..., "name":..., "currency":..., "change_buy":...}}
    """
    try:
        data = json.loads(_req(_VANGTODAY_URL))
        if not data.get("success"):
            print("  ⚠ vang.today: success=false", file=sys.stderr)
            return {}
        prices = data.get("prices", {})
        result = {}
        for code, info in prices.items():
            if code not in _VANGTODAY_MAP:
                continue
            product_key, label = _VANGTODAY_MAP[code]
            result[product_key] = {
                "buy":        info["buy"],
                "sell":       info.get("sell") or info["buy"],
                "name":       label,
                "currency":   info.get("currency", "VND"),
                "change_buy": info.get("change_buy", 0),
                "type_code":  code,
            }
        return result
    except Exception as e:
        print(f"  ⚠ vang.today: {e}", file=sys.stderr)
        return {}


# ── Nguồn 2: DOJI scrape (cross-check) ───────────────────────────────────────

_DOJI_GOLD_URL = "https://giavang.doji.vn/"

def fetch_doji_scrape() -> dict:
    """
    Scrape giavang.doji.vn — đơn vị nghìn/chỉ → VND/lượng (*10,000).
    Dùng để cross-check với vang.today.
    """
    results = {}
    try:
        html = _req(_DOJI_GOLD_URL).decode("utf-8", errors="replace")
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
                results["SJC_1L"] = {"buy": buy, "sell": sell, "name": "SJC bán lẻ (DOJI scrape)"}
            elif ("nhẫn" in nl or "nhan" in nl) and "9999" in nl and "DOJI_NHAN_9999" not in results:
                results["DOJI_NHAN_9999"] = {"buy": buy, "sell": sell, "name": name[:50]}
    except Exception as e:
        print(f"  ⚠ DOJI scrape: {e}", file=sys.stderr)
    return results


# ── Nguồn 3: XAU/USD Yahoo Finance (backup nếu vang.today thiếu) ─────────────

def fetch_xauusd_yahoo() -> Optional[float]:
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
            print(f"  ⚠ XAU/USD Yahoo ({symbol}): {e}", file=sys.stderr)
    return None


def fetch_usd_vnd() -> Optional[float]:
    try:
        url = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
        raw  = _req(url).decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        for item in root.iter("Exrate"):
            if item.get("CurrencyCode") == "USD":
                sell = item.get("Sell", "").replace(",", "")
                return float(sell) if sell else None
    except Exception:
        pass
    return None


# ── Cross-check ───────────────────────────────────────────────────────────────

def crosscheck(vt: dict, doji: dict, threshold_pct: float = 1.0) -> list[str]:
    """So sánh vang.today vs DOJI scrape, trả về danh sách cảnh báo nếu lệch > threshold_pct%."""
    warnings = []
    for product in ("SJC_1L", "DOJI_NHAN_9999"):
        vt_d   = vt.get(product)
        doji_d = doji.get(product)
        if not vt_d or not doji_d:
            continue
        for side in ("buy", "sell"):
            v1, v2 = vt_d[side], doji_d[side]
            if v1 and v2 and v2:
                diff_pct = abs(v1 - v2) / v2 * 100
                if diff_pct > threshold_pct:
                    warnings.append(
                        f"  ⚠ LỆCH {diff_pct:.1f}% [{product}.{side}] "
                        f"vang.today={v1/1e6:.3f}M vs DOJI={v2/1e6:.3f}M"
                    )
    return warnings


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_daily(verbose: bool = True) -> dict:
    today  = date.today()
    conn   = connect_db()
    ensure_schema(conn)
    saved  = {}

    # 1. vang.today — nguồn chính (tất cả sản phẩm)
    vt = fetch_vangtoday()
    for product, d in vt.items():
        curr = d.get("currency", "VND")
        buy, sell = d["buy"], d["sell"]
        upsert(conn, today, "VANGTODAYAPI", product, buy, sell, currency=curr,
               extra={"name": d["name"], "type_code": d.get("type_code"),
                      "change_buy": d.get("change_buy", 0)})
        saved[product] = d
        if verbose:
            if curr == "USD":
                print(f"  ✅ {product:<20} {buy:,.2f} USD/oz  (vang.today)")
            else:
                print(f"  ✅ {product:<20} Mua:{buy/1e6:.3f}M  Bán:{sell/1e6:.3f}M  (vang.today)")

    if not vt and verbose:
        print("  ❌ vang.today — không lấy được, dùng fallback")

    # 2. DOJI scrape — cross-check + fallback nếu vang.today lỗi
    doji = fetch_doji_scrape()
    for product, d in doji.items():
        upsert(conn, today, "DOJI_SCRAPE", product, d["buy"], d["sell"],
               extra={"name": d["name"]})
    if verbose and doji:
        print(f"  ✅ DOJI cross-check ({len(doji)} sản phẩm) lưu vào DOJI_SCRAPE")

    # Nếu vang.today không có SJC_1L → dùng DOJI scrape
    if "SJC_1L" not in vt and "SJC_1L" in doji:
        d = doji["SJC_1L"]
        upsert(conn, today, "VANGTODAYAPI", "SJC_1L", d["buy"], d["sell"],
               extra={"name": d["name"], "fallback": "doji_scrape"})
        saved["SJC_1L"] = d
        if verbose:
            print(f"  ✅ SJC_1L (fallback DOJI scrape) Mua:{d['buy']/1e6:.3f}M Bán:{d['sell']/1e6:.3f}M")

    # 3. XAU/USD — dùng vang.today nếu có, Yahoo Finance làm backup
    if "XAUUSD" not in vt:
        xau = fetch_xauusd_yahoo()
        if xau:
            usd_vnd = fetch_usd_vnd() or 25_400.0
            xau_vnd = round(xau * usd_vnd * (37.5 / 31.1035))
            upsert(conn, today, "VANGTODAYAPI", "XAUUSD", xau, xau, currency="USD",
                   extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd})
            if verbose:
                print(f"  ✅ XAUUSD (Yahoo) {xau:,.2f} USD/oz ≈ {xau_vnd/1e6:.2f}M VND/lượng")
    else:
        # Tính thêm quy đổi VND/lượng nếu vang.today chỉ cho USD/oz
        xau_entry = vt["XAUUSD"]
        usd_vnd   = fetch_usd_vnd() or 25_400.0
        xau_vnd   = round(xau_entry["buy"] * usd_vnd * (37.5 / 31.1035))
        upsert(conn, today, "VANGTODAYAPI", "XAUUSD",
               xau_entry["buy"], xau_entry["buy"], currency="USD",
               extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd,
                      "change": xau_entry.get("change_buy", 0)})
        if verbose:
            print(f"  ✅ XAUUSD {xau_entry['buy']:,.2f} USD/oz ≈ {xau_vnd/1e6:.2f}M VND/lượng")

    # 4. Cross-check cảnh báo
    warnings = crosscheck(vt, doji)
    if warnings:
        print("\n  --- CROSS-CHECK WARNINGS ---")
        for w in warnings:
            print(w)
    elif verbose and doji:
        # Hiển thị diff để tham khảo
        for product in ("SJC_1L", "DOJI_NHAN_9999"):
            vt_d = vt.get(product); doji_d = doji.get(product)
            if vt_d and doji_d:
                diff = abs(vt_d["sell"] - doji_d["sell"]) / 1e6
                print(f"  ✓ cross-check {product}: diff={diff:.3f}M VND/lượng OK")

    conn.commit()
    conn.close()
    return saved


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
    print(f"\nGold DB Status — {len(rows)} san pham")
    print(f"{'Source':<16} {'Product':<22} {'#':>5}  {'First':>12}  {'Last':>12}  {'Sell':>18}")
    print("-" * 90)
    for r in rows:
        src, prod, cnt, first, last, sell = r
        print(f"{src:<16} {prod:<22} {cnt:>5}  {str(first):>12}  {str(last):>12}  "
              f"{sell:>18,.0f}")


def run_crosscheck():
    """Chạy cross-check tức thì và in kết quả chi tiết."""
    print(f"Cross-check vang.today vs DOJI scrape ({date.today()})")
    print("=" * 55)
    vt   = fetch_vangtoday()
    doji = fetch_doji_scrape()

    for product in ("SJC_1L", "DOJI_NHAN_9999"):
        vt_d   = vt.get(product)
        doji_d = doji.get(product)
        print(f"\n[{product}]")
        if vt_d:
            print(f"  vang.today : Mua={vt_d['buy']/1e6:.3f}M  Bán={vt_d['sell']/1e6:.3f}M")
        else:
            print("  vang.today : N/A")
        if doji_d:
            print(f"  DOJI scrape: Mua={doji_d['buy']/1e6:.3f}M  Bán={doji_d['sell']/1e6:.3f}M")
        else:
            print("  DOJI scrape: N/A")
        if vt_d and doji_d:
            for side in ("buy", "sell"):
                diff_pct = abs(vt_d[side] - doji_d[side]) / doji_d[side] * 100
                flag = " ⚠ LỆCH" if diff_pct > 1.0 else " ✓"
                print(f"  {side}: diff={diff_pct:.2f}%{flag}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daily",      action="store_true", help="Fetch và lưu giá hôm nay")
    p.add_argument("--status",     action="store_true", help="Xem DB summary")
    p.add_argument("--crosscheck", action="store_true", help="So sánh vang.today vs DOJI")
    args = p.parse_args()
    if args.daily:
        print(f"Fetch gold prices ({date.today()})...")
        run_daily()
        print("Done")
    elif args.status:
        run_status()
    elif args.crosscheck:
        run_crosscheck()
    else:
        p.print_help()
