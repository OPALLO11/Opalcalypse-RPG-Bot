import json
from datetime import datetime

from game.logic import get_boss_stars_for_avg_level
from .base import BaseRepository
from ..models import Boss, BossParticipant, Player, PlayerClassLevel


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


class BossRepository(BaseRepository):
    _stars_cache = {}

    @classmethod
    def clear_stars_cache(cls):
        cls._stars_cache.clear()

    def __init__(self, lock):
        super().__init__(lock)

    def _hydrate_boss(self, boss_obj, session=None):
        if not boss_obj:
            return None
        boss = row_to_dict(boss_obj)
        instance_id = boss['instance_id']
        
        # In models.py, weakness and resist are JSON columns so they are already lists.
        # But just in case, we default them if they're None.
        boss['weakness'] = boss['weakness'] if boss['weakness'] is not None else []
        boss['resist'] = boss['resist'] if boss['resist'] is not None else []
        
        # Extract participants
        participants = [p.player_id for p in boss_obj.participants]
        boss['participants'] = participants

        if instance_id in self.__class__._stars_cache:
            boss['stars'] = self.__class__._stars_cache[instance_id]
            return boss

        avg_lvl = 1
        if participants and session:
            # Join PlayerClassLevel with Player based on active class
            total_lvl = 0
            count = 0
            for pid in participants:
                player = session.query(Player).filter_by(id=pid).first()
                if player:
                    cls_name = player.class_name.lower()
                    cl = session.query(PlayerClassLevel).filter_by(player_id=pid, class_name=cls_name).first()
                    if cl:
                        total_lvl += cl.level
                    else:
                        total_lvl += player.level
                    count += 1
            if count > 0:
                avg_lvl = total_lvl / count

        stars = get_boss_stars_for_avg_level(avg_lvl)
        self.__class__._stars_cache[instance_id] = stars
        boss['stars'] = stars

        return boss


    def get_active_boss(self):
        with self._read_only() as session:
            boss_obj = session.query(Boss).filter_by(status='active').order_by(Boss.instance_id.desc()).first()
            return self._hydrate_boss(boss_obj, session)

    def set_active_boss(self, boss_data):
        with self._transact() as session:
            weakness = boss_data.get('weakness', [])
            resist = boss_data.get('resist', [])
            participants_list = boss_data.get('participants', [])
            now = datetime.utcnow().isoformat()

            new_boss = Boss(
                boss_id=boss_data.get('boss_id'),
                name=boss_data.get('name'),
                type=boss_data.get('type'),
                element=boss_data.get('element'),
                base_hp=boss_data.get('base_hp'),
                base_def=boss_data.get('base_def', 0),
                current_hp=boss_data.get('current_hp'),
                max_hp=boss_data.get('max_hp'),
                weakness=weakness,
                resist=resist,
                image_url=boss_data.get('image_url'),
                spawned_at=now,
                status='active'
            )
            session.add(new_boss)
            session.flush()

            for pid in participants_list:
                bp = BossParticipant(boss_instance_id=new_boss.instance_id, player_id=pid)
                session.add(bp)

            boss_data['instance_id'] = new_boss.instance_id
            self.__class__.clear_stars_cache()

    def update_boss(self, instance_id, updates):
        if not updates:
            return self.get_active_boss()

        with self._transact() as session:
            boss_obj = session.query(Boss).filter_by(instance_id=instance_id).first()
            if not boss_obj:
                return None

            update_data = dict(updates)
            
            # Handle participants updates separately
            if 'participants' in update_data:
                participants_list = update_data.pop('participants')
                # Clear existing
                session.query(BossParticipant).filter_by(boss_instance_id=instance_id).delete()
                # Add new
                for pid in set(participants_list):
                    bp = BossParticipant(boss_instance_id=instance_id, player_id=pid)
                    session.add(bp)
                # clear cache because avg lvl might change
                self.__class__.clear_stars_cache()

            for k, v in update_data.items():
                if hasattr(boss_obj, k):
                    setattr(boss_obj, k, v)

            if boss_obj.current_hp <= 0:
                boss_obj.status = 'defeated'
                boss_obj.defeated_at = datetime.utcnow().isoformat()

        self.__class__._stars_cache.pop(instance_id, None)
        return self.get_active_boss()
