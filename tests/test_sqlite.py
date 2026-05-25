import sqlite3
import os

db_folder = r"E:\_Live Streaming Work\OPALLO11 - Live Streaming\All Program\Streamerbot\data"
db_files = [f for f in os.listdir(db_folder) if f.endswith('.db')] if os.path.exists(db_folder) else []

for db_file in db_files:
    path = os.path.join(db_folder, db_file)
    print(f"\n--- {db_file} ---")
    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        for t in tables:
            print(f"Table: {t[0]}")
            cursor.execute(f"PRAGMA table_info({t[0]})")
            columns = cursor.fetchall()
            print("  Columns:", [col[1] for col in columns])
            
            # If it's something that sounds like points or globals, fetch a bit
            if 'global' in t[0].lower() or 'point' in t[0].lower() or 'user' in t[0].lower():
                cursor.execute(f"SELECT * FROM {t[0]} LIMIT 3")
                print("  Sample data:", cursor.fetchall())
        conn.close()
    except Exception as e:
        print("Error:", e)
