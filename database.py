import sqlite3
import os
import threading
from datetime import datetime, timedelta
import json
import queue
import time
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DATA_DIR, 'database.db')

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class SQLiteDatabase:
    def __init__(self):
        self.lock = threading.Lock()
        os.makedirs(DATA_DIR, exist_ok=True)
        self._init_db()
        
        # Combat Log Batching Queue
        self.combat_queue = queue.Queue()
        self.batch_thread = threading.Thread(target=self._combat_log_worker, daemon=True)
        self.batch_thread.start()

    def get_connection(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        # Enable Write-Ahead Logging for better concurrent performance
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.row_factory = dict_factory
        return conn

    def _init_db(self):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()

            c.execute('''CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                twitch_id TEXT,
                character_name TEXT,
                class TEXT DEFAULT 'warrior',
                class_levels TEXT DEFAULT '{}',
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                hp INTEGER DEFAULT 1000,
                max_hp INTEGER DEFAULT 1000,
                mp INTEGER DEFAULT 50,
                max_mp INTEGER DEFAULT 50,
                atk INTEGER DEFAULT 100,
                def INTEGER DEFAULT 30,
                equipped_weapon INTEGER,
                equipped_armor INTEGER,
                equipped_accessory INTEGER,
                total_damage INTEGER DEFAULT 0,
                bosses_defeated INTEGER DEFAULT 0,
                mvp_count INTEGER DEFAULT 0,
                session_renamed BOOLEAN DEFAULT 0,
                session_class_changed BOOLEAN DEFAULT 0,
                gold INTEGER DEFAULT 0,
                protection_scrolls INTEGER DEFAULT 0,
                scroll_t1 INTEGER DEFAULT 0,
                scroll_t2 INTEGER DEFAULT 0,
                scroll_t3 INTEGER DEFAULT 0,
                created_at TEXT
            )''')

            # Migrate existing tables
            try:
                c.execute("ALTER TABLE players ADD COLUMN class_levels TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN session_class_changed BOOLEAN DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN gold INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN protection_scrolls INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN scroll_t1 INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN scroll_t2 INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE players ADD COLUMN scroll_t3 INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            
            # Migrate old protection_scrolls to scroll_t1
            try:
                c.execute("UPDATE players SET scroll_t1 = scroll_t1 + protection_scrolls, protection_scrolls = 0 WHERE protection_scrolls > 0")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                item_id TEXT,
                obtained_from TEXT,
                obtained_at TEXT,
                enhancement_level INTEGER DEFAULT 0,
                FOREIGN KEY(owner_id) REFERENCES players(id)
            )''')
            
            try:
                c.execute("ALTER TABLE items ADD COLUMN enhancement_level INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS bosses (
                instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_id TEXT,
                name TEXT,
                type TEXT,
                element TEXT,
                base_hp INTEGER,
                base_def INTEGER DEFAULT 0,
                current_hp INTEGER,
                max_hp INTEGER,
                weakness TEXT,
                resist TEXT,
                image_url TEXT,
                participants TEXT DEFAULT '[]',
                spawned_at TEXT,
                status TEXT DEFAULT 'active',
                defeated_at TEXT
            )''')

            try:
                c.execute("ALTER TABLE bosses ADD COLUMN base_def INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass

            c.execute('''CREATE TABLE IF NOT EXISTS cooldowns (
                player_id INTEGER,
                action TEXT,
                expires_at TEXT,
                PRIMARY KEY (player_id, action)
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS combat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_instance_id INTEGER,
                player_id INTEGER,
                action TEXT,
                damage INTEGER,
                is_crit BOOLEAN,
                timestamp TEXT
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS art_gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                bits_amount INTEGER,
                prompt TEXT,
                image_url TEXT,
                is_custom BOOLEAN,
                discord_posted BOOLEAN,
                created_at TEXT
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS stream_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_type TEXT,
                description TEXT,
                target_value INTEGER,
                current_value INTEGER DEFAULT 0,
                reward_type TEXT,
                reward_amount INTEGER,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )''')

            conn.commit()
            conn.close()

    def reset_rename_limits(self):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("UPDATE players SET session_renamed = 0, session_class_changed = 0")
            conn.commit()
            conn.close()

    def _hydrate_player(self, row):
        """Shared post-processing for a raw player DB row."""
        if not row:
            return None
        p = dict(row)
        try:
            p['class_levels'] = json.loads(p.get('class_levels') or '{}')
        except Exception:
            p['class_levels'] = {}
        cls_name = p.get('class', 'warrior').lower()
        if cls_name in p['class_levels']:
            p['level'] = p['class_levels'][cls_name].get('level', p.get('level', 1))
        else:
            p['level'] = p.get('level', 1)

        # Dynamic stats capping
        try:
            from game.logic import calculate_player_stats
            s = calculate_player_stats(p)
            if p['hp'] > s['max_hp']:
                p['hp'] = s['max_hp']
            if p['mp'] > s['max_mp']:
                p['mp'] = s['max_mp']
        except Exception as e:
            print(f"Error capping player HP/MP: {e}")

        return p

    def get_player(self, username):
        conn = self.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM players WHERE username = ? OR LOWER(character_name) = ?", (username.lower(), username.lower()))
            row = c.fetchone()
        finally:
            conn.close()
        return self._hydrate_player(row)

    def get_player_by_id(self, player_id):
        conn = self.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM players WHERE id = ?", (player_id,))
            row = c.fetchone()
        finally:
            conn.close()
        return self._hydrate_player(row)

    def create_player(self, username, twitch_id, character_name, class_name="warrior"):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM players WHERE username = ? OR twitch_id = ?", (username.lower(), str(twitch_id)))
            if c.fetchone():
                conn.close()
                return False

            # Load classes.json to initialize correct HP and MP
            classes_path = os.path.join(DATA_DIR, 'classes.json')
            initial_hp = 1000
            initial_mp = 50
            try:
                with open(classes_path, 'r', encoding='utf-8') as f:
                    classes_data = json.load(f)
                cls_info = classes_data.get(class_name.lower())
                if cls_info:
                    initial_hp = cls_info['base_stats']['hp']
                    initial_mp = cls_info['base_stats']['mp']
                    # Add Priest passive MP bonus if applicable
                    passive = cls_info.get('passive', {})
                    initial_mp += passive.get('bonus_mp', 0)
            except Exception as e:
                print(f"Error loading classes.json in create_player: {e}")

            now = datetime.now().isoformat()
            initial_levels = json.dumps({class_name: {"level": 1, "exp": 0}})
            c.execute('''INSERT INTO players (username, twitch_id, character_name, class, class_levels, hp, mp, created_at, session_renamed, session_class_changed) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)''', 
                      (username.lower(), str(twitch_id), character_name, class_name, initial_levels, initial_hp, initial_mp, now))
            conn.commit()
            conn.close()
            return True

    def update_player(self, player_id, updates):
        if not updates:
            return False
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            query = "UPDATE players SET " + ", ".join([f"{k} = ?" for k in updates.keys()]) + " WHERE id = ?"
            values = list(updates.values()) + [player_id]
            c.execute(query, tuple(values))
            conn.commit()
            success = c.rowcount > 0
            conn.close()
            return success

    def update_player_hp(self, player_id, new_hp):
        return self.update_player(player_id, {"hp": new_hp})

    def add_item(self, owner_id, item_data, boss_name=""):
        item_id = item_data.get('id', 'unknown') if isinstance(item_data, dict) else str(item_data)
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''INSERT INTO items (owner_id, item_id, obtained_from, obtained_at, enhancement_level) 
                         VALUES (?, ?, ?, ?, 0)''', 
                      (owner_id, item_id, boss_name, now))
            new_id = c.lastrowid
            conn.commit()
            conn.close()
            return {"id": new_id, "owner_id": owner_id, "item_id": item_id, "obtained_from": boss_name, "obtained_at": now, "enhancement_level": 0}

    # NOTE: give_item_or_enhance() has been moved to game/enhancement.py

    def get_active_boss(self):
        conn = self.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM bosses WHERE status = 'active' ORDER BY instance_id DESC LIMIT 1")
            boss = c.fetchone()
            if boss:
                boss = dict(boss)
                boss['weakness'] = json.loads(boss['weakness']) if boss['weakness'] else []
                boss['resist'] = json.loads(boss['resist']) if boss['resist'] else []
                boss['participants'] = json.loads(boss['participants']) if boss['participants'] else []
                
                participants = boss['participants']
                if participants:
                    placeholders = ','.join('?' * len(participants))
                    c_parts = conn.cursor()
                    c_parts.execute(f"SELECT class_levels, class, level FROM players WHERE id IN ({placeholders})", tuple(participants))
                    lvl_rows = c_parts.fetchall()
                    if lvl_rows:
                        total_lvl = 0
                        for r in lvl_rows:
                            try:
                                class_levels = json.loads(r.get('class_levels') or '{}')
                            except Exception:
                                class_levels = {}
                            cls_name = r.get('class', 'warrior').lower()
                            lvl = class_levels.get(cls_name, {}).get('level', r.get('level', 1))
                            total_lvl += lvl
                        avg_lvl = total_lvl / len(lvl_rows)
                    else:
                        avg_lvl = 1
                else:
                    avg_lvl = 1
                    
                if avg_lvl <= 5:
                    boss['stars'] = 1
                elif avg_lvl <= 15:
                    boss['stars'] = 2
                elif avg_lvl <= 30:
                    boss['stars'] = 3
                elif avg_lvl <= 50:
                    boss['stars'] = 4
                else:
                    boss['stars'] = 5
        finally:
            conn.close()
        return boss

    def set_active_boss(self, boss_data):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            
            weakness = json.dumps(boss_data.get('weakness', []))
            resist = json.dumps(boss_data.get('resist', []))
            participants = json.dumps(boss_data.get('participants', []))
            now = datetime.now().isoformat()
            
            c.execute('''INSERT INTO bosses (boss_id, name, type, element, base_hp, base_def, current_hp, 
                                            max_hp, weakness, resist, image_url, participants, spawned_at, status) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
                      (boss_data.get('boss_id'), boss_data.get('name'), boss_data.get('type'), 
                       boss_data.get('element'), boss_data.get('base_hp'), boss_data.get('base_def', 0), boss_data.get('current_hp'),
                       boss_data.get('max_hp'), weakness, resist, boss_data.get('image_url'), 
                       participants, now))
            
            instance_id = c.lastrowid
            boss_data['instance_id'] = instance_id
            conn.commit()
            conn.close()

    def update_boss(self, instance_id, updates):
        if not updates:
            return self.get_active_boss()
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            
            update_data = dict(updates)
            if 'weakness' in update_data: update_data['weakness'] = json.dumps(update_data['weakness'])
            if 'resist' in update_data: update_data['resist'] = json.dumps(update_data['resist'])
            if 'participants' in update_data: update_data['participants'] = json.dumps(update_data['participants'])

            query = "UPDATE bosses SET " + ", ".join([f"{k} = ?" for k in update_data.keys()]) + " WHERE instance_id = ?"
            values = list(update_data.values()) + [instance_id]
            c.execute(query, tuple(values))
            
            # Check for defeat
            c.execute("SELECT current_hp FROM bosses WHERE instance_id = ?", (instance_id,))
            row = c.fetchone()
            if row and row['current_hp'] <= 0:
                now = datetime.now().isoformat()
                c.execute("UPDATE bosses SET status = 'defeated', defeated_at = ? WHERE instance_id = ?", (now, instance_id))

            conn.commit()
            conn.close()
            return self.get_active_boss()
            
    def get_cooldown(self, player_id, action):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT expires_at FROM cooldowns WHERE player_id = ? AND action = ?", (player_id, action))
        row = c.fetchone()
        conn.close()
        return row['expires_at'] if row else None

    def set_cooldown(self, player_id, action, expires_at_iso):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute('''INSERT INTO cooldowns (player_id, action, expires_at) 
                         VALUES (?, ?, ?) 
                         ON CONFLICT(player_id, action) DO UPDATE SET expires_at=excluded.expires_at''',
                      (player_id, action, expires_at_iso))
            conn.commit()
            conn.close()

    def clear_cooldown(self, player_id, action):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM cooldowns WHERE player_id = ? AND action = ?", (player_id, action))
            conn.commit()
            conn.close()

    def add_combat_log(self, boss_instance_id, player_id, action, damage, is_crit):
        # Instead of writing immediately, put it in the queue for the batch worker
        now = datetime.now().isoformat()
        self.combat_queue.put((boss_instance_id, player_id, action, damage, is_crit, now))

    def _combat_log_worker(self):
        """Background thread that batches and writes combat logs every second"""
        while True:
            items = []
            try:
                # Wait for at least one item
                items.append(self.combat_queue.get(timeout=1.0))
                # Grab all other items currently in the queue
                while not self.combat_queue.empty():
                    try:
                        items.append(self.combat_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            if not items:
                continue

            # Batch write to DB
            with self.lock:
                conn = self.get_connection()
                try:
                    c = conn.cursor()
                    conn.execute("BEGIN TRANSACTION")
                    
                    # Accumulate damage/healing and track participants
                    player_damage = {} # player_id: total_damage_in_batch
                    player_healing = {} # player_id: total_healing_in_batch
                    boss_participants = {} # boss_instance_id: set(player_ids)
                    log_entries = []
                    
                    healing_actions = ('heal', 'sanctuary', 'miracle')

                    for boss_instance_id, player_id, action, damage, is_crit, timestamp in items:
                        log_entries.append((boss_instance_id, player_id, action, damage, is_crit, timestamp))
                        
                        is_healing = action.lower() in healing_actions
                        if is_healing:
                            player_healing[player_id] = player_healing.get(player_id, 0) + damage
                        else:
                            player_damage[player_id] = player_damage.get(player_id, 0) + damage
                        
                        if boss_instance_id not in boss_participants:
                            boss_participants[boss_instance_id] = set()
                        boss_participants[boss_instance_id].add(player_id)

                    # 1. Insert all combat logs
                    c.executemany('''INSERT INTO combat_log (boss_instance_id, player_id, action, damage, is_crit, timestamp) 
                                     VALUES (?, ?, ?, ?, ?, ?)''', log_entries)
                    
                    # 2. Update players total damage (Gold is no longer awarded in real-time)
                    for p_id, total_dmg in player_damage.items():
                        if total_dmg > 0:
                            c.execute("UPDATE players SET total_damage = total_damage + ? WHERE id = ?", (total_dmg, p_id))
                    
                    # 3. Update boss participants (Optimized)
                    for b_id, p_ids in boss_participants.items():
                        c.execute("SELECT participants FROM bosses WHERE instance_id = ?", (b_id,))
                        boss_row = c.fetchone()
                        if boss_row:
                            current_parts = json.loads(boss_row['participants']) if boss_row['participants'] else []
                            new_parts_added = False
                            for p_id in p_ids:
                                if p_id not in current_parts:
                                    current_parts.append(p_id)
                                    new_parts_added = True
                            
                            if new_parts_added:
                                c.execute("UPDATE bosses SET participants = ? WHERE instance_id = ?", (json.dumps(current_parts), b_id))

                    conn.commit()
                except Exception as e:
                    print(f"Error in batch logger: {e}")
                    conn.rollback()
                finally:
                    conn.close()

    def get_boss_rankings(self, boss_instance_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute('''SELECT player_id, SUM(damage) as total_damage 
                     FROM combat_log 
                     WHERE boss_instance_id = ? 
                     GROUP BY player_id 
                     ORDER BY total_damage DESC''', (boss_instance_id,))
        rows = c.fetchall()
        conn.close()
        
        rankings = []
        for index, row in enumerate(rows):
            rankings.append({
                'id': row['player_id'],
                'rank': index + 1,
                'damage': row['total_damage']
            })
        return rankings

    def add_art_gallery(self, username, bits_amount, prompt, image_url, is_custom, discord_posted):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute('''INSERT INTO art_gallery (username, bits_amount, prompt, image_url, is_custom, discord_posted, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (username, bits_amount, prompt, image_url, is_custom, discord_posted, now))
            conn.commit()
            conn.close()

    def add_player_gold(self, player_id, amount):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("UPDATE players SET gold = gold + ? WHERE id = ?", (amount, player_id))
            conn.commit()
            conn.close()

    # NOTE: buy_shop_item() has been moved to game/shop.py

    def get_player_equipment(self, player_id):
        from game.helpers import find_item_data
        conn = self.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT equipped_weapon, equipped_armor, equipped_accessory FROM players WHERE id = ?", (player_id,))
            p = c.fetchone()
            if not p:
                return {}
                
            eq = {}
            for slot in ['equipped_weapon', 'equipped_armor', 'equipped_accessory']:
                item_db_id = p[slot]
                if item_db_id:
                    c.execute("SELECT id, item_id, enhancement_level FROM items WHERE id = ?", (item_db_id,))
                    item = c.fetchone()
                    if item:
                        item = dict(item)
                        item_data, tier = find_item_data(item['item_id'])
                        item['name'] = item_data['name'] if item_data else item['item_id']
                        item['tier'] = tier or 'R'
                        eq[slot] = item
                    else:
                        eq[slot] = None
                else:
                    eq[slot] = None
        finally:
            conn.close()
        return eq

    def get_active_challenge(self):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM stream_challenges WHERE status = 'active' ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None

    def create_challenge(self, challenge_type, description, target_val, reward_type, reward_amt):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("UPDATE stream_challenges SET status = 'expired' WHERE status = 'active'")
            now = datetime.now().isoformat()
            c.execute('''INSERT INTO stream_challenges (challenge_type, description, target_value, current_value, reward_type, reward_amount, status, created_at)
                         VALUES (?, ?, ?, 0, ?, ?, 'active', ?)''',
                      (challenge_type, description, target_val, reward_type, reward_amt, now))
            new_id = c.lastrowid
            conn.commit()
            conn.close()
            return new_id

    def update_challenge_progress(self, challenge_id, amount):
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM stream_challenges WHERE id = ?", (challenge_id,))
            row = c.fetchone()
            if not row or row['status'] != 'active':
                conn.close()
                return None
            
            new_value = row['current_value'] + amount
            status = 'active'
            if new_value >= row['target_value']:
                new_value = row['target_value']
                status = 'completed'
            
            c.execute("UPDATE stream_challenges SET current_value = ?, status = ? WHERE id = ?", (new_value, status, challenge_id))
            conn.commit()
            
            c.execute("SELECT * FROM stream_challenges WHERE id = ?", (challenge_id,))
            updated_row = dict(c.fetchone())
            conn.close()
            return updated_row

    def get_challenge_participants(self, since_iso):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT DISTINCT player_id FROM combat_log WHERE timestamp >= ?", (since_iso,))
        rows = c.fetchall()
        conn.close()
        return [row['player_id'] for row in rows]

    # NOTE: sell_items() has been moved to game/shop.py

db = SQLiteDatabase()

