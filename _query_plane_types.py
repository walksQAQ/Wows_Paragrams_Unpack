import sqlite3

conn = sqlite3.connect(r'data/game_data.db')
c = conn.cursor()

# 1. Distinct plane_type values
print('=== DISTINCT plane_type FROM ship_module_aircraft ===')
c.execute('SELECT DISTINCT plane_type FROM ship_module_aircraft')
rows = c.fetchall()
for r in rows:
    print(r[0])
print()

# 2. Taiho entries
print('=== ship_module_aircraft WHERE ship_id LIKE %Taiho% or PJSA210_Taiho ===')
c.execute('SELECT * FROM ship_module_aircraft WHERE ship_id LIKE ? OR ship_id=?', ('%Taiho%', 'PJSA210_Taiho'))
cols = [desc[0] for desc in c.description]
rows = c.fetchall()
for row in rows:
    for i, col in enumerate(cols):
        print(f'  {col}: {row[i]}')
    print()

# 3. Mine entries
print('=== ship_module_aircraft WHERE module_key LIKE %Mine% or plane_type=Mine ===')
c.execute('SELECT * FROM ship_module_aircraft WHERE module_key LIKE ? OR plane_type=?', ('%Mine%', 'Mine'))
cols2 = [desc[0] for desc in c.description]
rows2 = c.fetchall()
for row in rows2:
    for i, col in enumerate(cols2):
        print(f'  {col}: {row[i]}')
    print()

conn.close()
