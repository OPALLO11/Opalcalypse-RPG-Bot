import datetime
import random

from database import db
from utils import emit_to_overlay
from .boss_manager import boss_manager
from .helpers import find_item_data, get_level_requirement
from .items import distribute_loot
from .logic import calculate_dynamic_boss_hp, calculate_player_stats, get_element_multiplier, CLASSES

# Global player activity and buff tracking
LAST_ACTIVE = {}  # player_id -> datetime
PLAYER_BUFFS = {}  # player_id -> {buff_name: (value, expires_at)}

import sys

if 'game.combat' in sys.modules:
    _old_combat = sys.modules['game.combat']
    if hasattr(_old_combat, 'LAST_ACTIVE'):
        LAST_ACTIVE = _old_combat.LAST_ACTIVE
    if hasattr(_old_combat, 'PLAYER_BUFFS'):
        PLAYER_BUFFS = _old_combat.PLAYER_BUFFS


def get_player_buff(player_id, buff_name):
    buffs = PLAYER_BUFFS.get(player_id, {})
    if buff_name in buffs:
        val, expires_at = buffs[buff_name]
        if datetime.datetime.now() < expires_at:
            return val
        else:
            del buffs[buff_name]
    return None


def set_player_buff(player_id, buff_name, value, seconds):
    if player_id not in PLAYER_BUFFS:
        PLAYER_BUFFS[player_id] = {}
    PLAYER_BUFFS[player_id][buff_name] = (value, datetime.datetime.now() + datetime.timedelta(seconds=seconds))


import time

COOLDOWNS = {}  # (player_id, action) -> expires_at_timestamp

import sys

if 'game.combat' in sys.modules:
    _old_combat = sys.modules['game.combat']
    if hasattr(_old_combat, 'COOLDOWNS'):
        COOLDOWNS = _old_combat.COOLDOWNS


def check_cooldown(player_id, action):
    expires_at = COOLDOWNS.get((player_id, action))
    if expires_at:
        now = time.time()
        if now < expires_at:
            return False, expires_at - now
    return True, 0


def set_cooldown(player_id, action, seconds):
    COOLDOWNS[(player_id, action)] = time.time() + seconds


def clear_cooldown(player_id, action):
    if (player_id, action) in COOLDOWNS:
        del COOLDOWNS[(player_id, action)]


def get_all_respawn_cooldowns():
    now = time.time()
    dead_pids = set()
    for (pid, act), expires_at in COOLDOWNS.items():
        if act == 'respawn' and now < expires_at:
            dead_pids.add(pid)
    return dead_pids


def calculate_damage(player, boss, skill_data):
    stats = calculate_player_stats(player)

    # Apply ATK buffs
    atk_buff = get_player_buff(player['id'], 'atk_up')
    if atk_buff:
        stats['atk'] = int(stats['atk'] * (1 + atk_buff))

    base_dmg = stats['atk'] * skill_data.get('damage_multiplier', 1.0)

    crit_chance = stats['crit_chance'] + skill_data.get('bonus_crit_chance', 0.0)

    # Apply Crit buffs
    crit_buff = get_player_buff(player['id'], 'crit_up')
    if crit_buff:
        crit_chance += crit_buff

    is_crit = False

    player_class = player.get('class', 'warrior').lower()

    if player_class == 'rogue' and (boss['current_hp'] / boss['max_hp']) < 0.3:
        crit_multiplier = 2.5
    elif player_class == 'rogue':
        crit_multiplier = 2.0
    else:
        crit_multiplier = 1.5

    if skill_data.get('guaranteed_crit'):
        is_crit = True
    elif random.random() < crit_chance:
        is_crit = True

    if is_crit:
        base_dmg *= crit_multiplier

    elem = skill_data.get('type', 'physical').replace('magic_', '')
    if elem in ['physical', 'magic', 'magic_aoe']:
        elem = stats.get('element')

    elem_mult = get_element_multiplier(elem, boss['weakness'], boss['resist'])
    base_dmg *= elem_mult

    if player_class == 'mage' and skill_data['name'] not in ('Basic Attack', 'Magic Bolt'):
        # Mage passive skill damage bonus
        base_dmg *= 1.30

    # Calculate boss defense
    participants = boss.get('participants', [])
    if participants:
        total_lvl = 0
        for pid in participants:
            pdata = db.get_player_by_id(pid)
            if pdata:
                total_lvl += pdata.get('level', 1)
        avg_lvl = total_lvl / len(participants)
    else:
        avg_lvl = 1

    boss_def = boss.get('base_def', 0) + int(avg_lvl * 10)

    final_dmg = max(10, int(base_dmg) - boss_def)
    return final_dmg, is_crit


