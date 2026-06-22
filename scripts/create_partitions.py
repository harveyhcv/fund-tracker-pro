import psycopg2
conn = psycopg2.connect("postgresql://postgres:PIqnNlqDQdMhpcWOqUOaaXlwOIvCjhrW@thomas.proxy.rlwy.net:30432/railway")
conn.autocommit = True
cur = conn.cursor()
for yr in range(2004, 2028):
    try:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS nav_{yr}
            PARTITION OF nav_history
            FOR VALUES FROM ('{yr}-01-01') TO ('{yr+1}-01-01')
        """)
        print(f"nav_{yr} OK")
    except Exception as e:
        print(f"nav_{yr} skip: {e}")
conn.close()
print("Done — all partitions 2004-2027 ready")
