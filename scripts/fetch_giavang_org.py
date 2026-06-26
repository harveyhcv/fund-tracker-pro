"""
Scrape SJC gold price history from giavang.org using Playwright.
Data available from 2009-07-22 to present.
Price format: "74.000" = 74,000 nghìn đồng/lượng = 74,000,000 VND/lượng

Strategy: scrape one date per month (the 15th) to get ~200 data points.
For denser data (daily), pass --daily flag but it takes ~60+ minutes.
"""
import sys, re, time, json, argparse
from datetime import date, timedelta
import psycopg2

sys.stdout.reconfigure(encoding='utf-8')

DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"
BASE_URL = "https://giavang.org/trong-nuoc/sjc/lich-su/{date}.html"

def parse_price(text):
    """Parse '74.000' or '74,000' to int VND/luong (×1000)."""
    text = text.strip().replace(',', '').replace('.', '')
    try:
        val = int(text)
        return val * 1000  # nghìn đồng → đồng
    except:
        return None

def scrape_date(page, d: date):
    url = BASE_URL.format(date=d.strftime("%Y-%m-%d"))
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)  # wait for JS to render

        rows = page.query_selector_all("table tr")
        best_buy = None
        best_sell = None

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 3:
                continue
            texts = [c.inner_text().strip() for c in cells]
            # Row format A (4 cols): Loại vàng | Mua vào | Bán ra | Thời gian
            # Row format B (5 cols): Khu vực | Loại vàng | Mua vào | Bán ra | Thời gian
            if len(cells) >= 5 and "SJC" in texts[1]:
                buy = parse_price(texts[2])
                sell = parse_price(texts[3])
            elif len(cells) >= 4 and "SJC" in texts[0]:
                buy = parse_price(texts[1])
                sell = parse_price(texts[2])
            else:
                continue
            if buy and sell and buy > 10_000_000:  # sanity: >10tr VND
                if best_buy is None or sell > best_sell:
                    best_buy = buy
                    best_sell = sell

        return best_buy, best_sell
    except Exception as e:
        return None, None

def date_range_monthly(start: date, end: date):
    """Yield one date per month (the 15th)."""
    d = date(start.year, start.month, 15)
    if d < start:
        # Move to next month
        if d.month == 12:
            d = date(d.year + 1, 1, 15)
        else:
            d = date(d.year, d.month + 1, 15)
    while d <= end:
        yield d
        # Next month
        if d.month == 12:
            d = date(d.year + 1, 1, 15)
        else:
            d = date(d.year, d.month + 1, 15)

def date_range_daily(start: date, end: date):
    """Yield every day (weekdays only)."""
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            yield d
        d += timedelta(days=1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2009-07-22', help='Start date YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='End date YYYY-MM-DD (default: today)')
    parser.add_argument('--daily', action='store_true', help='Scrape every weekday (slow)')
    parser.add_argument('--dry-run', action='store_true', help='Print results without saving to DB')
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    if args.daily:
        dates = list(date_range_daily(start, end))
    else:
        dates = list(date_range_monthly(start, end))

    print(f"Scraping {len(dates)} dates from {start} to {end} ({'daily' if args.daily else 'monthly'})")

    from playwright.sync_api import sync_playwright

    results = []  # list of (date_str, buy, sell)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for i, d in enumerate(dates):
            buy, sell = scrape_date(page, d)
            ds = d.strftime("%Y-%m-%d")
            if buy and sell:
                results.append((ds, buy, sell))
                print(f"  [{i+1}/{len(dates)}] {ds}: mua={buy//1_000_000}tr, bán={sell//1_000_000}tr")
            else:
                print(f"  [{i+1}/{len(dates)}] {ds}: NO DATA")

            # Rate limit: 1 req/sec
            time.sleep(1.0)

        browser.close()

    print(f"\nScraped {len(results)} data points with prices")

    if args.dry_run:
        print("Dry run — not saving to DB")
        return

    if not results:
        print("No data to insert")
        return

    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    inserted = 0
    for ds, buy, sell in results:
        cur.execute(
            "INSERT INTO gold_prices (source, product, price_date, buy_price, sell_price, extra)"
            " VALUES (%s,%s,%s,%s,%s,%s::jsonb)"
            " ON CONFLICT (source,product,price_date) DO UPDATE"
            " SET buy_price=EXCLUDED.buy_price, sell_price=EXCLUDED.sell_price",
            ("GIAVANG_ORG", "SJC_1L", ds, buy, sell,
             json.dumps({"source_url": f"giavang.org/lich-su/{ds}"}))
        )
        inserted += cur.rowcount

    conn.commit()
    conn.close()
    print(f"Upserted {inserted} rows to DB (source=GIAVANG_ORG, product=SJC_1L)")

    # Summary
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(price_date)::text, MAX(price_date)::text FROM gold_prices WHERE source='GIAVANG_ORG'")
    r = cur.fetchone()
    print(f"GIAVANG_ORG total: {r[0]} rows ({r[1]} to {r[2]})")
    conn.close()

if __name__ == "__main__":
    main()
