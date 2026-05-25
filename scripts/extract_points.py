import json
import sqlite3
import os

def migrate_streamerbot_points():
    # 1. Load the Twitch Data to map User ID -> Username
    twitch_dump_path = 'temp_litedb/twitch_dump.json'
    globals_dump_path = 'temp_litedb/globals_dump.json'
    db_path = 'data/rpg_database.db'
    
    if not os.path.exists(twitch_dump_path) or not os.path.exists(globals_dump_path):
        print("Error: Missing JSON dump files. Please make sure C# export script ran.")
        return

    print("Loading twitch_dump.json...")
    with open(twitch_dump_path, 'r', encoding='utf-8') as f:
        twitch_data = json.load(f)
        
    print("Loading globals_dump.json...")
    with open(globals_dump_path, 'r', encoding='utf-8') as f:
        globals_data = json.load(f)

    # Build User ID -> Username map
    user_map = {}
    if 'users' in twitch_data:
        for user in twitch_data['users']:
            uid = user.get('Id')
            name = user.get('Login')  # Try 'Login' or 'Name' or 'DisplayName'
            if not name:
                name = user.get('Name')
            if not name:
                name = user.get('DisplayName')
            
            if uid and name:
                # Ensure lowercase for exact DB match
                user_map[str(uid)] = name.lower()

    print(f"Mapped {len(user_map)} Twitch users.")

    # Extract Points
    # Streamerbot points are inside user_globals -> value structure: "type":"points", "value": { "$numberLong": "100" } or "100"
    points_map = {}
    if 'user_globals' in globals_data:
        for g in globals_data['user_globals']:
            name_key = g.get('name', '').lower()
            if 'points' in name_key:
                uid = str(g.get('userId'))
                username = user_map.get(uid)
                if username:
                    val_obj = g.get('value')
                    # Extract the actual value from LiteDB JSON Export format
                    points = 0
                    if isinstance(val_obj, dict):
                        if '$numberLong' in val_obj:
                            points = int(val_obj['$numberLong'])
                        elif '$numberInt' in val_obj:
                            points = int(val_obj['$numberInt'])
                        elif '$numberDouble' in val_obj:
                            points = int(float(val_obj['$numberDouble']))
                    elif isinstance(val_obj, (int, float, str)):
                        try:
                            points = int(val_obj)
                        except:
                            pass
                    
                    if points > 0:
                        points_map[username] = points

    print(f"Found points for {len(points_map)} users.")

    # Import into bot SQLite database
    print(f"Importing to {db_path}...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (username TEXT PRIMARY KEY, level INTEGER, xp INTEGER, currency INTEGER,
                 strength INTEGER, max_hp INTEGER, current_hp INTEGER)''')
    
    count = 0
    for username, points in points_map.items():
        # Add to currency if user exists, else create user with that currency
        c.execute("SELECT currency FROM players WHERE username=?", (username,))
        row = c.fetchone()
        if row:
            new_val = row[0] + points
            c.execute("UPDATE players SET currency=? WHERE username=?", (new_val, username))
        else:
            c.execute("INSERT INTO players (username, level, xp, currency, strength, max_hp, current_hp) VALUES (?, 1, 0, ?, 1, 100, 100)", (username, points))
        count += 1
        
    conn.commit()
    conn.close()
    
    print(f"Successfully migrated points for {count} users!")

if __name__ == "__main__":
    migrate_streamerbot_points()
