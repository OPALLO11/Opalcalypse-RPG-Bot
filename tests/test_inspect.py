import requests

OVERLAY_URL = "http://127.0.0.1:5000/internal/emit"


def emit(event, data):
    try:
        resp = requests.post(OVERLAY_URL, json={"event": event, "data": data})
        print(f"Sent {event} - Status: {resp.status_code}")
    except Exception as e:
        print(f"Error connecting to overlay: {e}")


def main():
    mock_payload = {
        "username": "opallo11",
        "character_name": "Opallo The Bold",
        "class": "warrior",
        "icon": "⚔️",
        "level": 15,
        "equipped_weapon": {
            "item_id": "w_r_3",
            "name": "Rusty Dagger",
            "enhancement_level": 5
        },
        "equipped_armor": {
            "item_id": "armor_01",
            "name": "Iron Plate",
            "enhancement_level": 2
        },
        "equipped_accessory": None
    }

    print("Emitting mock inspect_player event to overlay...")
    emit("inspect_player", mock_payload)


if __name__ == "__main__":
    main()
