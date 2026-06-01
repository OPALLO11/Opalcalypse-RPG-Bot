import json
import os
from datetime import datetime

from sqlalchemy import func
from .base import BaseRepository
from ..models import Player, PlayerClassLevel, Item

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')


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


class PlayerRepository(BaseRepository):

    def __init__(self, lock):
        super().__init__(lock)
        self._find_item_data = None
        self._calculate_player_stats = None
        self._get_required_exp = None

    def register_helpers(self, find_item_data, calculate_player_stats, get_required_exp):
        self._find_item_data = find_item_data
        self._calculate_player_stats = calculate_player_stats
        self._get_required_exp = get_required_exp

    def _hydrate_player(self, player_obj):
        if not player_obj:
            return None
        p = row_to_dict(player_obj)
        
        class_levels = {}
        for cl in player_obj.class_levels_data:
            class_levels[cl.class_name] = {'level': cl.level, 'exp': cl.exp}
        p['class_levels'] = class_levels

        cls_name = p.get('class', 'warrior').lower()
        if cls_name in class_levels:
            p['level'] = class_levels[cls_name].get('level', p.get('level', 1))
        else:
            p['level'] = p.get('level', 1)

        try:
            if not self._calculate_player_stats:
                try:
                    from game.logic import calculate_player_stats
                    self._calculate_player_stats = calculate_player_stats
                except ImportError:
                    pass
            if self._calculate_player_stats:
                s = self._calculate_player_stats(p)
                if p['hp'] > s['max_hp']:
                    p['hp'] = s['max_hp']
                if p['mp'] > s['max_mp']:
                    p['mp'] = s['max_mp']
        except Exception as e:
            print(f"Error capping player HP/MP: {e}")

        return p

    def get_player(self, username):
        with self._read_only() as session:
            player_obj = session.query(Player).filter(
                (func.lower(Player.username) == username.lower()) | 
                (func.lower(Player.character_name) == username.lower())
            ).first()
            return self._hydrate_player(player_obj)

    def get_player_by_id(self, player_id):
        with self._read_only() as session:
            player_obj = session.query(Player).filter_by(id=player_id).first()
            return self._hydrate_player(player_obj)

    def get_all_players(self):
        with self._read_only() as session:
            players = session.query(Player).all()
            return [self._hydrate_player(p) for p in players]

    def get_player_basic(self, player_id, columns="username, character_name"):
        with self._read_only() as session:
            player_obj = session.query(Player).filter_by(id=player_id).first()
            if not player_obj:
                return None
            return {
                'username': player_obj.username,
                'character_name': player_obj.character_name
            }

    def create_player(self, username, twitch_id, character_name, class_name="warrior"):
        with self._transact() as session:
            existing = session.query(Player).filter(
                (func.lower(Player.username) == username.lower()) |
                (Player.twitch_id == str(twitch_id))
            ).first()
            if existing:
                return False

            classes_path = os.path.join(DATA_DIR, 'classes.json')
            initial_hp = 1000
            initial_mp = 50
            try:
                with open(classes_path, 'r', encoding='utf-8') as f:
                    classes_data = json.load(f)
                cls_info = classes_data.get(class_name.lower())
                if cls_info:
                    initial_hp = cls_info['base_stats']['hp']
                    initial_mp = cls_info['base_stats']['mp']
                    passive = cls_info.get('passive', {})
                    initial_mp += passive.get('bonus_mp', 0)
            except Exception as e:
                print(f"Error loading classes.json in create_player: {e}")

            new_player = Player(
                username=username.lower(),
                twitch_id=str(twitch_id),
                character_name=character_name,
                class_name=class_name,
                hp=initial_hp,
                mp=initial_mp,
                session_renamed=False,
                session_class_changed=False
            )
            session.add(new_player)
            session.flush()

            class_level = PlayerClassLevel(
                player_id=new_player.id,
                class_name=class_name,
                level=1,
                exp=0
            )
            session.add(class_level)
            return True

    def update_player(self, player_id, updates):
        if not updates:
            return False
        
        if 'level' in updates or 'class_levels' in updates:
            try:
                from .boss_repo import BossRepository
                BossRepository.clear_stars_cache()
            except Exception:
                pass
                
        with self._transact() as session:
            player_obj = session.query(Player).filter_by(id=player_id).first()
            if not player_obj:
                return False

            # class_levels update requires special handling
            if 'class_levels' in updates:
                class_levels = updates.pop('class_levels')
                if isinstance(class_levels, str):
                    class_levels = json.loads(class_levels)
                
                for cls_name, data in class_levels.items():
                    cl = session.query(PlayerClassLevel).filter_by(
                        player_id=player_id, class_name=cls_name
                    ).first()
                    if cl:
                        cl.level = data.get('level', 1)
                        cl.exp = data.get('exp', 0)
                    else:
                        cl = PlayerClassLevel(
                            player_id=player_id,
                            class_name=cls_name,
                            level=data.get('level', 1),
                            exp=data.get('exp', 0)
                        )
                        session.add(cl)
            
            # Map 'class' key to 'class_name' field
            if 'class' in updates:
                updates['class_name'] = updates.pop('class')

            for k, v in updates.items():
                if hasattr(player_obj, k):
                    setattr(player_obj, k, v)
                    
            return True

    def update_player_hp(self, player_id, new_hp):
        return self.update_player(player_id, {"hp": new_hp})

    def add_player_gold(self, player_id, amount):
        with self._transact() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            if player:
                player.gold += amount

    def reset_rename_limits(self):
        with self._transact() as session:
            session.query(Player).update({
                Player.session_renamed: False,
                Player.session_class_changed: False
            })

    def get_player_equipment(self, player_id):
        with self._read_only() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            if not player:
                return {}

            eq = {}
            for slot in ['equipped_weapon', 'equipped_armor', 'equipped_accessory']:
                item_db_id = getattr(player, slot)
                if item_db_id:
                    item_obj = session.query(Item).filter_by(id=item_db_id).first()
                    if item_obj:
                        item = row_to_dict(item_obj)
                        if not self._find_item_data:
                            try:
                                from game.helpers import find_item_data
                                self._find_item_data = find_item_data
                            except ImportError:
                                pass
                        if self._find_item_data:
                            item_data, tier = self._find_item_data(item['item_id'])
                        else:
                            item_data, tier = None, 'R'
                        item['name'] = item_data['name'] if item_data else item['item_id']
                        item['tier'] = tier or 'R'
                        eq[slot] = item
                    else:
                        eq[slot] = None
                else:
                    eq[slot] = None
        return eq

    def get_equipped_item_rows(self, equipped_ids):
        if not equipped_ids:
            return []
        with self._read_only() as session:
            items = session.query(Item).filter(Item.id.in_(equipped_ids)).all()
            return [{'item_id': i.item_id, 'enhancement_level': i.enhancement_level} for i in items]

    def add_exp(self, player_id, amount):
        with self._transact() as session:
            player = session.query(Player).filter_by(id=player_id).first()
            if not player:
                return None

            cls_name = player.class_name.lower()
            cl = session.query(PlayerClassLevel).filter_by(player_id=player_id, class_name=cls_name).first()
            if not cl:
                cl = PlayerClassLevel(player_id=player_id, class_name=cls_name, level=player.level, exp=0)
                session.add(cl)
                session.flush()

            level = cl.level
            exp = cl.exp + amount
            level_up = False
            old_level = level
            max_level_allowed = old_level + 1

            if not self._get_required_exp:
                try:
                    from game.logic import get_required_exp
                    self._get_required_exp = get_required_exp
                except ImportError:
                    pass
            req_exp = self._get_required_exp(level) if self._get_required_exp else (level * 200 + level ** 2 * 50)
            
            while exp >= req_exp:
                if level >= max_level_allowed:
                    exp = req_exp - 1
                    break
                exp -= req_exp
                level += 1
                level_up = True
                req_exp = self._get_required_exp(level) if self._get_required_exp else (level * 200 + level ** 2 * 50)

            cl.level = level
            cl.exp = exp
            session.flush()

            if level_up:
                try:
                    from .boss_repo import BossRepository
                    BossRepository.clear_stars_cache()
                except Exception:
                    pass
                
                # Fetch fresh hydrated player data
                player_dict = self._hydrate_player(player)
                
                if not self._calculate_player_stats:
                    try:
                        from game.logic import calculate_player_stats
                        self._calculate_player_stats = calculate_player_stats
                    except ImportError:
                        pass
                
                if self._calculate_player_stats:
                    s = self._calculate_player_stats(player_dict)
                    player.hp = s['max_hp']
                    player.mp = s['max_mp']

            return {
                "level_up": level_up,
                "old_level": old_level,
                "new_level": level,
                "class": cls_name,
                "username": player.username,
                "character_name": player.character_name or player.username,
            }

    def batch_regen_update(self, player_updates):
        if not player_updates:
            return
        with self._transact() as session:
            for pid, updates in player_updates:
                player = session.query(Player).filter_by(id=pid).first()
                if player:
                    if 'class' in updates:
                        updates['class_name'] = updates.pop('class')
                    for k, v in updates.items():
                        if hasattr(player, k):
                            setattr(player, k, v)
