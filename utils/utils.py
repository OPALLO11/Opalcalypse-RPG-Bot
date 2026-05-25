import os
import requests
import json

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')

def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config in utils: {e}")
        return {}

def emit_to_overlay(event_name, data):
    try:
        host = os.environ.get('FLASK_HOST', '127.0.0.1')
        port = os.environ.get('FLASK_PORT', '5000')
        url = f"http://{host}:{port}/internal/emit"
        resp = requests.post(url, json={"event": event_name, "data": data}, timeout=1)
        if resp.status_code != 200:
            print(f"[Overlay Error] Failed to emit event {event_name}: Status {resp.status_code}")
    except Exception as e:
        print(f"[Overlay Error] Failed to emit event {event_name}: {e}")

def write_obs_boss_files(boss_name, current_hp, max_hp):
    """Write boss details to local text files for OBS GDI+ text source integration"""
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        name_path = os.path.join(data_dir, 'obs_boss_name.txt')
        hp_path = os.path.join(data_dir, 'obs_boss_hp.txt')
        
        with open(name_path, 'w', encoding='utf-8') as f:
            f.write(boss_name)
            
        pct = (current_hp / max_hp) * 100 if max_hp > 0 else 0
        hp_str = f"HP: {current_hp:,} / {max_hp:,} ({pct:.1f}%)"
        
        with open(hp_path, 'w', encoding='utf-8') as f:
            f.write(hp_str)
    except Exception as e:
        print(f"Error writing OBS boss text files: {e}")

_bot_instance = None
_loop_instance = None

def set_bot(bot, loop):
    global _bot_instance, _loop_instance
    _bot_instance = bot
    _loop_instance = loop

def send_streamerbot_message(message):
    """Send message to Twitch chat using RPGBot if active; fallback to Streamer.bot HTTP API"""
    global _bot_instance, _loop_instance
    
    if _bot_instance and _loop_instance:
        config = load_config()
        twitch_config = config.get('twitch', {})
        channel_name = twitch_config.get('channel') or os.environ.get('TWITCH_CHANNEL') or 'opallo11'
        
        async def _send():
            try:
                from game.helpers import split_message
                messages = split_message(message, max_len=400)
                
                channel = _bot_instance.get_channel(channel_name)
                if channel:
                    for msg in messages:
                        await channel.send(msg)
                    return True
                else:
                    print(f"[TwitchIO Send Error] Bot has not joined channel: {channel_name}")
                    return False
            except Exception as ex:
                print(f"[TwitchIO Send Exception] {ex}")
                return False
                
        import asyncio
        try:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
                
            if current_loop == _loop_instance:
                _loop_instance.create_task(_send())
            else:
                asyncio.run_coroutine_threadsafe(_send(), _loop_instance)
            return True
        except Exception as e:
            print(f"Error scheduling native Twitch message: {e}")
            
    # Original Streamer.bot fallback
    config = load_config()
    sb_config = config.get('streamerbot', {})
    if not sb_config.get('enabled', False):
        return False
        
    http_url = sb_config.get('http_url', 'http://127.0.0.1:8080/DoAction')
    action_name = sb_config.get('broadcaster_action_name', 'SendBroadcasterMessage')
    
    payload = {
        "action": {
            "name": action_name
        },
        "args": {
            "message": message
        }
    }
    
    try:
        res = requests.post(http_url, json=payload, timeout=2)
        success = res.status_code in (200, 204)
        safe_msg = message[:80].encode('ascii', 'backslashreplace').decode('ascii')
        if success:
            print(f"[HTTP->SB] Message sent successfully (status {res.status_code}): {safe_msg}")
        else:
            print(f"[HTTP->SB] Unexpected status {res.status_code} for message: {safe_msg}")
        return success
    except Exception as e:
        print(f"[HTTP->SB] Error sending message to Streamer.bot: {e}")
        return False
