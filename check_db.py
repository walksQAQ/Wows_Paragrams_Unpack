import sqlite3

db_path = r'd:\Wows Paragrams Unpack\release\data\game_data.db'
conn = sqlite3.connect(db_path)

# Check what tables exist
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== TABLES ===")
for t in tables:
    print(f"  {t[0]}")

# Check ship_module_hulls schema
cols = conn.execute("PRAGMA table_info(ship_module_hulls)").fetchall()
print("\n=== ship_module_hulls COLUMNS ===")
for c in cols:
    print(f"  {c[1]} ({c[2]})")

# Query for PJSB520 and PRSB210
print("\n=== TORPEDO PROTECTION DATA ===")
rows = conn.execute("""
    SELECT ship_id, config_group, module_key, torpedo_protection, health, draft
    FROM ship_module_hulls
    WHERE ship_id IN ('PJSB520', 'PRSB210')
    ORDER BY ship_id, config_group
""").fetchall()

print(f"ship_id      | config | module_key            | torpedo_protection | health     | draft")
print("-" * 100)
for r in rows:
    tp = str(r[3]) if r[3] is not None else "NULL"
    h = str(r[4]) if r[4] is not None else "NULL"
    d = str(r[5]) if r[5] is not None else "NULL"
    print(f"{r[0]:12s} | {str(r[1]):6s} | {str(r[2]):21s} | {tp:18s} | {h:10s} | {d}")

# Also query PASB111 (Maine) for comparison
print("\n=== MAINE (PASB111) for comparison ===")
rows2 = conn.execute("""
    SELECT ship_id, config_group, module_key, torpedo_protection, health, draft
    FROM ship_module_hulls
    WHERE ship_id = 'PASB111'
    ORDER BY config_group
""").fetchall()
for r in rows2:
    tp = str(r[3]) if r[3] is not None else "NULL"
    h = str(r[4]) if r[4] is not None else "NULL"
    d = str(r[5]) if r[5] is not None else "NULL"
    print(f"{r[0]:12s} | {str(r[1]):6s} | {str(r[2]):21s} | {tp:18s} | {h:10s} | {d}")

# Check all unique torpedo_protection values
print("\n=== ALL UNIQUE torpedo_protection VALUES (first 50) ===")
rows3 = conn.execute("SELECT DISTINCT torpedo_protection FROM ship_module_hulls WHERE torpedo_protection IS NOT NULL ORDER BY torpedo_protection").fetchall()
print(f"Total unique non-null values: {len(rows3)}")
for r in rows3[:50]:
    print(f"  {r[0]}")

# Check if underwaterProtection exists anywhere in the split JSON files
print("\n=== Checking if any row has torpedo_protection IS NULL for these ships ===")
rows4 = conn.execute("""
    SELECT ship_id, config_group, module_key
    FROM ship_module_hulls
    WHERE ship_id IN ('PJSB520', 'PRSB210') AND torpedo_protection IS NULL
""").fetchall()
if rows4:
    print(f"NULL torpedo_protection for: {len(rows4)} rows")
    for r in rows4:
        print(f"  {r[0]} {r[1]} {r[2]}")
else:
    print("All rows have non-NULL torpedo_protection values")

conn.close()
