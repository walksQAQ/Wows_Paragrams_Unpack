"""Debug: check why specific PASB ships aren't found"""
import sqlite3, json

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
vc = '26,8,0,0_8859114'

# Check all version codes
vcs = conn.execute("SELECT DISTINCT version_code FROM ship_basic_info").fetchall()
print("Version codes:", [r['version_code'] for r in vcs])

# Try the other version code if any
for ver in vcs:
    v = ver['version_code']
    row = conn.execute(
        "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?",
        (v, 'PASB013')).fetchone()
    print("\nTrying version %s:" % v)
    if row:
        print("  FOUND:", dict(row))
    else:
        print("  NOT FOUND")
    
    # List first 5 PASB ships for this version
    ships = conn.execute(
        "SELECT ship_id, tier FROM ship_basic_info WHERE version_code=? AND ship_id LIKE 'PASB%%'",
        (v,)).fetchall()
    print("  PASB ships:", [s['ship_id'] for s in ships])

conn.close()
