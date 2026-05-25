"""
Challenge repository — stream challenge CRUD.
"""

from datetime import datetime
from .base import BaseRepository


class ChallengeRepository(BaseRepository):

    def get_active_challenge(self):
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT * FROM stream_challenges "
                "WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            )
            row = c.fetchone()
            return dict(row) if row else None

    def create_challenge(self, challenge_type, description, target_val,
                         reward_type, reward_amt):
        with self._transact() as (conn, c):
            # Expire any existing active challenge
            c.execute(
                "UPDATE stream_challenges SET status = 'expired' "
                "WHERE status = 'active'"
            )
            now = datetime.now().isoformat()
            c.execute(
                '''INSERT INTO stream_challenges
                   (challenge_type, description, target_value, current_value,
                    reward_type, reward_amount, status, created_at)
                   VALUES (?, ?, ?, 0, ?, ?, 'active', ?)''',
                (challenge_type, description, target_val,
                 reward_type, reward_amt, now),
            )
            return c.lastrowid

    def update_challenge_progress(self, challenge_id, amount):
        with self._transact() as (conn, c):
            c.execute(
                "SELECT * FROM stream_challenges WHERE id = ?",
                (challenge_id,),
            )
            row = c.fetchone()
            if not row or row['status'] != 'active':
                return None

            new_value = row['current_value'] + amount
            status = 'active'
            if new_value >= row['target_value']:
                new_value = row['target_value']
                status = 'completed'

            c.execute(
                "UPDATE stream_challenges SET current_value = ?, status = ? "
                "WHERE id = ?",
                (new_value, status, challenge_id),
            )

            c.execute(
                "SELECT * FROM stream_challenges WHERE id = ?",
                (challenge_id,),
            )
            return dict(c.fetchone())
