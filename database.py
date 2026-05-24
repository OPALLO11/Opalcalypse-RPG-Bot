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

    def get_player(self, username):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE username = ? OR LOWER(character_name) = ?", (username.lower(), username.lower()))
        row = c.fetchone()
        conn.close()
        if row:
            p = dict(row)
            try:
                p['class_levels'] = json.loads(p.get('class_levels') or '{}')
            except:
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
                print(f"Error capping player HP/MP in get_player: {e}")

            return p
        return None

    def get_player_by_id(self, player_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE id = ?", (player_id,))
        row = c.fetchone()
        conn.close()
        if row:
            p = dict(row)
            try:
                p['class_levels'] = json.loads(p.get('class_levels') or '{}')
            except:
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
                print(f"Error capping player HP/MP in get_player_by_id: {e}")

            return p
        return None

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

    def give_item_or_enhance(self, owner_id, item_data, boss_name=""):
        item_id = item_data.get('id', 'unknown') if isinstance(item_data, dict) else str(item_data)
        item_tier = item_data.get('tier', 'R') if isinstance(item_data, dict) else 'R'
        
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, enhancement_level FROM items WHERE owner_id = ? AND item_id = ?", (owner_id, item_id))
        existing = c.fetchone()
        conn.close()
        
        if existing:
            current_enh = existing['enhancement_level'] or 0
            if current_enh >= 9:
                # Maxed out, give EXP instead
                from game.logic import add_exp
                add_exp(owner_id, 500)
                return {"action": "converted_exp", "amount": 500, "item_id": item_id, "enhancement_level": 9}
                
            target_enh = current_enh + 1
            broke = False
            success = True
            
            # Base success rates for +7, +8, +9
            base_rates = {7: 0.60, 8: 0.40, 9: 0.20}
            
            with self.lock:
                conn = self.get_connection()
                
                scroll_consumed = False
                prevent_break = False
                success_bonus = 0.0
                required_scroll = None
                
                if target_enh >= 7:
                    c_scroll = conn.cursor()
                    c_scroll.execute("SELECT scroll_t1, scroll_t2, scroll_t3 FROM players WHERE id = ?", (owner_id,))
                    p_row = c_scroll.fetchone()
                    
                    if p_row:
                        if item_tier in ['R', 'SR']:
                            required_scroll = 'scroll_t1'
                        elif item_tier == 'SSR':
                            required_scroll = 'scroll_t2'
                        elif item_tier == 'UR':
                            required_scroll = 'scroll_t3'
                            
                        if required_scroll and p_row[required_scroll] > 0:
                            # Consume the scroll
                            scroll_consumed = True
                            conn.execute(f"UPDATE players SET {required_scroll} = {required_scroll} - 1 WHERE id = ?", (owner_id,))
                            
                            if required_scroll == 'scroll_t1':
                                # 75% chance to prevent break
                                if random.random() < 0.75: prevent_break = True
                            elif required_scroll == 'scroll_t2':
                                prevent_break = True
                                success_bonus = 0.10
                            elif required_scroll == 'scroll_t3':
                                prevent_break = True
                                success_bonus = 0.25
                                
                    # Roll for success
                    final_success_rate = base_rates.get(target_enh, 1.0) + success_bonus
                    if random.random() > final_success_rate:
                        success = False
                        if not prevent_break:
                            broke = True
                            
                if success:
                    conn.execute("UPDATE items SET enhancement_level = ? WHERE id = ?", (target_enh, existing['id']))
                    conn.commit()
                    conn.close()
                    return {"action": "enhanced", "item_id": item_id, "new_level": target_enh}
                elif scroll_consumed and not broke:
                    conn.commit()
                    conn.close()
                    return {"action": "failed_protected", "item_id": item_id, "attempted_level": target_enh}
                elif broke:
                    conn.execute("DELETE FROM items WHERE id = ?", (existing['id'],))
                    
                    # Unequip if currently equipped
                    c_eq = conn.cursor()
                    c_eq.execute("UPDATE players SET equipped_weapon = NULL WHERE id = ? AND equipped_weapon = ?", (owner_id, existing['id']))
                    c_eq.execute("UPDATE players SET equipped_armor = NULL WHERE id = ? AND equipped_armor = ?", (owner_id, existing['id']))
                    c_eq.execute("UPDATE players SET equipped_accessory = NULL WHERE id = ? AND equipped_accessory = ?", (owner_id, existing['id']))
                    
                    conn.commit()
                    conn.close()
                    return {"action": "broke", "item_id": item_id, "attempted_level": target_enh}
                else:
                    # Should only happen if it fails but wasn't going to break anyway (e.g. < 7? No, all < 7 are 100% success right now since base_rates.get is 1.0)
                    conn.commit()
                    conn.close()
                    return {"action": "failed", "item_id": item_id, "attempted_level": target_enh}
        else:
            new_doc = self.add_item(owner_id, item_data, boss_name)
            new_doc["action"] = "new"
            return new_doc

    def get_active_boss(self):
        conn = self.get_connection()
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
                        except:
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

    def buy_shop_item(self, username, item_name):
        item_name = item_name.lower().strip()
        
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute("SELECT id, gold, level, class, class_levels FROM players WHERE username = ?", (username.lower(),))
            row = c.fetchone()
            if not row:
                conn.close()
                return False, "You need to !register first."
                
            player = dict(row)
            try:
                class_levels = json.loads(player.get('class_levels') or '{}')
                cls_name = player.get('class', 'warrior').lower()
                lvl = class_levels.get(cls_name, {}).get('level', player.get('level', 1))
            except:
                lvl = player.get('level', 1)
                
            costs = {
                "potion": 500,
                "scroll_t1": 10000,
                "scroll_t2": 50000,
                "scroll_t3": 100000
            }
            
            if item_name not in costs:
                conn.close()
                return False, "Item not found in shop. Available: Potion, scroll_t1, scroll_t2, scroll_t3"
                
            if item_name.startswith("scroll") and lvl < 11:
                conn.close()
                return False, "ใบกันแตกซื้อได้เมื่อเลเวล 11 ขึ้นไปครับ"
            
            cost = costs[item_name]
            
            if player["gold"] < cost:
                conn.close()
                return False, f"Not enough gold. Costs {cost}G, you have {player['gold']}G."
                
            new_gold = player["gold"] - cost
            if item_name == "scroll_t1":
                c.execute("UPDATE players SET gold = ?, scroll_t1 = scroll_t1 + 1 WHERE id = ?", (new_gold, player["id"]))
                msg = f"Successfully bought 1 Basic Scroll! (Remaining Gold: {new_gold}G)"
            elif item_name == "scroll_t2":
                c.execute("UPDATE players SET gold = ?, scroll_t2 = scroll_t2 + 1 WHERE id = ?", (new_gold, player["id"]))
                msg = f"Successfully bought 1 Blessed Scroll! (Remaining Gold: {new_gold}G)"
            elif item_name == "scroll_t3":
                c.execute("UPDATE players SET gold = ?, scroll_t3 = scroll_t3 + 1 WHERE id = ?", (new_gold, player["id"]))
                msg = f"Successfully bought 1 Divine Scroll! (Remaining Gold: {new_gold}G)"
            elif item_name == "potion":
                full_p = self.get_player_by_id(player["id"])
                from game.logic import calculate_player_stats
                stats = calculate_player_stats(full_p)
                new_hp = stats["max_hp"]
                new_mp = stats["max_mp"]
                c.execute("UPDATE players SET gold = ?, hp = ?, mp = ? WHERE id = ?", (new_gold, new_hp, new_mp, player["id"]))
                msg = f"Successfully bought and consumed Potion! Restored to Max HP/MP! (Remaining Gold: {new_gold}G)"
            
            conn.commit()
            conn.close()
            return True, msg

    def get_player_equipment(self, player_id):
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT equipped_weapon, equipped_armor, equipped_accessory FROM players WHERE id = ?", (player_id,))
        p = c.fetchone()
        if not p:
            conn.close()
            return {}
            
        eq = {}
        for slot in ['equipped_weapon', 'equipped_armor', 'equipped_accessory']:
            item_db_id = p[slot]
            if item_db_id:
                c.execute("SELECT id, item_id, enhancement_level FROM items WHERE id = ?", (item_db_id,))
                item = c.fetchone()
                if item:
                    item = dict(item)
                    # Find user-friendly name from logic.ITEMS
                    from game.logic import ITEMS
                    item_id = item['item_id']
                    name = item_id
                    tier = "R"
                    for cat in ITEMS.values():
                        for tier_name, tier_items in cat.items():
                            for itm in tier_items:
                                if itm['id'] == item_id:
                                    name = itm['name']
                                    tier = tier_name
                                    break
                    item['name'] = name
                    item['tier'] = tier
                    eq[slot] = item
                else:
                    eq[slot] = None
            else:
                eq[slot] = None
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

    def sell_items(self, owner_id, target_item_name=None, target_tier=None):
        import json
        import os
        items_path = os.path.join(os.path.dirname(__file__), 'data', 'items.json')
        try:
            with open(items_path, 'r', encoding='utf-8') as f:
                ITEMS = json.load(f)
        except:
            ITEMS = {}
            
        with self.lock:
            conn = self.get_connection()
            c = conn.cursor()
            
            c.execute("SELECT equipped_weapon, equipped_armor, equipped_accessory FROM players WHERE id = ?", (owner_id,))
            p_row = c.fetchone()
            if not p_row:
                conn.close()
                return False, "Player not found."
                
            equipped_ids = [p_row['equipped_weapon'], p_row['equipped_armor'], p_row['equipped_accessory']]
            equipped_ids = [eid for eid in equipped_ids if eid]
            
            base_prices = {"R": 100, "SR": 500, "SSR": 2500, "UR": 10000}
            
            c.execute("SELECT id, item_id, enhancement_level FROM items WHERE owner_id = ?", (owner_id,))
            owned_items = c.fetchall()
            
            items_to_sell = []
            
            def get_item_data(i_id):
                for cat in ITEMS.values():
                    for t_items in cat.values():
                        for itm in t_items:
                            if itm['id'] == i_id:
                                return itm
                return None
                
            if target_item_name:
                search_name = target_item_name.lower()
                candidates = []
                for row in owned_items:
                    if row['id'] in equipped_ids: continue
                    i_data = get_item_data(row['item_id'])
                    if not i_data: continue
                    
                    if search_name == i_data['name'].lower() or search_name == str(row['id']):
                        candidates.append((row, i_data))
                        
                if not candidates:
                    conn.close()
                    return False, f"ไม่พบไอเทม '{target_item_name}' ที่ยังไม่ได้สวมใส่ครับ (ถ้าใส่อยู่ต้องถอดก่อน)"
                    
                candidates.sort(key=lambda x: x[0]['enhancement_level'] or 0)
                items_to_sell.append(candidates[0])
                
            elif target_tier:
                target_t = target_tier.upper()
                if target_t not in ['R', 'SR']:
                    conn.close()
                    return False, "ระบบอนุญาตให้ขายเหมาเฉพาะเกรด R และ SR เท่านั้นครับ เพื่อป้องกันการเผลอขายของแรร์ทิ้ง"
                    
                for row in owned_items:
                    if row['id'] in equipped_ids: continue
                    i_data = get_item_data(row['item_id'])
                    if not i_data: continue
                    
                    if i_data.get('tier', 'R') == target_t:
                        items_to_sell.append((row, i_data))
                        
                if not items_to_sell:
                    conn.close()
                    return False, f"ไม่พบไอเทมเกรด {target_t} ที่ไม่ได้สวมใส่ในตัวคุณครับ"
                    
            if not items_to_sell:
                conn.close()
                return False, "ไม่มีไอเทมที่สามารถขายได้"
                
            total_gold = 0
            ids_to_delete = []
            
            for row, i_data in items_to_sell:
                tier = i_data.get('tier', 'R')
                base_price = base_prices.get(tier, 100)
                enh_lvl = row['enhancement_level'] or 0
                price = int(base_price * (1 + (enh_lvl * 0.5)))
                
                total_gold += price
                ids_to_delete.append(row['id'])
                
            placeholders = ','.join('?' * len(ids_to_delete))
            c.execute(f"DELETE FROM items WHERE id IN ({placeholders})", tuple(ids_to_delete))
            c.execute("UPDATE players SET gold = gold + ? WHERE id = ?", (total_gold, owner_id))
            
            conn.commit()
            conn.close()
            
            count = len(items_to_sell)
            if target_item_name:
                item_name = items_to_sell[0][1]['name']
                enh = items_to_sell[0][0]['enhancement_level'] or 0
                enh_str = f"+{enh} " if enh > 0 else ""
                return True, f"ขาย {enh_str}{item_name} สำเร็จ! ได้รับเงิน {total_gold} Gold 💰"
            else:
                return True, f"ขายเหมาไอเทมเกรด {target_tier.upper()} จำนวน {count} ชิ้น สำเร็จ! ได้รับเงินทั้งหมด {total_gold} Gold 💰"

db = SQLiteDatabase()

