#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_gold.py — Lấy giá vàng và lưu vào PostgreSQL

Nguồn chính   : vang.today/api/prices (JSON, free, không cần auth) — cho TẤT CẢ
                sản phẩm (SJC miếng, SJC nhẫn, DOJI HN/HCM/Jewelry, PNJ, Bảo Tín,
                VN Gold, Viettin, XAU/USD quốc tế) trong 1 lần gọi.
Nguồn dự phòng: giavang.org (SJC) + giavang.doji.vn (scrape) + Yahoo Finance (XAU/USD)
                — chỉ dùng khi vang.today lỗi/thiếu sản phẩm.
Cross-check   : so sánh vang.today vs DOJI scrape, cảnh báo nếu lệch >1%

Sản phẩm lưu (source : product):
  VANGTODAYAPI : SJC_1L           Vàng miếng SJC 9999 1 lượng
  VANGTODAYAPI : DOJI_NHAN_9999   DOJI nhẫn 9999 (Hà Nội)
  VANGTODAYAPI : DOJI_NHAN_HCM    DOJI nhẫn 9999 (Hồ Chí Minh)
  VANGTODAYAPI : DOJI_JEWELRY     DOJI Jewelry
  VANGTODAYAPI : SJC_NHAN         Nhẫn SJC 9999
  VANGTODAYAPI : PNJ_HN           PNJ Hà Nội
  VANGTODAYAPI : PNJ_24K          PNJ 24K
  VANGTODAYAPI : BAOTINNGUYEN     Bảo Tín 9999
  VANGTODAYAPI : BAOTINSJC        Bảo Tín SJC
  VANGTODAYAPI : VNGOLD_SJC       VN Gold SJC
  VANGTODAYAPI : VIETTIN_SJC      Viettin SJC
  VANGTODAYAPI : XAUUSD           XAU/USD quốc tế
  DOJI_SCRAPE  : SJC_1L           Cross-check từ giavang.doji.vn
  DOJI_SCRAPE  : DOJI_NHAN_9999   Cross-check từ giavang.doji.vn

Chạy daily (cron trong job_morning của bot.py):
    python3 fetch_gold.py --daily
    python3 fetch_gold.py --status
    python3 fetch_gold.py --crosscheck
    python3 fetch_gold.py --backfill 14
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
from datetime import date
from pathlib import Path
from typing import Optional

# Console Windows mặc định dùng cp1252, không encode được tiếng Việt có dấu trong
# print() — reconfigure sang UTF-8 (no-op an toàn trên Linux/Railway, vốn đã UTF-8).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).parent.parent

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"

# Mapping vang.today type_code → product key của chúng ta
_VANGTODAY_MAP = {
    "SJL1L10":     ("SJC_1L",         "Vàng miếng SJC 9999 1 lượng"),
    "DOHNL":       ("DOJI_NHAN_9999", "DOJI Hà Nội"),
    "DOHCML":      ("DOJI_NHAN_HCM",  "DOJI Hồ Chí Minh"),
    "DOJINHTV":    ("DOJI_JEWELRY",   "DOJI Jewelry"),
    "SJ9999":      ("SJC_NHAN",       "Nhẫn SJC 9999"),
    "PQHNVM":      ("PNJ_HN",         "PNJ Hà Nội"),
    "PQHN24NTT":   ("PNJ_24K",        "PNJ 24K"),
    "BT9999NTT":   ("BAOTINNGUYEN",   "Bảo Tín 9999"),
    "BTSJC":       ("BAOTINSJC",      "Bảo Tín SJC"),
    "VNGSJC":      ("VNGOLD_SJC",     "VN Gold SJC"),
    "VIETTINMSJC": ("VIETTIN_SJC",    "Viettin SJC"),
    "XAUUSD":      ("XAUUSD",         "Vàng quốc tế XAU/USD"),
}


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


# ── Nguồn 1: vang.today API (chính — tất cả sản phẩm trong 1 lần gọi) ────────

_VANGTODAY_URL = "https://www.vang.today/api/prices"


