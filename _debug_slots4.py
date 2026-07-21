"""Debug: check exact ship_id match"""
import sqlite3

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
vc = '26,8,0,0_8859114'

# Get PASB013 data directly
row = conn.execute(
    "SELECT ship_id, tier, shiptype, name_mapping_id FROM ship_basic_info "
    "WHERE version_code=? AND ship_id=?",
    (vc, 'PASB013_Arkansas_1912')).fetchone()
print("Using 'PASB013_Arkansas_1912':", dict(row) if row else "NOT FOUND")

# Try the full ID
row = conn.execute(
    "SELECT ship_id, tier FROM ship_basic_info "
    "WHERE version_code=? AND ship_id='PASB013_Arkansas_1912'",
    (vc,)).fetchone()
print("With literal string:", dict(row) if row else "NOT FOUND")

# Just get first 10 rows to see ship_id format
rows = conn.execute(
    "SELECT ship_id FROM ship_basic_info WHERE version_code=? LIMIT 10",
    (vc,)).fetchall()
print("Sample ship_ids:")
for r in rows:
    print("  [%s]" % r['ship_id'])

# Check PASB013 upgrade info with full name
rows = conn.execute(
    "SELECT upgrade_key, uc_type FROM ship_upgrade_info "
    "WHERE version_code=? AND ship_id=?",
    (vc, 'PASB013_Arkansas_1912')).fetchall()
print("\nPASB013_Arkansas_1912 upgrade info:", len(rows), "entries")
for r in rows:
    print("  %s  type=%s" % (r['upgrade_key'], r['uc_type']))

conn.close()