def log_combat(boss_instance_id, player_id, action, damage, is_crit):
    db.add_combat_log(boss_instance_id, player_id, action, damage, is_crit)
    try:
        from game.challenge_manager import track_progress
        if damage > 0:
            track_progress('damage', damage)
        if is_crit:
            track_progress('crits', 1)
    except Exception as e:
        print(f"Error tracking combat challenge progress: {e}")


def get_party_data(boss):
    if not boss:
        return []
    participants = boss.get('participants', [])
    party = []
    for pid in participants:
        pdata = db.get_player_by_id(pid)
        if pdata:
            stats = calculate_player_stats(pdata)

            can_act, cd = check_cooldown(pid, 'respawn')
            is_dead = not can_act

            current_hp = 0 if is_dead else pdata['hp']

            is_defending = False
            boss_state = boss_manager.boss_state.get(boss['instance_id'])
            if boss_state:
                is_defending = pid in boss_state.get('defending_players', set())

            icon_map = {'warrior': '⚔️', 'mage': '🔮', 'rogue': '🗡️', 'priest': '💖'}
            cls = pdata.get('class', 'warrior').lower()
            icon = icon_map.get(cls, '⚔️')

            party.append({
                'id': pdata['id'],
                'username': pdata['username'],
                'character_name': pdata['character_name'] or pdata['username'],
                'class': cls,
                'icon': icon,
                'level': pdata['level'],
                'hp': current_hp,
                'max_hp': stats['max_hp'],
                'mp': pdata['mp'],
                'max_mp': stats['max_mp'],
                'is_dead': is_dead,
                'is_defending': is_defending
            })
    return party


def _validate_and_resolve_skill(player, action_type, skill_name, cls_name, cls_data):
    """
    Check cooldowns, resolve the skill data dict, and validate MP.
    Returns (skill_data, error_response_or_None).
    """
    can_act, cd = check_cooldown(player['id'], 'respawn')
    if not can_act:
        return None, {'success': False, 'message': f'You are dead! Respawning in {int(cd)}s...'}

    if action_type != 'skill':
        can_act, cd = check_cooldown(player['id'], action_type)
        if not can_act:
            return None, {'success': False, 'message': f'Cooldown: {cd:.1f}s'}

    skill_data = None
    if action_type == 'def':
        valid_def_skills = {'warrior': 'parry', 'mage': 'barrier', 'rogue': 'dodge', 'priest': 'absorb'}
        req_skill = valid_def_skills.get(cls_name)
        if not skill_name or skill_name.lower().strip() != req_skill:
            return None, {'success': False, 'message': f"Invalid def skill! Your class uses: !def {req_skill}"}
        skill_data = {'name': req_skill.capitalize(), 'mp_cost': 0, 'cooldown': 5}
    elif action_type == 'ultimate':
        skill_data = cls_data['skills'].get('ultimate')
        skill_name = 'ultimate'
    elif action_type == 'attack':
        skill_data = cls_data['skills'].get('attack')
        skill_name = 'attack'
    elif action_type == 'skill':
        skills = [k for k in cls_data['skills'].keys() if k not in ('attack', 'ultimate')]
        if not skill_name:
            skill_list_strs = []
            for idx, s_key in enumerate(skills, 1):
                s_data = cls_data['skills'][s_key]
                s_name = s_data.get('name', s_key.capitalize())
                cd_val = s_data.get('cooldown', 0)
                skill_list_strs.append(f"[{idx}] {s_name} ({cd_val}s)")
            cls_display = cls_data.get('name', cls_name.capitalize())
            return None, {
                'success': False,
                'message': f"\u0e42\u0e1b\u0e23\u0e14\u0e23\u0e30\u0e1a\u0e38\u0e2b\u0e21\u0e32\u0e22\u0e40\u0e25\u0e02\u0e2a\u0e01\u0e34\u0e25: !skill <\u0e40\u0e25\u0e02> \u0e2a\u0e01\u0e34\u0e25\u0e02\u0e2d\u0e07\u0e04\u0e38\u0e13 ({cls_display}): {', '.join(skill_list_strs)}"
            }

        skill_name = skill_name.lower().strip()
        if skill_name.isdigit():
            idx = int(skill_name) - 1
            if 0 <= idx < len(skills):
                skill_name = skills[idx]
            else:
                skill_list_strs = []
                for i, s_key in enumerate(skills, 1):
                    s_data = cls_data['skills'][s_key]
                    s_name = s_data.get('name', s_key.capitalize())
                    cd_val = s_data.get('cooldown', 0)
                    skill_list_strs.append(f"[{i}] {s_name} ({cd_val}s)")
                cls_display = cls_data.get('name', cls_name.capitalize())
                return None, {
                    'success': False,
                    'message': f"\u0e44\u0e21\u0e48\u0e1e\u0e1a\u0e2a\u0e01\u0e34\u0e25\u0e2b\u0e21\u0e32\u0e22\u0e40\u0e25\u0e02 {skill_name}! \u0e2a\u0e01\u0e34\u0e25\u0e02\u0e2d\u0e07\u0e04\u0e38\u0e13 ({cls_display}): {', '.join(skill_list_strs)}"
                }

        skill_data = cls_data['skills'].get(skill_name)
        if not skill_data or skill_name in ('attack', 'ultimate'):
            skill_list_strs = []
            for i, s_key in enumerate(skills, 1):
                s_data = cls_data['skills'][s_key]
                s_name = s_data.get('name', s_key.capitalize())
                cd_val = s_data.get('cooldown', 0)
                skill_list_strs.append(f"[{i}] {s_name} ({cd_val}s)")
            cls_display = cls_data.get('name', cls_name.capitalize())
            return None, {
                'success': False,
                'message': f"\u0e44\u0e21\u0e48\u0e1e\u0e1a\u0e2a\u0e01\u0e34\u0e25\u0e0a\u0e37\u0e48\u0e2d {skill_name}! \u0e2a\u0e01\u0e34\u0e25\u0e02\u0e2d\u0e07\u0e04\u0e38\u0e13 ({cls_display}): {', '.join(skill_list_strs)}"
            }

    if action_type == 'skill':
        cooldown_action_key = f"skill_{skill_name}"
        can_act, cd = check_cooldown(player['id'], cooldown_action_key)
        if not can_act:
            return None, {'success': False,
                          'message': f"\u0e2a\u0e01\u0e34\u0e25 {skill_data.get('name', skill_name)} \u0e22\u0e31\u0e07\u0e15\u0e34\u0e14\u0e04\u0e39\u0e25\u0e14\u0e32\u0e27\u0e19\u0e4c\u0e40\u0e2b\u0e25\u0e37\u0e2d {cd:.1f} \u0e27\u0e34\u0e19\u0e32\u0e17\u0e35"}

    mp_cost = skill_data.get('mp_cost', 0)
    if player.get('mp', 0) < mp_cost:
        return None, {'success': False, 'message': f"Need {mp_cost} MP!"}

    return skill_data, None


