import time

import requests

OVERLAY_URL = "http://127.0.0.1:5000/internal/emit"


def emit(event, data):
    try:
        resp = requests.post(OVERLAY_URL, json={"event": event, "data": data})
        print(f"Sent {event} - Status: {resp.status_code}")
    except Exception as e:
        print(f"Error connecting to overlay: {e}")


if __name__ == "__main__":
    print('Testing Boss Spawn...')
    boss_data = {
        "instance_id": 1,
        "boss_id": "b1",
        "name": "Slime King",
        "level": 1,
        "max_hp": 1500,
        "current_hp": 1500,
        "status": "active"
    }
    emit("boss_update", boss_data)
    time.sleep(2)

    print('Testing Combat Log...')
    emit("combat_event", {
        "username": "opallo11",
        "action": "Basic Attack",
        "damage": 150,
        "is_crit": False
    })
    time.sleep(1)

    boss_data["current_hp"] -= 150
    emit("boss_update", boss_data)
    time.sleep(1)

    print('Testing Critical Hit...')
    emit("combat_event", {
        "username": "me_0_w__0",
        "action": "Fireball",
        "damage": 450,
        "is_crit": True
    })

    boss_data["current_hp"] -= 450
    emit("boss_update", boss_data)
    time.sleep(2)

    print('Testing Party Update...')
    party_data = [
        {
            "id": 1,
            "username": "opallo11",
            "character_name": "Opallo The Bold",
            "class": "warrior",
            "icon": "⚔️",
            "level": 15,
            "hp": 850,
            "max_hp": 1200,
            "mp": 30,
            "max_mp": 50,
            "is_dead": False,
            "is_defending": False
        },
        {
            "id": 2,
            "username": "me_0_w__0",
            "character_name": "Meow Mage",
            "class": "mage",
            "icon": "🔮",
            "level": 14,
            "hp": 400,
            "max_hp": 800,
            "mp": 10,
            "max_mp": 120,
            "is_dead": False,
            "is_defending": True
        },
        {
            "id": 3,
            "username": "priest_healer",
            "character_name": "Holy Healer",
            "class": "priest",
            "icon": "💖",
            "level": 12,
            "hp": 0,
            "max_hp": 900,
            "mp": 150,
            "max_mp": 200,
            "is_dead": True,
            "is_defending": False
        }
    ]
    emit("party_update", party_data)
    time.sleep(3)

    print('Testing Boss Defeat...')
    emit("boss_defeated", {"winner": "opallo11"})
    time.sleep(2)

    print('Testing AI Art Display...')
    emit("show_art", {
        "username": "viewer99",
        "bits": 500,
        "prompt": "A magical forest with floating crystals",
        "image_url": "https://placehold.co/600x400/png"  # Dummy image
    })
    print("Test complete! Check your browser window.")
