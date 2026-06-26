import psycopg2
DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"
conn = psycopg2.connect(DB)
cur = conn.cursor()

cur.execute("SELECT source, COUNT(*), MIN(nav_date)::text, MAX(nav_date)::text FROM nav_history WHERE fund_code='TCBF' GROUP BY source")
print("TCBF remaining by source:")
for r in cur.fetchall(): print(" ", r)

cur.execute("DELETE FROM nav_history WHERE fund_code='TCBF' AND source='fmarket'")
print(f"Deleted fmarket rows: {cur.rowcount}")
conn.commit()

cur.execute("SELECT COUNT(*), MIN(nav_date)::text, MAX(nav_date)::text FROM nav_history WHERE fund_code='TCBF'")
print("TCBF final:", cur.fetchone())

# TCFF check
cur.execute("SELECT source, COUNT(*), MIN(nav_date)::text, MAX(nav_date)::text FROM nav_history WHERE fund_code='TCFF' GROUP BY source")
print("\nTCFF by source:")
for r in cur.fetchall(): print(" ", r)

conn.close()