def _update_participants(boss, player_id):
    """
    Add the player to participants, prune inactive players, and
    recalculate dynamic boss HP scaling.
    Returns the (potentially updated) boss dict.
    """
    LAST_ACTIVE[player_id] = datetime.datetime.now()

    now_time = datetime.datetime.now()
    timeout_limit = datetime.timedelta(minutes=15)

    participants = list(boss.get('participants', []))
    participants_changed = False

    if player_id not in participants:
        participants.append(player_id)
        participants_changed = True

    active_participants = []
    for pid in participants:
        last_time = LAST_ACTIVE.get(pid)
        if pid == player_id or (last_time and (now_time - last_time) <= timeout_limit):
            active_participants.append(pid)

    # Dynamic HP scaling: base formula softened by boss star tier.
    total_lvl = 0
    for pid in active_participants:
        pdata = db.get_player_by_id(pid)
        if pdata:
            total_lvl += pdata.get('level', 1)
    avg_lvl = total_lvl / max(1, len(active_participants))

    new_max_hp = calculate_dynamic_boss_hp(
        boss['base_hp'],
        avg_lvl,
        len(active_participants),
    )

    if new_max_hp != boss['max_hp'] or participants_changed:
        old_max_hp = boss['max_hp']
        boss['max_hp'] = new_max_hp
        hp_diff = new_max_hp - old_max_hp
        if hp_diff > 0:
            boss['current_hp'] += hp_diff
        else:
            boss['current_hp'] = min(boss['current_hp'], new_max_hp)

        boss['participants'] = participants
        db.update_boss(boss['instance_id'], {
            'max_hp': new_max_hp,
            'current_hp': boss['current_hp'],
            'participants': participants
        })

    return boss