def fetch_vangtoday() -> dict:
    """GET vang.today/api/prices — trả về toàn bộ sản phẩm.
    Result: {product_key: {"buy":..., "sell":..., "name":..., "currency":..., "change_buy":...}}"""
    try:
        data = json.loads(_req(_VANGTODAY_URL))
        if not data.get("success"):
            print("  vang.today: success=false", file=sys.stderr)
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
        print(f"  vang.today: {e}", file=sys.stderr)
        return {}


# ── Nguồn 2: giavang.org (fallback SJC nếu vang.today lỗi) ──────────────────

def fetch_giavang_org(today: date) -> Optional[dict]:
    """
    Scrape giavang.org main page — khối "GIÁ VÀNG SJC HÔM NAY" ở đầu trang chứa
    đúng 2 <span class="gold-price"> đầu tiên: Mua vào rồi Bán ra của SJC Miếng.
    Giá dạng "145.400" = 145,400 nghìn đồng/lượng = 145,400,000 VND/lượng.
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


# ── Nguồn 3: DOJI scrape (cross-check + fallback nhẫn) ───────────────────────

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


# ── Nguồn 4: XAU/USD Yahoo Finance + Vietcombank (fallback quốc tế) ──────────

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


# ── Cross-check ───────────────────────────────────────────────────────────────

def crosscheck(vt: dict, doji: dict, threshold_pct: float = 1.0) -> "list[str]":
    """So sánh vang.today vs DOJI scrape, trả về danh sách cảnh báo nếu lệch > threshold_pct%."""
    warnings = []
    for product in ("SJC_1L", "DOJI_NHAN_9999"):
        vt_d   = vt.get(product)
        doji_d = doji.get(product)
        if not vt_d or not doji_d:
            continue
        for side in ("buy", "sell"):
            v1, v2 = vt_d[side], doji_d[side]
            if v1 and v2:
                diff_pct = abs(v1 - v2) / v2 * 100
                if diff_pct > threshold_pct:
                    warnings.append(
                        f"  LỆCH {diff_pct:.1f}% [{product}.{side}] "
                        f"vang.today={v1/1e6:.3f}M vs DOJI={v2/1e6:.3f}M"
                    )
    return warnings


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_daily(verbose: bool = True) -> dict:
    today  = date.today()
    conn   = connect_db()
    ensure_schema(conn)
    saved  = {}

    try:
        # 1. vang.today — nguồn chính (tất cả sản phẩm trong 1 lần gọi)
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
                    print(f"  {product:<20} {buy:,.2f} USD/oz  (vang.today)")
                else:
                    print(f"  {product:<20} Mua:{buy/1e6:.3f}M  Ban:{sell/1e6:.3f}M  (vang.today)")
        if not vt and verbose:
            print("  vang.today - khong lay duoc, dung fallback")
        # Commit ngay sau nguồn chính — dữ liệu quan trọng nhất không bị mất nếu
        # các bước fallback/cross-check phía dưới gặp lỗi.
        conn.commit()

        # 2. DOJI scrape — cross-check + fallback SJC/nhẫn nếu vang.today lỗi/thiếu
        doji = fetch_doji_scrape()
        for product, d in doji.items():
            upsert(conn, today, "DOJI_SCRAPE", product, d["buy"], d["sell"],
                   extra={"name": d["name"]})
        if verbose and doji:
            print(f"  DOJI cross-check ({len(doji)} san pham) luu vao DOJI_SCRAPE")

        if "SJC_1L" not in vt:
            # giavang.org trước, DOJI scrape sau
            gvo = fetch_giavang_org(today)
            if gvo:
                upsert(conn, today, "VANGTODAYAPI", "SJC_1L", gvo["buy"], gvo["sell"],
                       extra={"source": "giavang.org", "source_url": gvo["source_url"], "fallback": True})
                saved["SJC_1L"] = gvo
                if verbose:
                    print(f"  SJC_1L (fallback giavang.org) Mua:{gvo['buy']/1e6:.3f}M Ban:{gvo['sell']/1e6:.3f}M")
            elif "SJC_1L" in doji:
                d = doji["SJC_1L"]
                upsert(conn, today, "VANGTODAYAPI", "SJC_1L", d["buy"], d["sell"],
                       extra={"name": d["name"], "fallback": "doji_scrape"})
                saved["SJC_1L"] = d
                if verbose:
                    print(f"  SJC_1L (fallback DOJI scrape) Mua:{d['buy']/1e6:.3f}M Ban:{d['sell']/1e6:.3f}M")

        # 3. XAU/USD — vang.today trước, Yahoo Finance làm backup
        if "XAUUSD" not in vt:
            xau = fetch_xauusd_yahoo()
            if xau:
                usd_vnd = fetch_usd_vnd() or 25_400.0
                xau_vnd = round(xau * usd_vnd * (37.5 / 31.1035))
                upsert(conn, today, "VANGTODAYAPI", "XAUUSD", xau, xau, currency="USD",
                       extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd, "fallback": "yahoo"})
                saved["XAUUSD"] = {"buy": xau, "sell": xau, "usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd}
                if verbose:
                    print(f"  XAUUSD (fallback Yahoo) {xau:,.2f} USD/oz ~ {xau_vnd/1e6:.2f}M VND/luong")
        else:
            # Tính thêm quy đổi VND/lượng để hiển thị (vang.today chỉ cho USD/oz)
            xau_entry = vt["XAUUSD"]
            usd_vnd   = fetch_usd_vnd() or 25_400.0
            xau_vnd   = round(xau_entry["buy"] * usd_vnd * (37.5 / 31.1035))
            upsert(conn, today, "VANGTODAYAPI", "XAUUSD",
                   xau_entry["buy"], xau_entry["buy"], currency="USD",
                   extra={"usd_vnd": usd_vnd, "xau_vnd_luong": xau_vnd,
                          "change": xau_entry.get("change_buy", 0)})

        # 4. Cross-check cảnh báo
        warnings = crosscheck(vt, doji)
        if warnings and verbose:
            print("\n  --- CROSS-CHECK WARNINGS ---")
            for w in warnings:
                print(w)

        conn.commit()
    finally:
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
            print(f"  {pt['date']}  Mua:{pt['buy']/1e6:.3f}M  Bán:{pt['sell']/1e6:.3f}M")
    conn.commit()
    conn.close()
    return filled


def run_status():
    conn = connect_db()
    ensure_schema(conn)
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


def run_crosscheck():
    print(f"Cross-check vang.today vs DOJI scrape ({date.today()})")
    print("=" * 55)
    vt   = fetch_vangtoday()
    doji = fetch_doji_scrape()
    for product in ("SJC_1L", "DOJI_NHAN_9999"):
        vt_d   = vt.get(product)
        doji_d = doji.get(product)
        print(f"\n[{product}]")
        if vt_d:
            print(f"  vang.today : Mua={vt_d['buy']/1e6:.3f}M  Ban={vt_d['sell']/1e6:.3f}M")
        else:
            print("  vang.today : N/A")
        if doji_d:
            print(f"  DOJI scrape: Mua={doji_d['buy']/1e6:.3f}M  Ban={doji_d['sell']/1e6:.3f}M")
        else:
            print("  DOJI scrape: N/A")
        if vt_d and doji_d:
            for side in ("buy", "sell"):
                diff_pct = abs(vt_d[side] - doji_d[side]) / doji_d[side] * 100
                flag = " LECH" if diff_pct > 1.0 else " OK"
                print(f"  {side}: diff={diff_pct:.2f}%{flag}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daily",      action="store_true")
    p.add_argument("--status",     action="store_true")
    p.add_argument("--crosscheck", action="store_true")
    p.add_argument("--backfill", type=int, metavar="DAYS", help="Điền N ngày gần nhất còn thiếu")
    args = p.parse_args()
    if args.daily:
        print(f"Fetch gold ({date.today()})...")
        run_daily()
        print("Done")
    elif args.status:
        run_status()
    elif args.crosscheck:
        run_crosscheck()
    elif args.backfill:
        print(f"Backfill {args.backfill} ngày gần nhất từ giavang.org...")
        n = run_backfill(days=args.backfill)
        print(f"Done — {n} ngày đã điền")
    else:
        p.print_help()
