import random
from datetime import datetime
from database import db
from utils import emit_to_overlay, send_streamerbot_message

CHALLENGE_TEMPLATES = [
    {
        "type": "damage",
        "description": "ทำดาเมจรวมใส่บอสให้ถึง {target:,} ดาเมจ",
        "target_value": 500000,
        "reward_type": "gold",
        "reward_amount": 1000
    },
    {
        "type": "crits",
        "description": "โจมตีติดคริติคอลรวมให้ถึง {target} ครั้ง",
        "target_value": 50,
        "reward_type": "both",
        "reward_amount": 500  # 500 Gold and 500 EXP
    },
    {
        "type": "boss_kills",
        "description": "ปราบมอนสเตอร์/บอสให้ถึง {target} ตัว",
        "target_value": 5,
        "reward_type": "gold",
        "reward_amount": 1500
    }
]

def init_challenges():
    """Checks active challenge on startup. Resets if older than 12 hours."""
    active = db.get_active_challenge()
    if active:
        # Check expiration (12 hours)
        created_at = datetime.fromisoformat(active['created_at'])
        delta = datetime.now() - created_at
        if delta.total_seconds() > 12 * 3600:
            print(f"[Challenge] Active challenge ID {active['id']} expired after {delta.total_seconds()/3600:.1f} hours.")
            spawn_challenge()
        else:
            desc_safe = active['description'].encode('ascii', 'backslashreplace').decode('ascii')
            print(f"[Challenge] Active challenge loaded: ID {active['id']} - {desc_safe} ({active['current_value']}/{active['target_value']})")
            # Emit active challenge state to overlay
            emit_to_overlay('challenge_update', active)
    else:
        print("[Challenge] No active challenge found. Spawning one.")
        spawn_challenge()

def spawn_challenge():
    """Forces spawn of a new random challenge."""
    template = random.choice(CHALLENGE_TEMPLATES)
    
    # Scale targets slightly based on active registered players (if desired, or keep templates solid)
    target = template['target_value']
    desc = template['description'].format(target=target)
    
    challenge_id = db.create_challenge(
        challenge_type=template['type'],
        description=desc,
        target_val=target,
        reward_type=template['reward_type'],
        reward_amt=template['reward_amount']
    )
    
    active = db.get_active_challenge()
    if active:
        emit_to_overlay('challenge_update', active)
        reward_desc = get_reward_desc(active['reward_type'], active['reward_amount'])
        send_streamerbot_message(
            f"🏆 ความท้าทายประจำสตรีมเริ่มต้นขึ้นแล้ว! เป้าหมาย: {active['description']} | รางวัล: {reward_desc} (ร่วมมือกันผ่านการพิมพ์ !attack)"
        )
        return active
    return None

def get_reward_desc(reward_type, reward_amount):
    if reward_type == 'gold':
        return f"{reward_amount:,} Gold"
    elif reward_type == 'exp':
        return f"{reward_amount:,} EXP"
    elif reward_type == 'both':
        return f"{reward_amount:,} Gold & {reward_amount:,} EXP"
    return "Unknown"

def track_progress(challenge_type, amount=1):
    """Tracks progress for the active challenge, updating DB and emitting sockets."""
    active = db.get_active_challenge()
    if not active:
        return
        
    # Check expiration before updating
    created_at = datetime.fromisoformat(active['created_at'])
    delta = datetime.now() - created_at
    if delta.total_seconds() > 12 * 3600:
        print(f"[Challenge] Active challenge ID {active['id']} expired during tracking. Spawning new one.")
        spawn_challenge()
        return

    if active['challenge_type'] == challenge_type and active['status'] == 'active':
        updated = db.update_challenge_progress(active['id'], amount)
        if updated:
            emit_to_overlay('challenge_update', updated)
            
            # Check if it was completed in this update
            if updated['status'] == 'completed':
                distribute_rewards(updated)

def distribute_rewards(challenge):
    """Query participants and award them Gold/EXP."""
    participants = db.get_challenge_participants(challenge['created_at'])
    if not participants:
        send_streamerbot_message(
            f"🎉 ความท้าทายสำเร็จแล้ว: {challenge['description']}! แต่ไม่มีผู้เล่นเข้าร่วมในช่วงเวลานี้ เลยไม่มีการแจกรางวัล"
        )
        return
        
    gold_reward = challenge['reward_amount'] if challenge['reward_type'] in ('gold', 'both') else 0
    exp_reward = challenge['reward_amount'] if challenge['reward_type'] in ('exp', 'both') else 0
    
    # Import add_exp here to avoid circular imports
    from game.logic import add_exp
    
    rewarded_names = []
    for pid in participants:
        pinfo = db.get_player_by_id(pid)
        if pinfo:
            name = pinfo.get('character_name') or pinfo.get('username')
            rewarded_names.append(name)
            
            if gold_reward > 0:
                db.add_player_gold(pid, gold_reward)
            if exp_reward > 0:
                add_exp(pid, exp_reward)
                
    reward_desc = get_reward_desc(challenge['reward_type'], challenge['reward_amount'])
    players_list = ", ".join(rewarded_names[:5])
    if len(rewarded_names) > 5:
        players_list += f" และอีก {len(rewarded_names) - 5} คน"
        
    send_streamerbot_message(
        f"🎉 สำเร็จ! ความท้าทายประจำสตรีมสำเร็จแล้ว: {challenge['description']}! ผู้ร่วมชะตากรรม {len(rewarded_names)} คน ({players_list}) ได้รับรางวัลคนละ {reward_desc}!"
    )
