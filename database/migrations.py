"""
Versioned schema migrations.

Each migration function receives a cursor and runs the DDL/DML needed
to bring the schema from the previous version to the current one.
On startup, `run_migrations()` applies any outstanding migrations and
updates the `schema_version` table.
"""

from .connection import get_connection


# ---------------------------------------------------------------------------
# Migration definitions — append new migrations to the end of this list.
# ---------------------------------------------------------------------------

def _v1_initial_schema(c):
    """Consolidates all original CREATE TABLE + ALTER TABLE statements."""

    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT
                     UNIQUE
                     NOT
                     NULL,
                     twitch_id
                     TEXT,
                     character_name
                     TEXT,
                     class
                     TEXT
                     DEFAULT
                     'warrior',
                     class_levels
                     TEXT
                     DEFAULT
                     '{}',
                     level
                     INTEGER
                     DEFAULT
                     1,
                     exp
                     INTEGER
                     DEFAULT
                     0,
                     hp
                     INTEGER
                     DEFAULT
                     1000,
                     max_hp
                     INTEGER
                     DEFAULT
                     1000,
                     mp
                     INTEGER
                     DEFAULT
                     50,
                     max_mp
                     INTEGER
                     DEFAULT
                     50,
                     atk
                     INTEGER
                     DEFAULT
                     100,
                     def
                     INTEGER
                     DEFAULT
                     30,
                     equipped_weapon
                     INTEGER,
                     equipped_armor
                     INTEGER,
                     equipped_accessory
                     INTEGER,
                     total_damage
                     INTEGER
                     DEFAULT
                     0,
                     bosses_defeated
                     INTEGER
                     DEFAULT
                     0,
                     mvp_count
                     INTEGER
                     DEFAULT
                     0,
                     session_renamed
                     BOOLEAN
                     DEFAULT
                     0,
                     session_class_changed
                     BOOLEAN
                     DEFAULT
                     0,
                     gold
                     INTEGER
                     DEFAULT
                     0,
                     protection_scrolls
                     INTEGER
                     DEFAULT
                     0,
                     scroll_t1
                     INTEGER
                     DEFAULT
                     0,
                     scroll_t2
                     INTEGER
                     DEFAULT
                     0,
                     scroll_t3
                     INTEGER
                     DEFAULT
                     0,
                     created_at
                     TEXT
                 )''')

    c.execute('''CREATE TABLE IF NOT EXISTS items
    (
        id
        INTEGER
        PRIMARY
        KEY
        AUTOINCREMENT,
        owner_id
        INTEGER,
        item_id
        TEXT,
        obtained_from
        TEXT,
        obtained_at
        TEXT,
        enhancement_level
        INTEGER
        DEFAULT
        0,
        FOREIGN
        KEY
                 (
        owner_id
                 ) REFERENCES players
                 (
                     id
                 )
        )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bosses
                 (
                     instance_id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     boss_id
                     TEXT,
                     name
                     TEXT,
                     type
                     TEXT,
                     element
                     TEXT,
                     base_hp
                     INTEGER,
                     base_def
                     INTEGER
                     DEFAULT
                     0,
                     current_hp
                     INTEGER,
                     max_hp
                     INTEGER,
                     weakness
                     TEXT,
                     resist
                     TEXT,
                     image_url
                     TEXT,
                     participants
                     TEXT
                     DEFAULT
                     '[]',
                     spawned_at
                     TEXT,
                     status
                     TEXT
                     DEFAULT
                     'active',
                     defeated_at
                     TEXT
                 )''')

    c.execute('''CREATE TABLE IF NOT EXISTS cooldowns
    (
        player_id
        INTEGER,
        action
        TEXT,
        expires_at
        TEXT,
        PRIMARY
        KEY
                 (
        player_id,
        action
                 )
        )''')

    c.execute('''CREATE TABLE IF NOT EXISTS combat_log
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     boss_instance_id
                     INTEGER,
                     player_id
                     INTEGER,
                     action
                     TEXT,
                     damage
                     INTEGER,
                     is_crit
                     BOOLEAN,
                     timestamp
                     TEXT
                 )''')

    c.execute('''CREATE TABLE IF NOT EXISTS art_gallery
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT,
                     bits_amount
                     INTEGER,
                     prompt
                     TEXT,
                     image_url
                     TEXT,
                     is_custom
                     BOOLEAN,
                     discord_posted
                     BOOLEAN,
                     created_at
                     TEXT
                 )''')

    c.execute('''CREATE TABLE IF NOT EXISTS stream_challenges
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     challenge_type
                     TEXT,
                     description
                     TEXT,
                     target_value
                     INTEGER,
                     current_value
                     INTEGER
                     DEFAULT
                     0,
                     reward_type
                     TEXT,
                     reward_amount
                     INTEGER,
                     status
                     TEXT
                     DEFAULT
                     'active',
                     created_at
                     TEXT
                 )''')

    # Migrate legacy protection_scrolls → scroll_t1
    try:
        c.execute(
            "UPDATE players SET scroll_t1 = scroll_t1 + protection_scrolls, "
            "protection_scrolls = 0 WHERE protection_scrolls > 0"
        )
    except Exception:
        pass


def _v2_add_character_name_index(c):
    """Add a case-insensitive index on character_name for faster player lookups."""
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_players_character_name_nocase "
        "ON players(character_name COLLATE NOCASE);"
    )


# Ordered list — index == version number (0-based internally, stored 1-based).
MIGRATIONS = [
    _v1_initial_schema,
    _v2_add_character_name_index,
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_migrations():
    """Apply any pending migrations and update schema_version."""
    conn = get_connection()
    try:
        c = conn.cursor()

        # Ensure the version tracking table exists.
        c.execute('''CREATE TABLE IF NOT EXISTS schema_version
                     (
                         version
                         INTEGER
                         NOT
                         NULL
                         DEFAULT
                         0
                     )''')
        c.execute("SELECT version FROM schema_version")
        row = c.fetchone()
        if row is None:
            c.execute("INSERT INTO schema_version (version) VALUES (0)")
            current_version = 0
        else:
            current_version = row['version']

        target_version = len(MIGRATIONS)

        if current_version < target_version:
            for idx in range(current_version, target_version):
                print(f"[DB Migration] Applying migration v{idx + 1} …")
                MIGRATIONS[idx](c)

            c.execute(
                "UPDATE schema_version SET version = ?", (target_version,)
            )
            conn.commit()
            print(f"[DB Migration] Schema is now at version {target_version}.")
        else:
            print(f"[DB Migration] Schema is up to date (v{current_version}).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
