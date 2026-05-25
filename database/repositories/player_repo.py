"""
Player repository — all player CRUD, hydration, gold, EXP, and equipment queries.
"""

import json
import os
from datetime import datetime

from .base import BaseRepository

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')


class PlayerRepository(BaseRepository):

    def __init__(self, lock):
        super().__init__(lock)
        self._find_item_data = None
        self._calculate_player_stats = None
        self._get_required_exp = None

    def register_helpers(self, find_item_data, calculate_player_stats, get_required_exp):
        self._find_item_data = find_item_data
        self._calculate_player_stats = calculate_player_stats
        self._get_required_exp = get_required_exp

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

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
            if not self._calculate_player_stats:
                try:
                    from game.logic import calculate_player_stats
                    self._calculate_player_stats = calculate_player_stats
                except ImportError:
                    pass
            if self._calculate_player_stats:
                s = self._calculate_player_stats(p)
                if p['hp'] > s['max_hp']:
                    p['hp'] = s['max_hp']
                if p['mp'] > s['max_mp']:
                    p['mp'] = s['max_mp']
        except Exception as e:
            print(f"Error capping player HP/MP: {e}")

        return p

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_player(self, username):
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT * FROM players WHERE username = ? OR character_name = ? COLLATE NOCASE",
                (username.lower(), username.lower()),
            )
            return self._hydrate_player(c.fetchone())

    def get_player_by_id(self, player_id):
        with self._read_only() as (conn, c):
            c.execute("SELECT * FROM players WHERE id = ?", (player_id,))
            return self._hydrate_player(c.fetchone())

    def get_all_players(self):
        """Return every player row (hydrated)."""
        with self._read_only() as (conn, c):
            c.execute("SELECT * FROM players")
            return [self._hydrate_player(row) for row in c.fetchall()]

    def get_player_basic(self, player_id, columns="username, character_name"):
        """Lightweight lookup returning only the requested columns."""
        with self._read_only() as (conn, c):
            c.execute(f"SELECT {columns} FROM players WHERE id = ?", (player_id,))
            row = c.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_player(self, username, twitch_id, character_name, class_name="warrior"):
        with self._transact() as (conn, c):
            c.execute(
                "SELECT id FROM players WHERE username = ? OR twitch_id = ?",
                (username.lower(), str(twitch_id)),
            )
            if c.fetchone():
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
                    passive = cls_info.get('passive', {})
                    initial_mp += passive.get('bonus_mp', 0)
            except Exception as e:
                print(f"Error loading classes.json in create_player: {e}")

            now = datetime.now().isoformat()
            initial_levels = json.dumps({class_name: {"level": 1, "exp": 0}})
            c.execute(
                '''INSERT INTO players
                   (username, twitch_id, character_name, class, class_levels,
                    hp, mp, created_at, session_renamed, session_class_changed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)''',
                (username.lower(), str(twitch_id), character_name,
                 class_name, initial_levels, initial_hp, initial_mp, now),
            )
            return True

    def update_player(self, player_id, updates):
        if not updates:
            return False
        if 'level' in updates or 'class_levels' in updates:
            try:
                from .boss_repo import BossRepository
                BossRepository.clear_stars_cache()
            except Exception:
                pass
        with self._transact() as (conn, c):
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [player_id]
            c.execute(f"UPDATE players SET {set_clause} WHERE id = ?", tuple(values))
            return c.rowcount > 0

    def update_player_hp(self, player_id, new_hp):
        return self.update_player(player_id, {"hp": new_hp})

    def add_player_gold(self, player_id, amount):
        with self._transact() as (conn, c):
            c.execute("UPDATE players SET gold = gold + ? WHERE id = ?", (amount, player_id))

    def reset_rename_limits(self):
        with self._transact() as (conn, c):
            c.execute("UPDATE players SET session_renamed = 0, session_class_changed = 0")

    # ------------------------------------------------------------------
    # Equipment queries
    # ------------------------------------------------------------------

    def get_player_equipment(self, player_id):
        """Return equipment details for each slot, enriched with item name/tier."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT equipped_weapon, equipped_armor, equipped_accessory "
                "FROM players WHERE id = ?",
                (player_id,),
            )
            p = c.fetchone()
            if not p:
                return {}

            eq = {}
            for slot in ['equipped_weapon', 'equipped_armor', 'equipped_accessory']:
                item_db_id = p[slot]
                if item_db_id:
                    c.execute(
                        "SELECT id, item_id, enhancement_level FROM items WHERE id = ?",
                        (item_db_id,),
                    )
                    item = c.fetchone()
                    if item:
                        item = dict(item)
                        if not self._find_item_data:
                            try:
                                from game.helpers import find_item_data
                                self._find_item_data = find_item_data
                            except ImportError:
                                pass
                        if self._find_item_data:
                            item_data, tier = self._find_item_data(item['item_id'])
                        else:
                            item_data, tier = None, 'R'
                        item['name'] = item_data['name'] if item_data else item['item_id']
                        item['tier'] = tier or 'R'
                        eq[slot] = item
                    else:
                        eq[slot] = None
                else:
                    eq[slot] = None
        return eq

    def get_equipped_item_rows(self, equipped_ids):
        """
        Given a list of item DB IDs, return their item_id + enhancement_level.
        Used by calculate_player_stats to compute bonuses.
        """
        if not equipped_ids:
            return []
        with self._read_only() as (conn, c):
            placeholders = ','.join('?' * len(equipped_ids))
            c.execute(
                f"SELECT item_id, enhancement_level FROM items "
                f"WHERE id IN ({placeholders})",
                tuple(equipped_ids),
            )
            return c.fetchall()

    # ------------------------------------------------------------------
    # EXP / leveling  (absorbed from game/logic.py)
    # ------------------------------------------------------------------

    def add_exp(self, player_id, amount):
        """
        Add EXP to a player's current class. Handles level-ups (max +1 per call)
        and updates HP/MP to new max on level up.

        Returns a dict with level_up info, or None if the player doesn't exist.
        """
        with self._transact() as (conn, c):
            c.execute(
                "SELECT username, character_name, class, class_levels, level "
                "FROM players WHERE id = ?",
                (player_id,),
            )
            row = c.fetchone()
            if not row:
                return None

            player = dict(row)
            cls_name = player.get('class', 'warrior').lower()

            class_levels = player.get('class_levels', '{}')
            if isinstance(class_levels, str):
                try:
                    class_levels = json.loads(class_levels)
                except Exception:
                    class_levels = {}

            current_class_data = class_levels.get(
                cls_name, {'level': player.get('level', 1), 'exp': 0}
            )
            level = current_class_data.get('level', 1)
            exp = current_class_data.get('exp', 0)

            exp += amount
            level_up = False
            old_level = level
            max_level_allowed = old_level + 1

            if not self._get_required_exp:
                try:
                    from game.logic import get_required_exp
                    self._get_required_exp = get_required_exp
                except ImportError:
                    pass
            req_exp = self._get_required_exp(level) if self._get_required_exp else (level * 200 + level ** 2 * 50)
            while exp >= req_exp:
                if level >= max_level_allowed:
                    exp = req_exp - 1
                    break
                exp -= req_exp
                level += 1
                level_up = True
                req_exp = self._get_required_exp(level) if self._get_required_exp else (level * 200 + level ** 2 * 50)

            current_class_data['level'] = level
            current_class_data['exp'] = exp
            class_levels[cls_name] = current_class_data

            if level_up:
                try:
                    from .boss_repo import BossRepository
                    BossRepository.clear_stars_cache()
                except Exception:
                    pass
                player_for_stats = player.copy()
                player_for_stats['class_levels'] = json.dumps(class_levels)
                player_for_stats['level'] = level
                if not self._calculate_player_stats:
                    try:
                        from game.logic import calculate_player_stats
                        self._calculate_player_stats = calculate_player_stats
                    except ImportError:
                        pass
                if self._calculate_player_stats:
                    s = self._calculate_player_stats(player_for_stats)
                    max_hp, max_mp = s['max_hp'], s['max_mp']
                else:
                    max_hp, max_mp = 1000, 50
                c.execute(
                    "UPDATE players SET class_levels = ?, hp = ?, mp = ? WHERE id = ?",
                    (json.dumps(class_levels), max_hp, max_mp, player_id),
                )
            else:
                c.execute(
                    "UPDATE players SET class_levels = ? WHERE id = ?",
                    (json.dumps(class_levels), player_id),
                )

            return {
                "level_up": level_up,
                "old_level": old_level,
                "new_level": level,
                "class": cls_name,
                "username": player['username'],
                "character_name": player['character_name'] or player['username'],
            }

    # ------------------------------------------------------------------
    # Batch helpers used by regen_loop (bot.py)
    # ------------------------------------------------------------------

    def batch_regen_update(self, player_updates):
        """
        Apply a list of ``(player_id, {col: val})`` updates in a single transaction.
        """
        if not player_updates:
            return
        with self._transact() as (conn, c):
            for pid, updates in player_updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [pid]
                c.execute(
                    f"UPDATE players SET {set_clause} WHERE id = ?",
                    tuple(values),
                )
