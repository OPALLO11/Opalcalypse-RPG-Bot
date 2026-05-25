"""
Combat log repository — batched writes + rankings/participant queries.
"""

import json
import queue
import threading
from datetime import datetime

from .base import BaseRepository
from ..connection import get_connection


class CombatLogRepository(BaseRepository):
    """
    Manages the combat_log table with a background batching thread
    for high-throughput log inserts.
    """

    def __init__(self, lock: threading.Lock):
        super().__init__(lock)
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._combat_log_worker, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_combat_log(self, boss_instance_id, player_id, action, damage, is_crit):
        """Queue a combat log entry for batched writing."""
        now = datetime.now().isoformat()
        self._queue.put((boss_instance_id, player_id, action, damage, is_crit, now))

    def get_boss_rankings(self, boss_instance_id):
        with self._read_only() as (conn, c):
            c.execute(
                '''SELECT player_id, SUM(damage) as total_damage
                   FROM combat_log
                   WHERE boss_instance_id = ?
                   GROUP BY player_id
                   ORDER BY total_damage DESC''',
                (boss_instance_id,),
            )
            rows = c.fetchall()

        return [
            {'id': row['player_id'], 'rank': idx + 1, 'damage': row['total_damage']}
            for idx, row in enumerate(rows)
        ]

    def get_challenge_participants(self, since_iso):
        """Return distinct player IDs that logged combat since *since_iso*."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT DISTINCT player_id FROM combat_log WHERE timestamp >= ?",
                (since_iso,),
            )
            return [row['player_id'] for row in c.fetchall()]

    def flush(self):
        """Force write all currently queued logs immediately in the caller thread."""
        items = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    items.append(item)
            except queue.Empty:
                break
        if items:
            self._write_batch(items)

    def shutdown(self):
        """Stop the background worker thread cleanly."""
        self._stop_event.set()
        self._queue.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _combat_log_worker(self):
        """Background thread that batches and writes combat logs every second."""
        while not self._stop_event.is_set():
            items = []
            try:
                item = self._queue.get(timeout=1.0)
                if item is None:
                    break
                items.append(item)
                while not self._queue.empty():
                    try:
                        item = self._queue.get_nowait()
                        if item is None:
                            break
                        items.append(item)
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

            if items:
                self._write_batch(items)

    def _write_batch(self, items):
        """Perform the actual database batch write operation."""
        healing_actions = ('heal', 'sanctuary', 'miracle')
        with self._lock:
            conn = get_connection()
            try:
                c = conn.cursor()
                conn.execute("BEGIN TRANSACTION")

                player_damage = {}
                boss_participants = {}
                log_entries = []

                for boss_instance_id, player_id, action, damage, is_crit, timestamp in items:
                    log_entries.append(
                        (boss_instance_id, player_id, action, damage, is_crit, timestamp)
                    )

                    is_healing = action.lower() in healing_actions
                    if not is_healing:
                        player_damage[player_id] = (
                            player_damage.get(player_id, 0) + damage
                        )

                    if boss_instance_id not in boss_participants:
                        boss_participants[boss_instance_id] = set()
                    boss_participants[boss_instance_id].add(player_id)

                # 1. Insert all combat logs
                c.executemany(
                    '''INSERT INTO combat_log
                       (boss_instance_id, player_id, action, damage, is_crit, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    log_entries,
                )

                # 2. Update players total damage
                for p_id, total_dmg in player_damage.items():
                    if total_dmg > 0:
                        c.execute(
                            "UPDATE players SET total_damage = total_damage + ? WHERE id = ?",
                            (total_dmg, p_id),
                        )

                # 3. Update boss participants
                for b_id, p_ids in boss_participants.items():
                    c.execute(
                        "SELECT participants FROM bosses WHERE instance_id = ?",
                        (b_id,),
                    )
                    boss_row = c.fetchone()
                    if boss_row:
                        current_parts = (
                            json.loads(boss_row['participants'])
                            if boss_row['participants']
                            else []
                        )
                        new_parts_added = False
                        for p_id in p_ids:
                            if p_id not in current_parts:
                                current_parts.append(p_id)
                                new_parts_added = True
                        if new_parts_added:
                            c.execute(
                                "UPDATE bosses SET participants = ? WHERE instance_id = ?",
                                (json.dumps(current_parts), b_id),
                            )

                conn.commit()
            except Exception as e:
                print(f"Error in batch logger: {e}")
                conn.rollback()
            finally:
                conn.close()
