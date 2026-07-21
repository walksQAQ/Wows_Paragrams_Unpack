import sqlite3

conn = sqlite3.connect('data/game_data.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('=== 1. PGPA110 in plane_basic_info ===')
cur.execute("SELECT * FROM plane_basic_info WHERE plane_id LIKE '%PGPA110%' OR plane_id LIKE '%PGPA11%'")
rows = cur.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print('(no results)')

print()
print('=== 2. Aircraft with PGPA prefix ===')
cur.execute("SELECT plane_id, species FROM plane_basic_info WHERE plane_id LIKE 'PGPA%'")
rows = cur.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print('(no results)')

print()
print('=== 3. Projectile related to PGPA ===')
cur.execute("SELECT * FROM projectile_basic_info WHERE projectile_id LIKE '%PGPA110%' OR projectile_id LIKE '%PGP%AP%' OR projectile_id LIKE '%PGP%ap%' OR projectile_id LIKE '%PGP%rocket%'")
rows = cur.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print('(no results)')

print()
print('=== 4. Distinct projectile species values ===')
cur.execute('SELECT DISTINCT species, ammo_type FROM projectile_basic_info ORDER BY species')
rows = cur.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print('(no results)')

conn.close()
