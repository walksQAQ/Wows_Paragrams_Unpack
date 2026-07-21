import sqlite3
conn = sqlite3.connect(r'd:\Wows Paragrams Unpack\data\game_data.db')
c = conn.cursor()

# List all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [t[0] for t in c.fetchall()]
print("=== All Tables ===")
for t in tables:
    print(f"  {t}")

# For each table, show schema
for t in tables:
    c.execute(f"PRAGMA table_info({t})")
    cols = c.fetchall()
    print(f"\n--- {t} ---")
    for col in cols:
        print(f"  {col[1]} ({col[2]})")

conn.close()
