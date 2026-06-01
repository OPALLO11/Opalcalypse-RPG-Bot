from datetime import datetime

from .base import BaseRepository
from ..models import Item


def row_to_dict(obj):
    if obj is None:
        return None
    d = {**obj.__dict__}
    d.pop('_sa_instance_state', None)
    if 'class_name' in d:
        d['class'] = d.pop('class_name')
    if 'def_stat' in d:
        d['def'] = d.pop('def_stat')
    return d


class ItemRepository(BaseRepository):

    def get_items_by_owner(self, owner_id):
        with self._read_only() as session:
            items = session.query(Item).filter_by(owner_id=owner_id).all()
            return [{'id': i.id, 'item_id': i.item_id, 'enhancement_level': i.enhancement_level} for i in items]

    def get_item_by_db_id(self, item_db_id):
        with self._read_only() as session:
            item = session.query(Item).filter_by(id=item_db_id).first()
            return row_to_dict(item)

    def find_existing_item(self, owner_id, item_id):
        with self._read_only() as session:
            item = session.query(Item).filter_by(owner_id=owner_id, item_id=item_id).first()
            return row_to_dict(item)

    def add_item(self, owner_id, item_data, boss_name=""):
        item_id = (
            item_data.get('id', 'unknown')
            if isinstance(item_data, dict)
            else str(item_data)
        )
        with self._transact() as session:
            now = datetime.utcnow().isoformat()
            new_item = Item(
                owner_id=owner_id,
                item_id=item_id,
                obtained_from=boss_name,
                obtained_at=now,
                enhancement_level=0
            )
            session.add(new_item)
            session.flush()
            new_id = new_item.id
            return {
                "id": new_id,
                "owner_id": owner_id,
                "item_id": item_id,
                "obtained_from": boss_name,
                "obtained_at": now,
                "enhancement_level": 0,
            }

    def update_enhancement(self, item_db_id, new_level):
        with self._transact() as session:
            item = session.query(Item).filter_by(id=item_db_id).first()
            if item:
                item.enhancement_level = new_level

    def delete_item(self, item_db_id):
        with self._transact() as session:
            session.query(Item).filter_by(id=item_db_id).delete()

    def delete_items(self, item_db_ids):
        if not item_db_ids:
            return
        with self._transact() as session:
            session.query(Item).filter(Item.id.in_(item_db_ids)).delete()

    def unequip_item_from_player(self, owner_id, item_db_id):
        with self._transact() as session:
            from ..models import Player
            player = session.query(Player).filter_by(id=owner_id).first()
            if player:
                if player.equipped_weapon == item_db_id:
                    player.equipped_weapon = None
                if player.equipped_armor == item_db_id:
                    player.equipped_armor = None
                if player.equipped_accessory == item_db_id:
                    player.equipped_accessory = None
