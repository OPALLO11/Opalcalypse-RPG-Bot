import sys

import requests

OVERLAY_URL = "http://127.0.0.1:5000/internal/emit"


def emit(event, data):
    try:
        resp = requests.post(OVERLAY_URL, json={"event": event, "data": data})
        print(f"Sent {event} - Status: {resp.status_code}")
    except Exception as e:
        print(f"Error connecting to overlay: {e}")


def main():
    count = 10
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except ValueError:
            pass

    classes = [
        {"class": "warrior", "icon": "⚔️"},
        {"class": "mage", "icon": "🔮"},
        {"class": "rogue", "icon": "⚔️"},
        {"class": "priest", "icon": "💖"}
    ]

    party_data = []
    for i in range(1, count + 1):
        cls_info = classes[(i - 1) % len(classes)]
        party_data.append({
            "id": i,
            "username": f"player_{i}",
            "character_name": f"Hero Name {i}",
            "class": cls_info["class"],
            "icon": cls_info["icon"],
            "level": i * 2,
            "hp": 500 + i * 50,
            "max_hp": 1000 + i * 50,
            "mp": 20 + i * 10,
            "max_mp": 100 + i * 10,
            "is_dead": False,
            "is_defending": i % 3 == 0
        })

    print(f"Emitting party update with {count} players...")
    emit("party_update", party_data)


if __name__ == "__main__":
    main()