def _apply_combat_effects(player, boss, action_type, skill_name, skill_data, cls_name, cls_data, participants,
                          target=None):
    """
    Process all combat effects: buffs, debuffs, healing, damage, poison DoT.
    Returns (dmg, is_crit, is_dead, left_hp, heal_msg, logged_heal_amount).
    """
    heal_msg = ""
    is_dead, left_hp = False, boss['current_hp']
    dmg, is_crit = 0, False
    logged_heal_amount = 0

    # Apply self buff skills
    if action_type == 'skill':
        if skill_name == 'shieldbash':
            set_player_buff(player['id'], 'def_up', 0.30, 20)
        elif skill_name == 'shadowstep':
            set_player_buff(player['id'], 'crit_up', 0.20, 15)
            set_player_buff(player['id'], 'dodge_up', 0.20, 15)

    if action_type == 'ultimate' and cls_name == 'warrior':
        set_player_buff(player['id'], 'atk_up', 0.50, 30)

    # Priest healing / reviving skills
    is_healing_skill = False
    if cls_name == 'priest' and (action_type == 'skill' or action_type == 'ultimate'):
        if skill_name in ('heal', 'sanctuary') or action_type == 'ultimate':
            is_healing_skill = True
            priest_passive = cls_data.get('passive', {})
            healing_bonus = priest_passive.get('healing_bonus', 0.30)

            if skill_name == 'heal':
                heal_target = None
                if target:
                    clean_target = target.replace('@', '').strip().lower()
                    heal_target = db.get_player(clean_target)

                if not heal_target:
                    lowest_player = None
                    lowest_pct = 1.0
                    for pid in participants:
                        pdata = db.get_player_by_id(pid)
                        if pdata:
                            alive, _ = check_cooldown(pid, 'respawn')
                            if not alive:
                                continue
                            pstats = calculate_player_stats(pdata)
                            pct = pdata.get('hp', 0) / pstats['max_hp']
                            if pct < lowest_pct:
                                lowest_pct = pct
                                lowest_player = pdata
                    heal_target = lowest_player

                if not heal_target:
                    heal_target = player

                t_stats = calculate_player_stats(heal_target)
                heal_amount = int(t_stats['max_hp'] * 0.30 * (1 + healing_bonus))
                new_hp = min(t_stats['max_hp'], heal_target.get('hp', 0) + heal_amount)
                db.update_player_hp(heal_target['id'], new_hp)
                heal_msg = f"\ud83d\udc96 \u0e2e\u0e35\u0e25 {heal_target['character_name'] or heal_target['username']} \u0e1f\u0e37\u0e49\u0e19\u0e1f\u0e39 +{heal_amount} HP!"
                logged_heal_amount = heal_amount

            elif skill_name == 'sanctuary':
                total_healed = 0
                for pid in participants:
                    pdata = db.get_player_by_id(pid)
                    if pdata:
                        alive, _ = check_cooldown(pid, 'respawn')
                        if not alive: continue
                        pstats = calculate_player_stats(pdata)
                        heal_amount = int(pstats['max_hp'] * 0.10 * (1 + healing_bonus))
                        new_hp = min(pstats['max_hp'], pdata.get('hp', 0) + heal_amount)
                        db.update_player_hp(pid, new_hp)
                        set_player_buff(pid, 'def_up', 0.20, 30)
                        total_healed += heal_amount
                heal_msg = f"\ud83d\udee1\ufe0f Sanctuary! \u0e1f\u0e37\u0e49\u0e19\u0e1f\u0e39\u0e1c\u0e39\u0e49\u0e40\u0e25\u0e48\u0e19\u0e17\u0e38\u0e01\u0e04\u0e19 +10% HP \u0e41\u0e25\u0e30\u0e40\u0e1e\u0e34\u0e48\u0e21\u0e1e\u0e25\u0e31\u0e07\u0e1b\u0e49\u0e2d\u0e07\u0e01\u0e31\u0e19 +20% (30 \u0e27\u0e34\u0e19\u0e32\u0e17\u0e35)"
                logged_heal_amount = total_healed

            elif action_type == 'ultimate':  # Miracle
                total_healed = 0
                for pid in participants:
                    pdata = db.get_player_by_id(pid)
                    if pdata:
                        pstats = calculate_player_stats(pdata)
                        alive, cd = check_cooldown(pid, 'respawn')
                        heal_amount = int(pstats['max_hp'] * 0.50)
                        total_healed += heal_amount
                        if not alive:
                            clear_cooldown(pid, 'respawn')
                            db.update_player_hp(pid, heal_amount)
                        else:
                            new_hp = min(pstats['max_hp'], pdata.get('hp', 0) + heal_amount)
                            db.update_player_hp(pid, new_hp)
                heal_msg = f"\ud83c\udf1f Miracle! \u0e0a\u0e38\u0e1a\u0e0a\u0e35\u0e27\u0e34\u0e15\u0e1c\u0e39\u0e49\u0e40\u0e25\u0e48\u0e19\u0e17\u0e35\u0e48\u0e15\u0e32\u0e22\u0e17\u0e31\u0e49\u0e07\u0e2b\u0e21\u0e14 \u0e41\u0e25\u0e30\u0e1f\u0e37\u0e49\u0e19\u0e1f\u0e39 HP 50% \u0e41\u0e01\u0e48\u0e17\u0e38\u0e01\u0e04\u0e19!"
                logged_heal_amount = total_healed

    # Apply boss status debuffs from skills
    if action_type == 'skill':
        state = boss_manager.boss_state.get(boss['instance_id'])
        if state:
            if 'debuffs' not in state:
                state['debuffs'] = {}
            if skill_name == 'blizzard':
                state['debuffs']['slow'] = datetime.datetime.now() + datetime.timedelta(seconds=15)
            elif skill_name == 'powerstrike':
                state['debuffs']['stun'] = datetime.datetime.now() + datetime.timedelta(seconds=5)
            elif skill_name == 'taunt':
                state['debuffs']['taunt'] = datetime.datetime.now() + datetime.timedelta(seconds=15)
            elif skill_name == 'poisondart':
                state['debuffs']['poison'] = datetime.datetime.now() + datetime.timedelta(seconds=20)

    if action_type == 'def':
        pass  # Defending deals no damage
    elif is_healing_skill:
        log_combat(boss['instance_id'], player['id'],
                   skill_data['name'] if action_type == 'skill' else 'Miracle',
                   logged_heal_amount, False)
    else:
        dmg, is_crit = calculate_damage(player, boss, skill_data)
        is_dead, left_hp = boss_manager.take_damage(dmg, player['id'])
        log_combat(boss['instance_id'], player['id'], skill_data['name'], dmg, is_crit)

    # Poison DoT
    poison_dmg = 0
    boss_state = boss_manager.boss_state.get(boss['instance_id'])
    if boss_state and not is_dead and action_type != 'def':
        debuffs = boss_state.get('debuffs', {})
        if 'poison' in debuffs:
            if datetime.datetime.now() < debuffs['poison']:
                poison_dmg = max(50, int(boss['max_hp'] * 0.005))
                is_dead, left_hp = boss_manager.take_damage(poison_dmg, player['id'])
                log_combat(boss['instance_id'], player['id'], "Poison DoT", poison_dmg, False)
            else:
                del debuffs['poison']

    return dmg, is_crit, is_dead, left_hp, heal_msg, poison_dmg


