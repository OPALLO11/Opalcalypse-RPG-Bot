import json
import queue
import threading
from datetime import datetime

from sqlalchemy import func
from .base import BaseRepository
from ..connection import SessionLocal
from ..models import CombatLog, Player, BossParticipant


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

    def add_combat_log(self, boss_instance_id, player_id, action, damage, is_crit):
        now = datetime.utcnow().isoformat()
        self._queue.put((boss_instance_id, player_id, action, damage, is_crit, now))

    def get_boss_rankings(self, boss_instance_id):
        with self._read_only() as session:
            rows = session.query(
                CombatLog.player_id,
                func.sum(CombatLog.damage).label('total_damage')
            ).filter(CombatLog.boss_instance_id == boss_instance_id) \
             .group_by(CombatLog.player_id) \
             .order_by(func.sum(CombatLog.damage).desc()) \
             .all()

        return [
            {'id': row.player_id, 'rank': idx + 1, 'damage': row.total_damage}
            for idx, row in enumerate(rows)
        ]

    def get_challenge_participants(self, since_iso):
        with self._read_only() as session:
            rows = session.query(CombatLog.player_id).filter(
                CombatLog.timestamp >= since_iso
            ).distinct().all()
            return [row.player_id for row in rows]

    def flush(self):
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
        self._stop_event.set()
        self._queue.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

    def _combat_log_worker(self):
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
        healing_actions = ('heal', 'sanctuary', 'miracle')
        with self._lock:
            session = SessionLocal()
            try:
                player_damage = {}
                boss_participants = {}
                log_entries = []

                for boss_instance_id, player_id, action, damage, is_crit, timestamp in items:
                    log_entries.append(
                        CombatLog(
                            boss_instance_id=boss_instance_id,
                            player_id=player_id,
                            action=action,
                            damage=damage,
                            is_crit=is_crit,
                            timestamp=timestamp
                        )
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
                session.add_all(log_entries)

                # 2. Update players total damage
                for p_id, total_dmg in player_damage.items():
                    if total_dmg > 0:
                        player = session.query(Player).filter_by(id=p_id).first()
                        if player:
                            player.total_damage += total_dmg

                # 3. Update boss participants (now with association table)
                for b_id, p_ids in boss_participants.items():
                    existing_bps = session.query(BossParticipant).filter_by(boss_instance_id=b_id).all()
                    existing_pids = {bp.player_id for bp in existing_bps}
                    
                    for p_id in p_ids:
                        if p_id not in existing_pids:
                            session.add(BossParticipant(boss_instance_id=b_id, player_id=p_id))

                session.commit()
            except Exception as e:
                print(f"Error in batch logger: {e}")
                session.rollback()
            finally:
                session.close()
