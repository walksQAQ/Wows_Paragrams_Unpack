import sqlite3
conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row

r = conn.execute("SELECT aura_name, aura_type, aura_dps, min_distance, max_distance, hit_chance FROM ship_module_aa WHERE ship_id='PHSC110_Gouden_Leeuw'").fetchall()
print("PHSC110 AA rows:")
for row in r:
    d = dict(row)
    print(f"  {d}")

# Also check what auras the ship should have from analysis
print("\n--- Checking raw collection ---")
# Check if Med1 was stored from ATBA
r2 = conn.execute("SELECT DISTINCT aura_name FROM ship_module_aa").fetchall()
print(f"All distinct aura_names in DB: {[r[0] for r in r2]}")

conn.close()
