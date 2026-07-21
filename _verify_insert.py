import sqlite3

db_path = r"D:\Wows Paragrams Unpack\data\game_data.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT * FROM name_mappings WHERE category='skill_desc' AND key_name='detection_direction'")
row = c.fetchone()
conn.close()

if row:
    print("=== 验证成功 ===")
    print(f"ID:       {row[0]}")
    print(f"Category: {row[1]}")
    print(f"Key:      {row[2]}")
    print(f"lang_zh:  {row[3]}")
else:
    print("未找到记录")
