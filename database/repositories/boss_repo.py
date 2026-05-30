"""
Boss repository — active boss CRUD with JSON field handling.
"""

import json
from datetime import datetime

from game.logic import get_boss_stars_for_avg_level
from .base import BaseRepository


class BossRepository(BaseRepository):
    _stars_cache = {}

    @classmethod
    def clear_stars_cache(cls):
        cls._stars_cache.clear()

    def __init__(self, lock):
        super().__init__(lock)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_active_boss(self):
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT * FROM bosses WHERE status = 'active' "
                "ORDER BY instance_id DESC LIMIT 1"
            )
            boss = c.fetchone()
            if not boss:
                return None

            boss = dict(boss)
            instance_id = boss['instance_id']
            boss['weakness'] = json.loads(boss['weakness']) if boss['weakness'] else []
            boss['resist'] = json.loads(boss['resist']) if boss['resist'] else []
            boss['participants'] = json.loads(boss['participants']) if boss['participants'] else []

            # Check cache
            if instance_id in self.__class__._stars_cache:
                boss['stars'] = self.__class__._stars_cache[instance_id]
                return boss

            # Compute stars based on average participant level
            participants = boss['participants']
            if participants:
                placeholders = ','.join('?' * len(participants))
                c.execute(
                    f"SELECT class_levels, class, level FROM players "
                    f"WHERE id IN ({placeholders})",
                    tuple(participants),
                )
                lvl_rows = c.fetchall()
                if lvl_rows:
                    total_lvl = 0
                    for r in lvl_rows:
                        try:
                            class_levels = json.loads(r.get('class_levels') or '{}')
                        except Exception:
                            class_levels = {}
                        cls_name = r.get('class', 'warrior').lower()
                        lvl = class_levels.get(cls_name, {}).get(
                            'level', r.get('level', 1)
                        )
                        total_lvl += lvl
                    avg_lvl = total_lvl / len(lvl_rows)
                else:
                    avg_lvl = 1
            else:
                avg_lvl = 1

            stars = get_boss_stars_for_avg_level(avg_lvl)

            self.__class__._stars_cache[instance_id] = stars
            boss['stars'] = stars

        return boss

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_active_boss(self, boss_data):
        with self._transact() as (conn, c):
            weakness = json.dumps(boss_data.get('weakness', []))
            resist = json.dumps(boss_data.get('resist', []))
            participants = json.dumps(boss_data.get('participants', []))
            now = datetime.now().isoformat()

            c.execute(
                '''INSERT INTO bosses
                   (boss_id, name, type, element, base_hp, base_def, current_hp,
                    max_hp, weakness, resist, image_url, participants, spawned_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
                (
                    boss_data.get('boss_id'), boss_data.get('name'),
                    boss_data.get('type'), boss_data.get('element'),
                    boss_data.get('base_hp'), boss_data.get('base_def', 0),
                    boss_data.get('current_hp'), boss_data.get('max_hp'),
                    weakness, resist, boss_data.get('image_url'),
                    participants, now,
                ),
            )
            boss_data['instance_id'] = c.lastrowid
            self.__class__.clear_stars_cache()

    def update_boss(self, instance_id, updates):
        if not updates:
            return self.get_active_boss()

        with self._transact() as (conn, c):
            update_data = dict(updates)
            if 'weakness' in update_data:
                update_data['weakness'] = json.dumps(update_data['weakness'])
            if 'resist' in update_data:
                update_data['resist'] = json.dumps(update_data['resist'])
            if 'participants' in update_data:
                update_data['participants'] = json.dumps(update_data['participants'])

            set_clause = ", ".join(f"{k} = ?" for k in update_data)
            values = list(update_data.values()) + [instance_id]
            c.execute(
                f"UPDATE bosses SET {set_clause} WHERE instance_id = ?",
                tuple(values),
            )

            # Check for defeat
            c.execute(
                "SELECT current_hp FROM bosses WHERE instance_id = ?",
                (instance_id,),
            )
            row = c.fetchone()
            if row and row['current_hp'] <= 0:
                now = datetime.now().isoformat()
                c.execute(
                    "UPDATE bosses SET status = 'defeated', defeated_at = ? "
                    "WHERE instance_id = ?",
                    (now, instance_id),
                )

        self.__class__._stars_cache.pop(instance_id, None)
        return self.get_active_boss()
