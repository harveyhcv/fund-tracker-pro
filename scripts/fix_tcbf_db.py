"""Xoá chỉ những rows TCBF sai (từ fmarket id=22, sau Jun 21)."""
import psycopg2
DB = "postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway"
conn = psycopg2.connect(DB)
cur = conn.cursor()

# Xem data gần đây
cur.execute("SELECT nav_date, nav, source FROM nav_history WHERE fund_code='TCBF' ORDER BY nav_date DESC LIMIT 10")
print("TCBF 10 rows gần nhất:")
for r in cur.fetchall():
    print(f"  {r[0]} NAV={float(r[1]):,.2f} source={r[2]}")

# Xoá rows SAI: Jun 22-25 với NAV ~19,800 (fmarket id=22, không phải TCBF thật)
# NAV TCBF thật từ TCInvest: >20,000. Rows <20,000 là sai.
cur.execute("SELECT COUNT(*) FROM nav_history WHERE fund_code='TCBF' AND nav < 20000")
bad_count = cur.fetchone()[0]
print(f"\nRows TCBF với NAV < 20000 (sai): {bad_count}")

cur.execute("DELETE FROM nav_history WHERE fund_code='TCBF' AND nav < 20000")
deleted = cur.rowcount
conn.commit()
print(f"Đã xoá {deleted} rows sai.")

# Verify
cur.execute("SELECT nav_date, nav FROM nav_history WHERE fund_code='TCBF' ORDER BY nav_date DESC LIMIT 5")
print("\nTCBF sau khi xoá:")
for r in cur.fetchall():
    print(f"  {r[0]} NAV={float(r[1]):,.2f}")

conn.close()
print("\nDone. Cần fetch lại TCBF từ TCInvest với token mới để có Jun 22-26.")