def _distribute_boss_rewards(boss, participants, rankings):
    """
    Distribute gold, EXP, MVP, and loot when a boss is defeated.
    Returns (loot_results, exp_results, gold_results).
    """
    loot_results = distribute_loot(boss['name'], rankings)

    # Gold rewards based on stars and type
    boss_stars = boss.get('stars', 1)
    base_gold_map = {1: 1000, 2: 3000, 3: 10000, 4: 30000, 5: 100000}
    base_gold = base_gold_map.get(boss_stars, 1000)

    type_mult = 1.0
    if boss.get('type') == 'weekly':
        type_mult = 2.5
    elif boss.get('type') == 'monthly':
        type_mult = 5.0

    total_boss_gold = int(base_gold * type_mult)
    total_contribution = sum(p['damage'] for p in rankings)

    gold_results = {}
    for p in rankings:
        p_id = p['id']
        pct = p['damage'] / total_contribution if total_contribution > 0 else 1.0 / len(rankings)
        player_gold = int(total_boss_gold * pct)
        if player_gold > 0:
            db.add_player_gold(p_id, player_gold)
            gold_results[p_id] = player_gold

    # EXP rewards
    if participants:
        total_lvl = sum(db.get_player_by_id(pid).get('level', 1) for pid in participants if db.get_player_by_id(pid))
        avg_lvl = total_lvl / len(participants)
    else:
        avg_lvl = 1

    boss_type = boss.get('type', 'normal')
    if boss_type == 'monthly':
        base_exp = 3000 + int(avg_lvl * 50)
    elif boss_type == 'weekly':
        base_exp = 800 + int(avg_lvl * 15)
    else:
        base_exp = 150 + int(avg_lvl * 5)

    from .logic import add_exp
    exp_results = []
    for index, p in enumerate(rankings):
        is_mvp = (index == 0)
        player_exp = int(base_exp * 1.2) if is_mvp else base_exp

        exp_res = add_exp(p['id'], player_exp)
        if exp_res and exp_res.get('level_up'):
            exp_results.append(exp_res)

        if is_mvp:
            p_current = db.get_player_by_id(p['id'])
            if p_current:
                db.update_player(p['id'], {'mvp_count': p_current.get('mvp_count', 0) + 1})

    return loot_results, exp_results, gold_results


