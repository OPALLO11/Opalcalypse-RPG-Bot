"""
Shared game utility functions.

Centralizes frequently duplicated patterns:
- Item lookup by ID across the nested ITEMS structure
- Level requirement calculation for item tiers/enhancements
- Twitch message splitting for the 500-char limit
"""

from .logic import ITEMS


def find_item_data(item_id):
    """
    Search the ITEMS data for an item by its string ID.

    Returns:
        (item_dict, tier_str) if found, e.g. ({'id': 'sword_fire', 'name': 'Flame Sword', ...}, 'SR')
        (None, None) if not found.
    """
    for category in ITEMS.values():
        for tier_name, tier_items in category.items():
            for item in tier_items:
                if item['id'] == item_id:
                    return item, tier_name
    return None, None


def get_level_requirement(tier, enhancement_level=0):
    """
    Calculate the minimum player level required to use an item
    based on its rarity tier and enhancement level.

    Tier base levels:  R=1, SR=10, SSR=25, UR=50
    Enhancement bonus: +4..+6 adds 5,  +7..+9 adds 10
    """
    base = {'R': 1, 'SR': 10, 'SSR': 25, 'UR': 50}
    req = base.get(tier, 1)

    if 4 <= enhancement_level <= 6:
        req += 5
    elif enhancement_level >= 7:
        req += 10

    return req


def split_message(message, max_len=400):
    """
    Split a long message into chunks safe for Twitch chat (≤500 char limit).

    Splits on the last space before *max_len* whenever possible so words
    aren't broken mid-way.

    Returns:
        list[str] — one or more message chunks.
    """
    if len(message) <= max_len + 50:
        return [message]

    chunks = []
    remaining = message
    while len(remaining) > max_len:
        split_idx = remaining.rfind(' ', 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunks.append(remaining[:split_idx])
        remaining = remaining[split_idx:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
