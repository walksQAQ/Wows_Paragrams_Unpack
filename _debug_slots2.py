"""Debug script 2: compare with similar ships"""
import sqlite3, json

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
vc = '26,8,0,0_8859114'

# Check PASB004 (Arkansas tech tree)
print("=== PASB004 (Arkansas tech tree) ===")
row = conn.execute(
    "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?",
    (vc, 'PASB004')).fetchone()
if row:
    print(dict(row))
    # Check upgrade info
    rows = conn.execute(
        "SELECT upgrade_key, uc_type FROM ship_upgrade_info "
        "WHERE version_code=? AND ship_id=?",
        (vc, 'PASB004')).fetchall()
    print("ShipUpgradeInfo (%d entries):" % len(rows))
    for r in rows:
        print("  %s  type=%s" % (r['upgrade_key'], r['uc_type']))
else:
    print("NOT FOUND")

# Compare with PASB001 (Michigan, tier 3 BB)
print("\n=== PASB001 (Michigan, tier 3) ===")
row = conn.execute(
    "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?",
    (vc, 'PASB001')).fetchone()
if row:
    print(dict(row))
    rows = conn.execute(
        "SELECT upgrade_key, uc_type FROM ship_upgrade_info "
        "WHERE version_code=? AND ship_id=?",
        (vc, 'PASB001')).fetchall()
    print("ShipUpgradeInfo (%d entries):" % len(rows))
    for r in rows:
        print("  %s  type=%s" % (r['upgrade_key'], r['uc_type']))
else:
    print("NOT FOUND")

# Check PASB006 (New York, tier 5)
print("\n=== PASB006 (New York, tier 5) ===")
row = conn.execute(
    "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?",
    (vc, 'PASB006')).fetchone()
if row:
    print(dict(row))
    rows = conn.execute(
        "SELECT upgrade_key, uc_type FROM ship_upgrade_info "
        "WHERE version_code=? AND ship_id=?",
        (vc, 'PASB006')).fetchall()
    print("ShipUpgradeInfo (%d entries):" % len(rows))
    for r in rows:
        print("  %s  type=%s" % (r['upgrade_key'], r['uc_type']))
else:
    print("NOT FOUND")

# Show the total count
total_ships = conn.execute(
    "SELECT COUNT(*) as cnt FROM ship_basic_info WHERE version_code=?", 
    (vc,)).fetchone()
print("\nTotal ships in ship_basic_info: %d" % total_ships['cnt'])

total_upgrade = conn.execute(
    "SELECT COUNT(*) as cnt FROM ship_upgrade_info WHERE version_code=?", 
    (vc,)).fetchone()
print("Total upgrade entries: %d" % total_upgrade['cnt'])

distinct_upgrade = conn.execute(
    "SELECT COUNT(DISTINCT ship_id) as cnt FROM ship_upgrade_info WHERE version_code=?", 
    (vc,)).fetchone()
print("Ships with upgrade info: %d" % distinct_upgrade['cnt'])

conn.close()