def _get_custom_weapon_format(player, action_type):
    """Fetch custom chat format string from the player's equipped weapon, if any."""
    equipped_weapon_id = player.get('equipped_weapon')
    if not equipped_weapon_id or action_type == 'def':
        return None

    eq = db.get_player_equipment(player['id'])
    eq_weapon = eq.get('equipped_weapon')
    if not eq_weapon:
        return None

    item_tier = eq_weapon.get('tier', 'R')
    enh_lvl = eq_weapon.get('enhancement_level') or 0
    req_lvl = get_level_requirement(item_tier, enh_lvl)

    if player.get('level', 1) < req_lvl:
        return None

    item_data, _ = find_item_data(eq_weapon['item_id'])
    return item_data.get('custom_chat_format') if item_data else None


def process_action(player, action_type, skill_name=None, target=None):
    """Main combat action coordinator."""
    boss = boss_manager.get_current_boss()
    if not boss:
        return {'success': False, 'message': 'No active boss to attack!'}

    cls_name = player.get('class', 'warrior').lower()
    cls_data = CLASSES.get(cls_name)

    # 1. Validate cooldowns & resolve skill
    skill_data, error = _validate_and_resolve_skill(player, action_type, skill_name, cls_name, cls_data)
    if error:
        return error

    # Resolve actual skill_name after validation (may have been converted from index)
    if action_type == 'attack':
        skill_name = 'attack'
    elif action_type == 'ultimate':
        skill_name = 'ultimate'
    elif action_type == 'skill' and skill_name and skill_name.isdigit():
        skills = [k for k in cls_data['skills'].keys() if k not in ('attack', 'ultimate')]
        idx = int(skill_name) - 1
        if 0 <= idx < len(skills):
            skill_name = skills[idx]

    # 2. Update participants & boss scaling
    boss = _update_participants(boss, player['id'])
    participants = boss.get('participants', [])

    # 3. Apply combat effects
    dmg, is_crit, is_dead, left_hp, heal_msg, poison_dmg = _apply_combat_effects(
        player, boss, action_type, skill_name, skill_data, cls_name, cls_data, participants, target=target
    )

    # 4. Apply cooldowns and MP cost
    if action_type == 'skill':
        if 'cooldown' in skill_data:
            set_cooldown(player['id'], f"skill_{skill_name}", skill_data['cooldown'])
    elif 'cooldown' in skill_data:
        set_cooldown(player['id'], action_type, skill_data['cooldown'])
    elif action_type == 'ultimate':
        set_cooldown(player['id'], action_type, 120)

    mp_cost = skill_data.get('mp_cost', 0)
    if mp_cost > 0:
        db.update_player(player['id'], {"mp": player.get("mp", 0) - mp_cost})

    boss_state_res = boss_manager.record_action(boss, player['id'], action_type)

    # 5. Boss defeated — distribute rewards
    loot_results, exp_results, gold_results = {}, [], {}
    if is_dead:
        try:
            from game.challenge_manager import track_progress
            track_progress('boss_kills', 1)
        except Exception as e:
            print(f"Error tracking boss kill challenge progress: {e}")
        rankings = db.get_boss_rankings(boss['instance_id'])
        loot_results, exp_results, gold_results = _distribute_boss_rewards(boss, participants, rankings)

    # 6. Emit overlay updates
    emit_to_overlay('party_update', get_party_data(boss))

    # 7. Build response message
    custom_format = _get_custom_weapon_format(player, action_type)
    final_msg = f"Dealt {dmg} damage!" if action_type != 'def' else "Ready to defend!"
    if action_type != 'def' and custom_format:
        try:
            p_name = player.get('character_name') or player['username']
            final_msg = custom_format.format(
                player=p_name,
                damage=dmg + poison_dmg,
                boss=boss['name'],
                action=skill_data['name']
            )
        except Exception as e:
            print(f"Error formatting custom chat message: {e}")
    elif heal_msg:
        final_msg = heal_msg
    elif poison_dmg > 0:
        final_msg += f" (Poison DoT dealt {poison_dmg} extra damage!)"

    # 8. Wipe tracking
    if not is_dead:
        alive_count_final = sum(1 for pid in boss.get('participants', []) if check_cooldown(pid, 'respawn')[0])
        boss_state_obj = boss_manager.boss_state.get(boss['instance_id'])
        if boss_state_obj is not None:
            if alive_count_final == 0 and len(boss.get('participants', [])) > 0:
                if 'wipe_time' not in boss_state_obj:
                    boss_state_obj['wipe_time'] = datetime.datetime.now()
            else:
                if 'wipe_time' in boss_state_obj:
                    del boss_state_obj['wipe_time']

    return {
        'success': True,
        'action_name': skill_data['name'],
        'damage': dmg + poison_dmg,
        'is_crit': is_crit,
        'is_dead': is_dead,
        'boss_hp': left_hp,
        'loot': loot_results,
        'exp_results': exp_results,
        'gold_rewards': gold_results,
        'boss_state': boss_state_res,
        'player_died': False,
        'message': final_msg
    }


