"""
Shop system — buying and selling items.

Extracted from database.py so that game/business logic lives
in the game layer rather than the persistence layer.
"""

import json
import os
from database import db
from .helpers import find_item_data, get_level_requirement


# ---------------------------------------------------------------------------
# Buy
# ---------------------------------------------------------------------------

SHOP_COSTS = {
    "potion": 500,
    "scroll_t1": 10000,
    "scroll_t2": 50000,
    "scroll_t3": 100000,
}


def buy_shop_item(username, item_name):
    """
    Process a shop purchase for *username*.

    Returns (success: bool, message: str).
    """
    item_name = item_name.lower().strip()

    player = db.get_player(username)
    if not player:
        return False, "You need to !register first."

    try:
        class_levels = player.get('class_levels', {})
        if isinstance(class_levels, str):
            class_levels = json.loads(class_levels)
        cls_name = player.get('class', 'warrior').lower()
        lvl = class_levels.get(cls_name, {}).get('level', player.get('level', 1))
    except Exception:
        lvl = player.get('level', 1)

    if item_name not in SHOP_COSTS:
        return False, "Item not found in shop. Available: Potion, scroll_t1, scroll_t2, scroll_t3"

    if item_name.startswith("scroll") and lvl < 11:
        return False, "ใบกันแตกซื้อได้เมื่อเลเวล 11 ขึ้นไปครับ"

    cost = SHOP_COSTS[item_name]

    if player["gold"] < cost:
        return False, f"Not enough gold. Costs {cost}G, you have {player['gold']}G."

    new_gold = player["gold"] - cost

    if item_name == "scroll_t1":
        db.update_player(player["id"], {'gold': new_gold, 'scroll_t1': player.get('scroll_t1', 0) + 1})
        msg = f"Successfully bought 1 Basic Scroll! (Remaining Gold: {new_gold}G)"
    elif item_name == "scroll_t2":
        db.update_player(player["id"], {'gold': new_gold, 'scroll_t2': player.get('scroll_t2', 0) + 1})
        msg = f"Successfully bought 1 Blessed Scroll! (Remaining Gold: {new_gold}G)"
    elif item_name == "scroll_t3":
        db.update_player(player["id"], {'gold': new_gold, 'scroll_t3': player.get('scroll_t3', 0) + 1})
        msg = f"Successfully bought 1 Divine Scroll! (Remaining Gold: {new_gold}G)"
    elif item_name == "potion":
        from game.logic import calculate_player_stats
        stats = calculate_player_stats(player)
        db.update_player(player["id"], {
            'gold': new_gold,
            'hp': stats["max_hp"],
            'mp': stats["max_mp"],
        })
        msg = f"Successfully bought and consumed Potion! Restored to Max HP/MP! (Remaining Gold: {new_gold}G)"

    return True, msg


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------

_SELL_BASE_PRICES = {"R": 100, "SR": 500, "SSR": 2500, "UR": 10000}


def sell_items(owner_id, target_item_name=None, target_tier=None):
    """
    Sell items from a player's inventory.

    Either sell a specific item by name (target_item_name) or bulk-sell an
    entire tier (target_tier, limited to R/SR for safety).

    Returns (success: bool, message: str).
    """
    items_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'items.json')
    try:
        with open(items_path, 'r', encoding='utf-8') as f:
            ITEMS = json.load(f)
    except Exception:
        ITEMS = {}

    def _get_item_data(i_id):
        for cat in ITEMS.values():
            for t_items in cat.values():
                for itm in t_items:
                    if itm['id'] == i_id:
                        return itm
        return None

    # Get player equipment to avoid selling equipped items
    player = db.get_player_by_id(owner_id)
    if not player:
        return False, "Player not found."

    equipped_ids = [
        player.get('equipped_weapon'),
        player.get('equipped_armor'),
        player.get('equipped_accessory'),
    ]
    equipped_ids = [eid for eid in equipped_ids if eid]

    # Get all owned items via repository
    owned_items = db.items.get_items_by_owner(owner_id)

    items_to_sell = []

    if target_item_name:
        search_name = target_item_name.lower()
        candidates = []
        for row in owned_items:
            if row['id'] in equipped_ids:
                continue
            i_data = _get_item_data(row['item_id'])
            if not i_data:
                continue
            if search_name == i_data['name'].lower() or search_name == str(row['id']):
                candidates.append((row, i_data))

        if not candidates:
            return False, f"ไม่พบไอเทม '{target_item_name}' ที่ยังไม่ได้สวมใส่ครับ (ถ้าใส่อยู่ต้องถอดก่อน)"

        candidates.sort(key=lambda x: x[0]['enhancement_level'] or 0)
        items_to_sell.append(candidates[0])

    elif target_tier:
        target_t = target_tier.upper()
        if target_t not in ('R', 'SR'):
            return False, "ระบบอนุญาตให้ขายเหมาเฉพาะเกรด R และ SR เท่านั้นครับ เพื่อป้องกันการเผลอขายของแรร์ทิ้ง"

        for row in owned_items:
            if row['id'] in equipped_ids:
                continue
            i_data = _get_item_data(row['item_id'])
            if not i_data:
                continue
            if i_data.get('tier', 'R') == target_t:
                items_to_sell.append((row, i_data))

        if not items_to_sell:
            return False, f"ไม่พบไอเทมเกรด {target_t} ที่ไม่ได้สวมใส่ในตัวคุณครับ"

    if not items_to_sell:
        return False, "ไม่มีไอเทมที่สามารถขายได้"

    total_gold = 0
    ids_to_delete = []

    for row, i_data in items_to_sell:
        tier = i_data.get('tier', 'R')
        base_price = _SELL_BASE_PRICES.get(tier, 100)
        enh_lvl = row['enhancement_level'] or 0
        price = int(base_price * (1 + (enh_lvl * 0.5)))

        total_gold += price
        ids_to_delete.append(row['id'])

    # Delete items and add gold via repositories
    db.items.delete_items(ids_to_delete)
    db.add_player_gold(owner_id, total_gold)

    count = len(items_to_sell)
    if target_item_name:
        item_name_display = items_to_sell[0][1]['name']
        enh = items_to_sell[0][0]['enhancement_level'] or 0
        enh_str = f"+{enh} " if enh > 0 else ""
        return True, f"ขาย {enh_str}{item_name_display} สำเร็จ! ได้รับเงิน {total_gold} Gold 💰"
    else:
        return True, f"ขายเหมาไอเทมเกรด {target_tier.upper()} จำนวน {count} ชิ้น สำเร็จ! ได้รับเงินทั้งหมด {total_gold} Gold 💰"

