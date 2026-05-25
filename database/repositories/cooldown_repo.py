"""
Cooldown repository — CRUD for per-player action cooldowns.
"""

from .base import BaseRepository


class CooldownRepository(BaseRepository):

    def get_cooldown(self, player_id, action):
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT expires_at FROM cooldowns WHERE player_id = ? AND action = ?",
                (player_id, action),
            )
            row = c.fetchone()
            return row['expires_at'] if row else None

    def set_cooldown(self, player_id, action, expires_at_iso):
        with self._transact() as (conn, c):
            c.execute(
                '''INSERT INTO cooldowns (player_id, action, expires_at)
                   VALUES (?, ?, ?) ON CONFLICT(player_id, action)
                   DO
                UPDATE SET expires_at=excluded.expires_at''',
                (player_id, action, expires_at_iso),
            )

    def clear_cooldown(self, player_id, action):
        with self._transact() as (conn, c):
            c.execute(
                "DELETE FROM cooldowns WHERE player_id = ? AND action = ?",
                (player_id, action),
            )

    def get_all_respawn_cooldowns(self):
        """Return all active respawn cooldowns (used for revive logic)."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT player_id, expires_at FROM cooldowns WHERE action = 'respawn'"
            )
            return c.fetchall()
