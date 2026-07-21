import sqlite3

db_path = r'd:\Wows Paragrams Unpack\release\data\game_data.db'
conn = sqlite3.connect(db_path)

# List ALL columns in ship_module_hulls
cols = conn.execute("PRAGMA table_info(ship_module_hulls)").fetchall()
print(f"=== ship_module_hulls COLUMNS ({len(cols)}) ===")
for c in cols:
    print(f"  {c[1]} ({c[2]})")

# Check if underwaterProtection is stored anywhere in the split JSON
# Let's search the ship data for different field names
# First check what version codes exist
print("\n=== VERSION CODES ===")
vers = conn.execute("SELECT * FROM data_version_registry").fetchall()
for v in vers:
    print(f"  {v}")

# Check what ships exist
print(f"\n=== SHIPS IN DATABASE ===")
ships = conn.execute("SELECT ship_id FROM ship_basic_info ORDER BY ship_id").fetchall()
print(f"Total ships: {len(ships)}")
for s in ships:
    if 'PJSB' in s[0] or 'PRSB' in s[0] or 'PASB' in s[0]:
        print(f"  {s[0]}")

# Check ship_module_hulls for PJSB520
print(f"\n=== HULL DATA FOR PJSB520 ===")
rows = conn.execute("SELECT * FROM ship_module_hulls WHERE ship_id='PJSB520'").fetchall()
if rows:
    col_names = [c[1] for c in cols]
    for r in rows:
        for i, cn in enumerate(col_names):
            print(f"  {cn}: {r[i]}")
        print("---")
else:
    print("No hull data for PJSB520")

# Check ship_module_hulls for PRSB210
print(f"\n=== HULL DATA FOR PRSB210 ===")
rows = conn.execute("SELECT * FROM ship_module_hulls WHERE ship_id='PRSB210'").fetchall()
if rows:
    col_names = [c[1] for c in cols]
    for r in rows:
        for i, cn in enumerate(col_names):
            print(f"  {cn}: {r[i]}")
        print("---")
else:
    print("No hull data for PRSB210")

# Check if there's any data with these ship IDs at all
print(f"\n=== ENTITY REGISTRY ===")
ents = conn.execute("SELECT entity_id, entity_type FROM entity_registry WHERE entity_id LIKE 'PJSB%' OR entity_id LIKE 'PRSB%'").fetchall()
for e in ents:
    print(f"  {e[0]} ({e[1]})")

conn.close()
