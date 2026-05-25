"""
Database package — drop-in replacement for the old ``database.py`` module.

Exports a ``db`` singleton that exposes the **exact same public API** as the
old ``SQLiteDatabase`` class, so every ``from database import db`` across
the codebase continues to work without modification.

Internally, work is delegated to domain-specific repositories under
``database.repositories``.
"""

import os
import threading

from .connection import get_connection, DATA_DIR  # noqa: re-export
from .migrations import run_migrations
from .repositories import (
    PlayerRepository,
    BossRepository,
    ItemRepository,
    CooldownRepository,
    CombatLogRepository,
    ChallengeRepository,
    ArtRepository,
)


class DatabaseManager:
    """
    Thin façade that wires up all repositories and exposes the legacy
    method names so callers don't need to change.
    """

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.lock = threading.Lock()

        # Run versioned migrations (replaces the old _init_db)
        run_migrations()

        # Repositories
        self.players = PlayerRepository(self.lock)
        self.bosses = BossRepository(self.lock)
        self.items = ItemRepository(self.lock)
        self.cooldowns = CooldownRepository(self.lock)
        self.combat_logs = CombatLogRepository(self.lock)
        self.challenges = ChallengeRepository(self.lock)
        self.art = ArtRepository(self.lock)

    def register_helpers(self, find_item_data, calculate_player_stats, get_required_exp):
        """Inject helper callbacks to break circular imports between db and game logic."""
        self.players.register_helpers(find_item_data, calculate_player_stats, get_required_exp)

    # ------------------------------------------------------------------
    # Legacy API — delegates straight to the appropriate repository.
    # Every method below existed on the old SQLiteDatabase class.
    # ------------------------------------------------------------------

    # Connection (kept for callers that still need a raw connection)
    def get_connection(self):
        return get_connection()

    # Player
    def get_player(self, username):
        return self.players.get_player(username)

    def get_player_by_id(self, player_id):
        return self.players.get_player_by_id(player_id)

    def create_player(self, username, twitch_id, character_name, class_name="warrior"):
        return self.players.create_player(username, twitch_id, character_name, class_name)

    def update_player(self, player_id, updates):
        return self.players.update_player(player_id, updates)

    def update_player_hp(self, player_id, new_hp):
        return self.players.update_player_hp(player_id, new_hp)

    def add_player_gold(self, player_id, amount):
        return self.players.add_player_gold(player_id, amount)

    def reset_rename_limits(self):
        return self.players.reset_rename_limits()

    def get_player_equipment(self, player_id):
        return self.players.get_player_equipment(player_id)

    # Boss
    def get_active_boss(self):
        return self.bosses.get_active_boss()

    def set_active_boss(self, boss_data):
        return self.bosses.set_active_boss(boss_data)

    def update_boss(self, instance_id, updates):
        return self.bosses.update_boss(instance_id, updates)

    # Items
    def add_item(self, owner_id, item_data, boss_name=""):
        return self.items.add_item(owner_id, item_data, boss_name)

    # Cooldowns
    def get_cooldown(self, player_id, action):
        return self.cooldowns.get_cooldown(player_id, action)

    def set_cooldown(self, player_id, action, expires_at_iso):
        return self.cooldowns.set_cooldown(player_id, action, expires_at_iso)

    def clear_cooldown(self, player_id, action):
        return self.cooldowns.clear_cooldown(player_id, action)

    # Combat logs
    def add_combat_log(self, boss_instance_id, player_id, action, damage, is_crit):
        return self.combat_logs.add_combat_log(
            boss_instance_id, player_id, action, damage, is_crit
        )

    def get_boss_rankings(self, boss_instance_id):
        return self.combat_logs.get_boss_rankings(boss_instance_id)

    def get_challenge_participants(self, since_iso):
        return self.combat_logs.get_challenge_participants(since_iso)

    # Challenges
    def get_active_challenge(self):
        return self.challenges.get_active_challenge()

    def create_challenge(self, challenge_type, description, target_val,
                         reward_type, reward_amt):
        return self.challenges.create_challenge(
            challenge_type, description, target_val, reward_type, reward_amt
        )

    def update_challenge_progress(self, challenge_id, amount):
        return self.challenges.update_challenge_progress(challenge_id, amount)

    # Art gallery
    def add_art_gallery(self, username, bits_amount, prompt, image_url,
                        is_custom, discord_posted):
        return self.art.add_art_gallery(
            username, bits_amount, prompt, image_url, is_custom, discord_posted
        )


# ---------------------------------------------------------------------------
# Module-level singleton — exact same pattern as the old ``database.py``.
# ---------------------------------------------------------------------------
db = DatabaseManager()