def revive_party_members(user):
    boss = boss_manager.get_current_boss()
    if not boss:
        return False, "No active boss"

    participants = boss.get('participants', [])

    # Find all players with active respawn cooldowns
    dead_pids = get_all_respawn_cooldowns()

    all_to_check = set(participants) | dead_pids

    revived_any = False
    updated_participants = list(participants)

    for pid in all_to_check:
        alive, _ = check_cooldown(pid, 'respawn')
        if not alive:
            clear_cooldown(pid, 'respawn')
            p_data = db.get_player_by_id(pid)
            if p_data:
                p_stats = calculate_player_stats(p_data)
                db.update_player_hp(pid, int(p_stats['max_hp'] * 0.50))
                revived_any = True
                if pid not in updated_participants:
                    updated_participants.append(pid)

    if revived_any:
        db.update_boss(boss['instance_id'], {'participants': updated_participants})
        boss = boss_manager.get_current_boss()

        boss_state = boss_manager.boss_state.get(boss['instance_id'])
        if boss_state and 'wipe_time' in boss_state:
            del boss_state['wipe_time']

        emit_to_overlay('party_update', get_party_data(boss))
        emit_to_overlay('combat_event', {
            'username': '💖 Streamer.bot',
            'action': f'{user} redeemed Revive Party! Dead party members revived!',
            'damage': 0, 'is_crit': False,
            'boss_hp': boss['current_hp']
        })
        return True, "Party revived"
    return False, "No dead party members to revive"


def revive_single_player(user, target_name):
    boss = boss_manager.get_current_boss()
    if not boss:
        return False, "No active boss"

    clean_target = target_name.replace('@', '').strip().lower()
    p_data = db.get_player(clean_target)
    if not p_data:
        return False, f"ไม่พบผู้เล่นชื่อ {target_name}"

    alive, cd = check_cooldown(p_data['id'], 'respawn')
    if alive:
        return False, f"{p_data['character_name'] or p_data['username']} ยังไม่ตาย!"

    clear_cooldown(p_data['id'], 'respawn')
    p_stats = calculate_player_stats(p_data)
    db.update_player_hp(p_data['id'], p_stats['max_hp'])

    participants = boss.get('participants', [])
    if p_data['id'] not in participants:
        participants.append(p_data['id'])
        db.update_boss(boss['instance_id'], {'participants': participants})
        boss = boss_manager.get_current_boss()

    boss_state = boss_manager.boss_state.get(boss['instance_id'])
    if boss_state and 'wipe_time' in boss_state:
        del boss_state['wipe_time']

    emit_to_overlay('party_update', get_party_data(boss))
    emit_to_overlay('combat_event', {
        'username': '💖 Streamer.bot',
        'action': f'{user} redeemed Revive Player! Revived {p_data["character_name"] or p_data["username"]}!',
        'damage': 0, 'is_crit': False,
        'boss_hp': boss['current_hp']
    })
    return True, f"Revived {p_data['character_name'] or p_data['username']}"


