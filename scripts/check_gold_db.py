import psycopg2
DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"
conn = psycopg2.connect(DB)
cur = conn.cursor()

# Check table exists and count
cur.execute("SELECT COUNT(*), MIN(price_date)::text, MAX(price_date)::text FROM gold_prices")
row = cur.fetchone()
print(f"gold_prices: {row[0]} rows, range {row[1]} to {row[2]}")

if row[0] > 0:
    cur.execute("SELECT source, product, COUNT(*) FROM gold_prices GROUP BY source, product ORDER BY COUNT(*) DESC LIMIT 10")
    print("By source/product:")
    for r in cur.fetchall(): print(f"  {r[0]} / {r[1]}: {r[2]} rows")

conn.close()
