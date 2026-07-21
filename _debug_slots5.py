"""Compare upgrade counts between ships"""
import sqlite3

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
vc = '26,8,0,0_8859114'

# Compare ship upgrade info for different ships at tier 4
ships_to_check = [
    ('PASB013_Arkansas_1912', 'Arkansas Beta (T4 premium US BB)'),
    ('PASB004_Arkansas_1912', 'Arkansas (T4 tech tree US BB)'),
    ('PASB001_Michigan_1916', 'Michigan (T3 tech tree US BB)'),
    ('PASB006_New_York_1934', 'New York (T5 tech tree US BB)'),
]

for sid, desc in ships_to_check:
    rows = conn.execute(
        "SELECT upgrade_key, uc_type FROM ship_upgrade_info "
        "WHERE version_code=? AND ship_id=? ORDER BY uc_type",
        (vc, sid)).fetchall()
    types = [r['uc_type'] for r in rows]
    print("%s (%s): %d entries" % (sid, desc, len(rows)))
    for r in rows:
        print("  %s  %s" % (r['uc_type'], r['upgrade_key']))
    print()

conn.close()