async def trigger_boss_aoe_attack(boss):
    from utils import send_streamerbot_message

    # 1. Get boss state
    boss_state = boss_manager.boss_state.get(boss['instance_id'])
    if not boss_state or not boss_state.get('is_charging'):
        return

    # Get participants and defenders
    participants = boss.get('participants', [])
    defenders = boss_state.get('defending_players', set())
    next_attack = boss_state.get('next_attack',
                                 {"name": "Mighty Strike", "type": "physical", "description": "โจมตีอย่างรุนแรง"})
    atk_name = next_attack.get('name', 'Mighty Strike')
    atk_type = next_attack.get('type', 'physical')

    # Check if boss is taunted
    is_taunted = False
    debuffs = boss_state.get('debuffs', {})
    if 'taunt' in debuffs:
        if datetime.datetime.now() < debuffs['taunt']:
            is_taunted = True
        else:
            del debuffs['taunt']

    # Calculate average level for boss attack scaling
    total_lvl = 0
    for pid in participants:
        pdata = db.get_player_by_id(pid)
        if pdata:
            total_lvl += pdata.get('level', 1)
    avg_lvl = total_lvl / max(1, len(participants))

    base_hp = boss.get('base_hp', 15000)
    boss_atk = int(base_hp * 0.02) + int(avg_lvl * 15) + 300

    if is_taunted:
        boss_atk = int(boss_atk * 0.70)

    victims_info = []
    death_count = 0
    alive_count = 0

    for p_id in participants:
        can_act, cd = check_cooldown(p_id, 'respawn')
        if not can_act:
            continue

        p_data = db.get_player_by_id(p_id)
        if not p_data:
            continue

        p_stats = calculate_player_stats(p_data)
        p_class = p_data.get('class', 'warrior').lower()
        p_def = p_stats['def']
        is_defending = (p_id in defenders)

        def_penalty = False
        if is_defending:
            if atk_type == 'magic' and p_class == 'warrior':
                def_penalty = True
            elif atk_type == 'physical' and p_class in ('mage', 'priest'):
                def_penalty = True
            elif atk_type == 'piercing' and p_class == 'rogue':
                def_penalty = True

        damage_taken = 0
        status = 'hit'

        if is_defending:
            dodge_ratios = {'rogue': 0.60, 'mage': 0.40, 'warrior': 0.20, 'priest': 0.30}
            dodge_chance = dodge_ratios.get(p_class, 0.20)

            dodge_buff = get_player_buff(p_id, 'dodge_up')
            if dodge_buff:
                dodge_chance += dodge_buff

            if def_penalty and p_class in ('rogue', 'mage'):
                dodge_chance /= 2.0

            if random.random() < dodge_chance:
                status = 'dodged'
                damage_taken = 0
            else:
                status = 'blocked'
                effective_def = p_def
                def_buff = get_player_buff(p_id, 'def_up')
                if def_buff:
                    effective_def *= (1 + def_buff)

                if p_class == 'warrior':
                    effective_def *= 3
                elif p_class == 'priest':
                    effective_def *= 2

                if def_penalty and p_class in ('warrior', 'priest'):
                    effective_def = int(effective_def * 0.5)

                damage_taken = max(10, boss_atk - effective_def)
        else:
            effective_def = p_def
            def_buff = get_player_buff(p_id, 'def_up')
            if def_buff:
                effective_def *= (1 + def_buff)
            damage_taken = max(10, boss_atk - effective_def)

        if status != 'dodged':
            if p_class == 'warrior':
                damage_taken = int(damage_taken * 0.8)
            elif p_class == 'mage':
                damage_taken = int(damage_taken * 1.2)
            elif p_class == 'priest':
                orig_damage = damage_taken
                damage_taken = int(damage_taken * 0.7)
                absorbed = orig_damage - damage_taken
                if absorbed > 0:
                    new_mp = min(p_stats['max_mp'], p_data.get('mp', 0) + int(absorbed * 0.20))
                    db.update_player(p_id, {'mp': new_mp})

        if damage_taken > 0:
            new_hp = max(0, p_data.get('hp', 1000) - damage_taken)
            db.update_player_hp(p_id, new_hp)

            if new_hp <= 0:
                status = 'dead'
                death_count += 1
                set_cooldown(p_id, 'respawn', 300)
                db.update_player_hp(p_id, p_stats['max_hp'])
            else:
                alive_count += 1
        else:
            alive_count += 1

        victims_info.append({
            'username': p_data['username'],
            'status': status,
            'damage': damage_taken
        })

    # Reset boss charge state
    boss_state['charge'] = 0
    boss_state['is_charging'] = False
    boss_state['defending_players'] = set()
    boss_state['charge_start_time'] = None
    boss_state['next_attack'] = None

    # Process wipe
    if alive_count == 0 and len(participants) > 0:
        if 'wipe_time' not in boss_state:
            boss_state['wipe_time'] = datetime.datetime.now()

    # Send messages
    details = []
    for v in victims_info:
        u = v['username']
        st = v['status']
        if st == 'dodged':
            details.append(f"@{u} หลบพ้น")
        elif st == 'dead':
            details.append(f"@{u} 💀ตาย")
        elif st == 'blocked':
            details.append(f"@{u} กัน(-{v['damage']})")
        elif st == 'ineffective':
            details.append(f"@{u} ป้องกันไร้ผล(-{v['damage']})")
        else:
            details.append(f"@{u} โดน(-{v['damage']})")

    detail_msg = ", ".join(details)
    if len(detail_msg) > 300:
        detail_msg = detail_msg[:297] + "..."

    boss_name = boss['name']
    chat_msg = f"💥 {boss_name} ใช้ท่า「{atk_name}」โจมตีหมู่! {detail_msg}"
    send_streamerbot_message(chat_msg)

    # Emit overlay events
    emit_to_overlay('combat_event', {
        'username': boss_name,
        'action': f"💥 ใช้ท่า {atk_name} โจมตีหมู่!",
        'damage': 'MASSIVE', 'is_crit': True,
        'boss_hp': boss['current_hp']
    })

    emit_to_overlay('party_update', get_party_data(boss))
    return {
        'aoe_attack': True,
        'victims_info': victims_info,
        'party_wipe': (alive_count == 0 and len(participants) > 0)
    }
