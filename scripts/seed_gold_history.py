"""
Seed 2 years of gold price history from Yahoo Finance into Railway DB.
Sources:
  - GC=F (Gold Futures USD/troy oz) → convert to VND/luong
  - VND=X (USD/VND rate)
  - SJC estimate = XAU_USD * USDVND / 0.8294 * (1 + premium)
    where 1 troy oz = 31.1035g, 1 luong = 37.5g → 1 oz = 0.8294 luong
"""
import psycopg2, urllib.request, json, time

DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"

def fetch_yahoo(symbol, range_="2y", interval="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def get_series(symbol):
    """Returns list of (date_str, price) tuples."""
    try:
        d = fetch_yahoo(symbol)
        result = d["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        out = []
        for ts, c in zip(timestamps, closes):
            if c is None: continue
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            out.append((dt, c))
        print(f"  {symbol}: {len(out)} points, {out[0][0]} to {out[-1][0]}")
        return out
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return []

print("Fetching XAU/USD (GC=F)...")
xau_series = get_series("GC%3DF")  # URL-encoded GC=F
time.sleep(1)

print("Fetching USD/VND (VND%3DX)...")
usd_vnd_series = get_series("VND%3DX")  # VND=X

# Build date → price maps
xau_map = {d: p for d, p in xau_series}
vnd_map = {d: p for d, p in usd_vnd_series}

# Merge by date
all_dates = sorted(set(xau_map) | set(vnd_map))
print(f"\nTotal unique dates: {len(all_dates)}")

# Interpolate VND gaps (forward fill)
last_vnd = 24000  # fallback
vnd_filled = {}
for dt in sorted(all_dates):
    if dt in vnd_map:
        last_vnd = vnd_map[dt]
    vnd_filled[dt] = last_vnd

# 1 troy oz = 31.1035g, 1 luong = 37.5g → oz_per_luong = 37.5/31.1035 = 1.2057
# price_per_luong_vnd = xau_usd * usdvnd * oz_per_luong
OZ_PER_LUONG = 37.5 / 31.1035  # = 1.2057

# Historical SJC premium over international varies:
# ~10-15% historically, spiked to 40%+ in 2023-2024 during VN gold crackdown
# We'll use a conservative 12% as a baseline
# NOTE: This is an ESTIMATE. Actual SJC price from vangtoday starts 2026-06-24
SJC_PREMIUM = 0.12

rows_to_insert = []
for dt in all_dates:
    if dt not in xau_map:
        continue
    xau_usd = xau_map[dt]
    usd_vnd = vnd_filled[dt]
    # International price in VND/luong
    intl_vnd = xau_usd * usd_vnd * OZ_PER_LUONG
    # SJC estimate
    sjc_est = intl_vnd * (1 + SJC_PREMIUM)

    # INTERNATIONAL row: actual XAU/USD
    rows_to_insert.append(("INTERNATIONAL", "XAU_USD", dt, xau_usd, xau_usd, {"usd_vnd": round(usd_vnd, 2)}))
    # INTERNATIONAL row: price in VND/luong
    rows_to_insert.append(("INTERNATIONAL", "XAU_VND_LUONG", dt, round(intl_vnd), round(intl_vnd), {"xau_usd": round(xau_usd, 2), "usd_vnd": round(usd_vnd, 2)}))
    # SJC estimate
    rows_to_insert.append(("SJC_ESTIMATE", "SJC_1L", dt, round(sjc_est), round(sjc_est * 1.01), {"xau_usd": round(xau_usd, 2), "usd_vnd": round(usd_vnd, 2), "premium_pct": SJC_PREMIUM * 100}))

print(f"Rows to insert: {len(rows_to_insert)}")

# Insert to DB
conn = psycopg2.connect(DB)
cur = conn.cursor()
inserted = 0
skipped = 0
for row in rows_to_insert:
    source, product, date, buy, sell, extra = row
    cur.execute(
        """INSERT INTO gold_prices (source, product, price_date, buy_price, sell_price, extra)
           VALUES (%s, %s, %s, %s, %s, %s::jsonb)
           ON CONFLICT (source, product, price_date) DO NOTHING""",
        (source, product, date, buy, sell, json.dumps(extra))
    )
    if cur.rowcount:
        inserted += 1
    else:
        skipped += 1

conn.commit()
conn.close()
print(f"\nInserted: {inserted}, Skipped (already exist): {skipped}")

# Verify
conn = psycopg2.connect(DB)
cur = conn.cursor()
cur.execute("SELECT source, product, COUNT(*), MIN(price_date)::text, MAX(price_date)::text FROM gold_prices GROUP BY source, product ORDER BY source, product")
print("\ngold_prices table summary:")
for r in cur.fetchall():
    print(f"  {r[0]}/{r[1]}: {r[2]} rows ({r[3]} to {r[4]})")
conn.close()
