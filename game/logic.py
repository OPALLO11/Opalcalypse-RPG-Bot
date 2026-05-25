import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

def load_json(filename):
    with open(os.path.join(DATA_DIR, filename), 'r', encoding='utf-8') as f:
        return json.load(f)

CLASSES = load_json('classes.json')
BOSSES = load_json('bosses.json')
ITEMS = load_json('items.json')

def calculate_boss_hp(base_hp, active_players):
    """
    Boss Scaling: HP = Base HP × (1 + Active Players × 0.3)
    """
    if active_players < 1:
        active_players = 1
    return int(base_hp * (1 + active_players * 0.3))

def get_element_multiplier(attack_element, boss_weaknesses, boss_resists):
    if not attack_element:
        return 1.0
    
    # Needs to parse strings if stored as JSON arrays in DB or loaded from list
    if isinstance(boss_weaknesses, str):
        try:
            boss_weaknesses = json.loads(boss_weaknesses)
        except:
            boss_weaknesses = []

    if isinstance(boss_resists, str):
        try: boss_resists = json.loads(boss_resists)
        except:
            boss_resists = []

    if attack_element in boss_weaknesses:
        return 1.5
    if attack_element in boss_resists:
        return 0.5
    return 1.0

def calculate_player_stats(player):
    """
    Calculate full stats from base class and items.
    player is a dict from DB players row.
    """
    from .helpers import find_item_data, get_level_requirement

    cls_name = player.get('class', 'warrior').lower()
    cls = CLASSES.get(cls_name, CLASSES['warrior'])
    
    class_levels = player.get('class_levels', {})
    if isinstance(class_levels, str):
        try: class_levels = json.loads(class_levels)
        except Exception: class_levels = {}
    
    level_dict = class_levels.get(cls_name, {'level': player.get('level', 1)})
    level = level_dict.get('level', player.get('level', 1))
    
    stats = {
        'max_hp': cls['base_stats']['hp'] + (level - 1) * cls['stat_growth']['hp'],
        'max_mp': cls['base_stats']['mp'] + (level - 1) * cls['stat_growth']['mp'] + cls['passive'].get('bonus_mp', 0),
        'atk': cls['base_stats']['atk'] + (level - 1) * cls['stat_growth']['atk'],
        'def': cls['base_stats']['def'] + (level - 1) * cls['stat_growth']['def'],
        'crit_chance': cls['passive'].get('base_crit_chance', 0.0),
        'element': None
    }
    
    # Add equipped items stats
    from database import db
    conn = db.get_connection()
    try:
        c = conn.cursor()
        equipped_ids = []
        for slot in ['equipped_weapon', 'equipped_armor', 'equipped_accessory']:
            if player.get(slot):
                equipped_ids.append(player[slot])
                
        if equipped_ids:
            placeholders = ','.join('?' * len(equipped_ids))
            c.execute(f"SELECT item_id, enhancement_level FROM items WHERE id IN ({placeholders})", tuple(equipped_ids))
            rows = c.fetchall()
            
            for row in rows:
                item_id = row['item_id']
                enh = row.get('enhancement_level') or 0
                item_data, item_tier = find_item_data(item_id)
                    
                if item_data:
                    if not item_tier:
                        item_tier = 'R'
                    req_lvl = get_level_requirement(item_tier, enh)
                        
                    if level < req_lvl:
                        continue  # Ignore stats for this item if level requirement is not met
                        
                    mult = 1.0 + (0.10 * enh)
                    stats['max_hp'] += int(item_data.get('hp_bonus', 0) * mult)
                    stats['max_mp'] += int(item_data.get('mp_bonus', 0) * mult)
                    stats['atk'] += int(item_data.get('atk', 0) * mult)
                    stats['def'] += int(item_data.get('def', 0) * mult)
                    stats['crit_chance'] += item_data.get('crit_rate', 0) / 100.0
                    if item_data.get('element'):
                        stats['element'] = item_data['element']
    finally:
        conn.close()
    
    return stats

def get_required_exp(level):
    """
    Required EXP = (level * 200) + (level^2 * 50)
    """
    return (level * 200) + (level ** 2) * 50

def add_exp(player_id, amount):
    from database import db
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT username, character_name, class, class_levels, level FROM players WHERE id = ?", (player_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return None

    player = dict(row)
    cls_name = player.get('class', 'warrior').lower()
    
    class_levels = player.get('class_levels', '{}')
    if isinstance(class_levels, str):
        try: class_levels = json.loads(class_levels)
        except: class_levels = {}

    current_class_data = class_levels.get(cls_name, {'level': player.get('level', 1), 'exp': 0})
    level = current_class_data.get('level', 1)
    exp = current_class_data.get('exp', 0)
    
    exp += amount
    level_up = False
    old_level = level
    max_level_allowed = old_level + 1
    
    req_exp = get_required_exp(level)
    while exp >= req_exp:
        if level >= max_level_allowed:
            exp = req_exp - 1
            break
        exp -= req_exp
        level += 1
        level_up = True
        req_exp = get_required_exp(level)
        
    current_class_data['level'] = level
    current_class_data['exp'] = exp
    class_levels[cls_name] = current_class_data
    
    if level_up:
        player_for_stats = player.copy()
        player_for_stats['class_levels'] = json.dumps(class_levels)
        player_for_stats['level'] = level
        
        s = calculate_player_stats(player_for_stats)
        c.execute("UPDATE players SET class_levels = ?, hp = ?, mp = ? WHERE id = ?", (json.dumps(class_levels), s['max_hp'], s['max_mp'], player_id))
    else:
        c.execute("UPDATE players SET class_levels = ? WHERE id = ?", (json.dumps(class_levels), player_id))
        
    conn.commit()
    conn.close()
    
    return {
        "level_up": level_up,
        "old_level": old_level,
        "new_level": level,
        "class": cls_name,
        "username": player['username'],
        "character_name": player['character_name'] or player['username']
    }
