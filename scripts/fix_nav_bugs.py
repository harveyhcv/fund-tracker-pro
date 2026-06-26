"""
Fix 3 root causes khiến TCBF/TCFF NAV sai:
1. _insert_pg: date→nav_date, remove status column, fix ON CONFLICT
2. _api_admin_fetch_nav: add save_nav_to_db inline (bot.py không có hàm này)
3. bot.py config: TCBF fmarket_id=22 sai → đặt None (TCBF chỉ có trên TCInvest)
"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
SRV = os.path.join(ROOT, 'telegram-bot', 'miniapp_server.py')
BOT = os.path.join(ROOT, 'telegram-bot', 'bot.py')

# ════════════════════════════════════════════════════════════════
# FIX 1: _insert_pg — sửa tên cột và ON CONFLICT
# ════════════════════════════════════════════════════════════════
srv = open(SRV, encoding='utf-8').read()

OLD_INSERT = (
    "        def _insert_pg(db_url, code, points):\n"
    '            """Insert NAV points to PostgreSQL, return count inserted."""\n'
    "            conn = psycopg2.connect(db_url, sslmode=\"require\")\n"
    "            cur = conn.cursor()\n"
    "            inserted = 0\n"
    "            for pt in points:\n"
    "                cur.execute(\n"
    "                    \"INSERT INTO nav_history (fund_code, date, nav, source, status) \"\n"
    "                    \"VALUES (%s, %s, %s, 'tcinvest', 'draft') \"\n"
    "                    \"ON CONFLICT (fund_code, date) DO NOTHING\",\n"
    "                    (code, pt[\"date\"], float(pt[\"nav\"]))\n"
    "                )\n"
    "                inserted += cur.rowcount\n"
    "            conn.commit()\n"
    "            conn.close()\n"
    "            return inserted"
)
NEW_INSERT = (
    "        def _insert_pg(db_url, code, points, source='manual'):\n"
    '            """Insert NAV points to PostgreSQL nav_history, return count inserted."""\n'
    "            conn = psycopg2.connect(db_url)\n"
    "            cur = conn.cursor()\n"
    "            inserted = 0\n"
    "            for pt in points:\n"
    "                cur.execute(\n"
    "                    \"INSERT INTO nav_history (fund_code, nav_date, nav, source) \"\n"
    "                    \"VALUES (%s, %s, %s, %s) \"\n"
    "                    \"ON CONFLICT (fund_code, nav_date) DO NOTHING\",\n"
    "                    (code, pt[\"date\"], float(pt[\"nav\"]), source)\n"
    "                )\n"
    "                inserted += cur.rowcount\n"
    "            conn.commit()\n"
    "            conn.close()\n"
    "            return inserted"
)
if OLD_INSERT in srv:
    srv = srv.replace(OLD_INSERT, NEW_INSERT, 1)
    print('OK fix1: _insert_pg columns fixed')
else:
    print('FAIL fix1: _insert_pg not found exactly')

# ════════════════════════════════════════════════════════════════
# FIX 2: _api_admin_fetch_nav — thay _bot.save_nav_to_db bằng inline save
# ════════════════════════════════════════════════════════════════
OLD_SAVE = (
    "                    if pts_all and db_url:\n"
    "                        try:\n"
    "                            saved = _bot.save_nav_to_db(db_url, code, pts_all)\n"
    "                            results[code] = saved\n"
    "                            log.info(f\"[fetch-nav] saved {code}: +{saved}\")\n"
    "                        except Exception as ex:\n"
    "                            errors[f\"save_{code}\"] = str(ex)\n"
    "                            log.warning(f\"save {code}: {ex}\")"
)
NEW_SAVE = (
    "                    if pts_all and db_url:\n"
    "                        try:\n"
    "                            import psycopg2\n"
    "                            _conn = psycopg2.connect(db_url)\n"
    "                            _cur = _conn.cursor()\n"
    "                            _saved = 0\n"
    "                            for _pt in pts_all:\n"
    "                                _cur.execute(\n"
    "                                    \"INSERT INTO nav_history (fund_code, nav_date, nav, source) \"\n"
    "                                    \"VALUES (%s, %s, %s, %s) \"\n"
    "                                    \"ON CONFLICT (fund_code, nav_date) DO NOTHING\",\n"
    "                                    (code, _pt['date'], float(_pt['nav']), 'tcinvest')\n"
    "                                )\n"
    "                                _saved += _cur.rowcount\n"
    "                            _conn.commit(); _conn.close()\n"
    "                            results[code] = _saved\n"
    "                            log.info(f\"[fetch-nav] saved {code}: +{_saved}\")\n"
    "                        except Exception as ex:\n"
    "                            errors[f\"save_{code}\"] = str(ex)\n"
    "                            log.warning(f\"save {code}: {ex}\")"
)
if OLD_SAVE in srv:
    srv = srv.replace(OLD_SAVE, NEW_SAVE, 1)
    print('OK fix2: fetch-nav inline save fixed')
else:
    print('FAIL fix2: fetch-nav save block not found')

open(SRV, 'w', encoding='utf-8').write(srv)

# ════════════════════════════════════════════════════════════════
# FIX 3: bot.py — TCBF fmarket_id: 22 → None
# (fmarket id=22 là quỹ khác, NAV 19,799 ≠ TCBF 20,631)
# ════════════════════════════════════════════════════════════════
bot = open(BOT, encoding='utf-8').read()
OLD_TCBF = '"TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",           "fmarket_id": 22,   "tcbs": True},'
NEW_TCBF = '"TCBF":    {"name": "Quỹ Trái Phiếu Techcombank",           "fmarket_id": None, "tcbs": True},  # fmarket_id=22 là quỹ khác'
if OLD_TCBF in bot:
    bot = bot.replace(OLD_TCBF, NEW_TCBF, 1)
    open(BOT, 'w', encoding='utf-8').write(bot)
    print('OK fix3: TCBF fmarket_id=22 -> None')
else:
    print('FAIL fix3: TCBF line not found')

print('\nAll done.')
