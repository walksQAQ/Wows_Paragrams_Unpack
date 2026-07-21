"""Debug script: check upgrade slots for PASB013 Arkansas Beta"""
import sqlite3, json

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
vc = '26,8,0,0_8859114'

# 1. Check PASB013 basic info
row = conn.execute(
    "SELECT * FROM ship_basic_info WHERE version_code=? AND ship_id=?",
    (vc, 'PASB013')).fetchone()
print("=== PASB013 Basic Info ===")
if row:
    print(dict(row))
else:
    print("NOT FOUND")

# 2. Check ShipUpgradeInfo
rows = conn.execute(
    "SELECT upgrade_key, uc_type, components_json FROM ship_upgrade_info "
    "WHERE version_code=? AND ship_id=?",
    (vc, 'PASB013')).fetchall()
print("\n=== PASB013 ShipUpgradeInfo (%d entries) ===" % len(rows))
for r in rows:
    print("  %s  type=%s" % (r['upgrade_key'], r['uc_type']))

# 3. Count total ships with upgrade info
cnt = conn.execute(
    "SELECT COUNT(DISTINCT ship_id) as cnt FROM ship_upgrade_info "
    "WHERE version_code=?", (vc,)).fetchone()
print("\nShips with upgrade_info entries: %d" % cnt['cnt'])

# 4. Check all tables
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("\nTables in DB:")
for t in tables:
    print("  " + t['name'])

# 5. Check modernizations that match tier 4 BB
print("\n=== Modernizations for tier 4 battleship ===")
mods = conn.execute(
    "SELECT mod_id, slot, shiptype_json, shiplevel_json, nations_json, ships_json "
    "FROM modernization_basic_info WHERE version_code=? AND slot>=0 AND slot<=5 "
    "ORDER BY slot, rarity", (vc,)).fetchall()
for m in mods:
    ships = json.loads(m['ships_json'] or '[]')
    types = json.loads(m['shiptype_json'] or '[]')
    levels = json.loads(m['shiplevel_json'] or '[]')
    
    # Check if this mod could match PASB013 (tier 4, Battleship)
    match_type = not types or 'Battleship' in types or 'BBS' in types
    match_tier = not levels or 4 in levels
    match_ship = not ships or 'PASB013' in ships
    
    if match_type and match_tier and match_ship:
        print("  Slot %d: %s (type_match=%s, tier_match=%s, ship_match=%s)" % (
            m['slot'], m['mod_id'], match_type, match_tier, match_ship))

conn.close()
