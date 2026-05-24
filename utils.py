import os
import requests
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

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
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
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

def send_streamerbot_message(message):
    """Send message to Twitch chat using Streamer.bot HTTP API (Method 2 for Broadcaster message)"""
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
