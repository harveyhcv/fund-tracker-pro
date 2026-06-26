import psycopg2
DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"
conn = psycopg2.connect(DB)
cur = conn.cursor()
cur.execute("DELETE FROM nav_history WHERE fund_code='TCFF' AND source='fmarket'")
print(f"Deleted TCFF fmarket rows: {cur.rowcount}")
conn.commit()
cur.execute("SELECT nav_date::text, nav FROM nav_history WHERE fund_code='TCFF' ORDER BY nav_date DESC LIMIT 3")
print("TCFF latest now:")
for r in cur.fetchall(): print(f"  {r[0]} NAV={float(r[1]):,.2f}")
conn.close()
