"""
Item repository — item CRUD, ownership queries, enhancement helpers.
"""

from datetime import datetime
from .base import BaseRepository


class ItemRepository(BaseRepository):

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_items_by_owner(self, owner_id):
        """Return all items owned by a player."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT id, item_id, enhancement_level FROM items WHERE owner_id = ?",
                (owner_id,),
            )
            return c.fetchall()

    def get_item_by_db_id(self, item_db_id):
        """Fetch a single item row by its database PK."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT id, item_id, enhancement_level, owner_id "
                "FROM items WHERE id = ?",
                (item_db_id,),
            )
            row = c.fetchone()
            return dict(row) if row else None

    def find_existing_item(self, owner_id, item_id):
        """Check if a player already owns a specific item_id."""
        with self._read_only() as (conn, c):
            c.execute(
                "SELECT id, enhancement_level FROM items "
                "WHERE owner_id = ? AND item_id = ?",
                (owner_id, item_id),
            )
            return c.fetchone()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_item(self, owner_id, item_data, boss_name=""):
        item_id = (
            item_data.get('id', 'unknown')
            if isinstance(item_data, dict)
            else str(item_data)
        )
        with self._transact() as (conn, c):
            now = datetime.now().isoformat()
            c.execute(
                '''INSERT INTO items
                   (owner_id, item_id, obtained_from, obtained_at, enhancement_level)
                   VALUES (?, ?, ?, ?, 0)''',
                (owner_id, item_id, boss_name, now),
            )
            new_id = c.lastrowid
            return {
                "id": new_id,
                "owner_id": owner_id,
                "item_id": item_id,
                "obtained_from": boss_name,
                "obtained_at": now,
                "enhancement_level": 0,
            }

    def update_enhancement(self, item_db_id, new_level):
        """Set the enhancement level on an item."""
        with self._transact() as (conn, c):
            c.execute(
                "UPDATE items SET enhancement_level = ? WHERE id = ?",
                (new_level, item_db_id),
            )

    def delete_item(self, item_db_id):
        """Delete a single item by its DB id."""
        with self._transact() as (conn, c):
            c.execute("DELETE FROM items WHERE id = ?", (item_db_id,))

    def delete_items(self, item_db_ids):
        """Bulk-delete items by a list of DB ids."""
        if not item_db_ids:
            return
        with self._transact() as (conn, c):
            placeholders = ','.join('?' * len(item_db_ids))
            c.execute(
                f"DELETE FROM items WHERE id IN ({placeholders})",
                tuple(item_db_ids),
            )

    def unequip_item_from_player(self, owner_id, item_db_id):
        """Clear equipment slots referencing this item (used when item breaks)."""
        with self._transact() as (conn, c):
            for slot in ('equipped_weapon', 'equipped_armor', 'equipped_accessory'):
                c.execute(
                    f"UPDATE players SET {slot} = NULL "
                    f"WHERE id = ? AND {slot} = ?",
                    (owner_id, item_db_id),
                )
