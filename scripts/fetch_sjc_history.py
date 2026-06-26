"""
Fetch 1 year SJC gold price history from webgia.com and seed into Railway DB.
Series: Mua vao (buy), Ban ra (sell) in trieu VND/luong.
Converts to VND (multiply by 1,000,000) before storing.
Also fetches XAU/USD and USD/VND from Yahoo Finance (2 years).
"""
import re, json, urllib.request, psycopg2
from datetime import datetime, timezone

DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"

def fetch_webgia_sjc():
    url = "https://webgia.com/gia-vang/sjc/bieu-do-1-nam.html"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")
    # Extract series: name:"Ban ra",data:[[ts,val],...] and name:"Mua vao",...
    pattern = r'name:"([^"]+)",data:\[(\[[\d.,\[\] ]+\])\]'
    matches = re.findall(pattern, html)
    result = {}
    for name, data_str in matches:
        try:
            pts = json.loads(f"[{data_str}]")
            result[name] = [(int(p[0]), float(p[1])) for p in pts if len(p) == 2]
        except Exception as e:
            print(f"  Parse error {name}: {e}")
    return result

def fetch_yahoo(symbol, range_="2y"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    result = d["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    return [
        (datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"), c)
        for ts, c in zip(timestamps, closes) if c is not None
    ]

def ts_to_date(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

print("=== Fetching SJC from webgia.com ===")
sjc_data = fetch_webgia_sjc()
for name, pts in sjc_data.items():
    if pts:
        d0 = ts_to_date(pts[0][0]); d1 = ts_to_date(pts[-1][0])
        print(f"  {name}: {len(pts)} points, {d0} to {d1}, range {pts[0][1]}-{pts[-1][1]} trieu")

print("\n=== Fetching XAU/USD + USD/VND from Yahoo Finance ===")
import time
xau_usd = fetch_yahoo("GC%3DF", "2y"); print(f"  XAU/USD: {len(xau_usd)} pts, {xau_usd[0][0]} to {xau_usd[-1][0]}")
time.sleep(0.5)
usd_vnd = fetch_yahoo("VND%3DX", "2y"); print(f"  USD/VND: {len(usd_vnd)} pts, {usd_vnd[0][0]} to {usd_vnd[-1][0]}")

# Build VND/VND map
vnd_map = {d: v for d, v in usd_vnd}
xau_map = {d: v for d, v in xau_usd}

# 1 oz = 31.1035g, 1 luong = 37.5g → oz/luong = 37.5/31.1035
OZ_PER_LUONG = 37.5 / 31.1035

# Insert to DB
conn = psycopg2.connect(DB)
cur = conn.cursor()
inserted = 0

# SJC buy/sell from webgia
buy_pts = sjc_data.get("Mua vào", sjc_data.get("Mua vao", []))
sell_pts = sjc_data.get("Bán ra", sjc_data.get("Ban ra", []))
buy_map = {ts_to_date(ts): val * 1_000_000 for ts, val in buy_pts}
sell_map = {ts_to_date(ts): val * 1_000_000 for ts, val in sell_pts}
all_sjc_dates = sorted(set(buy_map) | set(sell_map))
for dt in all_sjc_dates:
    buy = buy_map.get(dt, sell_map.get(dt))
    sell = sell_map.get(dt, buy_map.get(dt))
    cur.execute(
        "INSERT INTO gold_prices (source, product, price_date, buy_price, sell_price, extra)"
        " VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (source,product,price_date) DO UPDATE"
        " SET buy_price=EXCLUDED.buy_price, sell_price=EXCLUDED.sell_price",
        ("SJC", "SJC_1L", dt, buy, sell, json.dumps({"source_url": "webgia.com"}))
    )
    inserted += cur.rowcount

# XAU/USD and XAU/VND from Yahoo
last_vnd = 25000
for dt, xau in xau_map.items():
    if dt in vnd_map: last_vnd = vnd_map[dt]
    xau_vnd = xau * last_vnd * OZ_PER_LUONG
    cur.execute(
        "INSERT INTO gold_prices (source,product,price_date,buy_price,sell_price,extra)"
        " VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (source,product,price_date) DO UPDATE"
        " SET buy_price=EXCLUDED.buy_price, sell_price=EXCLUDED.sell_price",
        ("INTERNATIONAL","XAU_USD",dt,xau,xau,json.dumps({"usd_vnd":round(last_vnd,2)}))
    )
    inserted += cur.rowcount
    cur.execute(
        "INSERT INTO gold_prices (source,product,price_date,buy_price,sell_price,extra)"
        " VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (source,product,price_date) DO UPDATE"
        " SET buy_price=EXCLUDED.buy_price, sell_price=EXCLUDED.sell_price",
        ("INTERNATIONAL","XAU_VND_LUONG",dt,round(xau_vnd),round(xau_vnd),json.dumps({"xau_usd":round(xau,2),"usd_vnd":round(last_vnd,2)}))
    )
    inserted += cur.rowcount

conn.commit(); conn.close()
print(f"\nUpserted {inserted} rows total")

# Verify
conn = psycopg2.connect(DB)
cur = conn.cursor()
cur.execute("SELECT source,product,COUNT(*),MIN(price_date)::text,MAX(price_date)::text FROM gold_prices GROUP BY source,product ORDER BY source,product")
print("\nDB summary:")
for r in cur.fetchall(): print(f"  {r[0]}/{r[1]}: {r[2]} rows ({r[3]} to {r[4]})")
conn.close()
