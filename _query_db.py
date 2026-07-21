import sqlite3
conn = sqlite3.connect(r'd:\Wows Paragrams Unpack\data\game_data.db')
c = conn.cursor()

version = '26,8,0,0_8859114'

# Query projectile_basic_info for the projectiles used by PASA111's planes
# From plane_basic_info: PAAD120 -> bomb_name=PAPB120, PAAD121 -> bomb_name=PAPB121
# PAAF120 -> bomb_name=PAPR210_Midway_top (rocket), PAAF121 -> bomb_name=PAPR121_UNITED_STATES_JET
# PAAB121 -> bomb_name=PAPT120_UNITED_STATES_STOCK (torpedo)
projectile_ids = ['PAPB120_UNITED_STATES_STOCK', 'PAPB121_UNITED_STATES_JET',
                  'PAPR210_Midway_top', 'PAPR121_UNITED_STATES_JET',
                  'PAPT120_UNITED_STATES_STOCK']

print("=== projectile_basic_info ===")
for pid in projectile_ids:
    c.execute("SELECT * FROM projectile_basic_info WHERE version_code=? AND projectile_id=?", (version, pid))
    rows = c.fetchall()
    if rows:
        cols = [desc[0] for desc in c.description]
        for row in rows:
            print(f"\n--- {pid} ---")
            for i, col in enumerate(cols):
                print(f"  {col}: {row[i]}")
    else:
        print(f"\n--- {pid} --- (not found)")
print()

# Also check projectile subtype tables
print("=== projectile_bomb_ext for PAPB projectiles ===")
for pid in ['PAPB120_UNITED_STATES_STOCK', 'PAPB121_UNITED_STATES_JET']:
    c.execute("SELECT * FROM projectile_bomb_ext WHERE version_code=? AND projectile_id=?", (version, pid))
    rows = c.fetchall()
    if rows:
        cols = [desc[0] for desc in c.description]
        for row in rows:
            print(f"\n--- {pid} ---")
            for i, col in enumerate(cols):
                print(f"  {col}: {row[i]}")
    else:
        print(f"\n--- {pid} --- (not found)")

print()
print("=== projectile_rocket_ext for PAPR projectiles ===")
for pid in ['PAPR210_Midway_top', 'PAPR121_UNITED_STATES_JET']:
    c.execute("SELECT * FROM projectile_rocket_ext WHERE version_code=? AND projectile_id=?", (version, pid))
    rows = c.fetchall()
    if rows:
        cols = [desc[0] for desc in c.description]
        for row in rows:
            print(f"\n--- {pid} ---")
            for i, col in enumerate(cols):
                print(f"  {col}: {row[i]}")
    else:
        print(f"\n--- {pid} --- (not found)")

print()
print("=== projectile_torpedo_ext for PAPT projectiles ===")
c.execute("SELECT * FROM projectile_torpedo_ext WHERE version_code=? AND projectile_id=?", (version, 'PAPT120_UNITED_STATES_STOCK'))
rows = c.fetchall()
if rows:
    cols = [desc[0] for desc in c.description]
    for row in rows:
        print(f"\n--- PAPT120_UNITED_STATES_STOCK ---")
        for i, col in enumerate(cols):
            print(f"  {col}: {row[i]}")
else:
    print("(not found)")

conn.close()
