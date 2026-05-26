"""
Item enhancement system.

Handles the give-or-enhance logic when a player receives a duplicate item:
- First copy → added to inventory
- Subsequent copies → auto-enhancement attempt with RNG, scroll protection,
  and break mechanics
"""

import random

from database import db


def give_item_or_enhance(owner_id, item_data, boss_name=""):
    """
    Give an item to a player. If they already own it, attempt enhancement instead.

    Enhancement rules:
      +1 through +6: guaranteed success
      +7: 60% base success rate
      +8: 40% base success rate
      +9: 20% base success rate
      +10 (max): duplicate converts to 500 EXP

    Protection scrolls (consumed automatically when available):
      scroll_t1 (Basic)   — for R/SR items:  75% chance to prevent break
      scroll_t2 (Blessed) — for SSR items:    100% prevent break, +10% success bonus
      scroll_t3 (Divine)  — for UR items:     100% prevent break, +25% success bonus

    Returns dict with 'action' key: 'new', 'enhanced', 'failed', 'failed_protected',
    'broke', or 'converted_exp'.
    """
    item_id = item_data.get('id', 'unknown') if isinstance(item_data, dict) else str(item_data)
    item_tier = item_data.get('tier', 'R') if isinstance(item_data, dict) else 'R'

    existing = db.items.find_existing_item(owner_id, item_id)

    if not existing:
        # Brand new item
        new_doc = db.add_item(owner_id, item_data, boss_name)
        new_doc["action"] = "new"
        return new_doc

    current_enh = existing['enhancement_level'] or 0
    if current_enh >= 9:
        # Maxed out — give EXP instead
        from game.logic import add_exp
        add_exp(owner_id, 500)
        return {"action": "converted_exp", "amount": 500, "item_id": item_id, "enhancement_level": 9}

    target_enh = current_enh + 1
    broke = False
    success = True

    # Base success rates for high-level enhancements
    base_rates = {7: 0.60, 8: 0.40, 9: 0.20}

    if target_enh >= 7:
        # Check for protection scrolls
        player = db.get_player_by_id(owner_id)
        scroll_consumed = False
        prevent_break = False
        success_bonus = 0.0

        if player:
            required_scroll = _get_required_scroll(item_tier)

            if required_scroll and player.get(required_scroll, 0) > 0:
                # Consume the scroll
                scroll_consumed = True
                db.update_player(owner_id, {
                    required_scroll: player[required_scroll] - 1
                })

                if required_scroll == 'scroll_t1':
                    if random.random() < 0.75:
                        prevent_break = True
                elif required_scroll == 'scroll_t2':
                    prevent_break = True
                    success_bonus = 0.10
                elif required_scroll == 'scroll_t3':
                    prevent_break = True
                    success_bonus = 0.25

        # Roll for success
        final_success_rate = base_rates.get(target_enh, 1.0) + success_bonus
        if random.random() > final_success_rate:
            success = False
            if not prevent_break:
                broke = True

        if success:
            db.items.update_enhancement(existing['id'], target_enh)
            return {"action": "enhanced", "item_id": item_id, "new_level": target_enh}
        elif scroll_consumed and not broke:
            return {"action": "failed_protected", "item_id": item_id, "attempted_level": target_enh}
        elif broke:
            db.items.delete_item(existing['id'])
            db.items.unequip_item_from_player(owner_id, existing['id'])
            return {"action": "broke", "item_id": item_id, "attempted_level": target_enh}
        else:
            return {"action": "failed", "item_id": item_id, "attempted_level": target_enh}
    else:
        # Guaranteed success for +1 through +6
        db.items.update_enhancement(existing['id'], target_enh)
        return {"action": "enhanced", "item_id": item_id, "new_level": target_enh}


def _get_required_scroll(item_tier):
    """Map an item tier to the scroll column needed for protection."""
    if item_tier in ('R', 'SR'):
        return 'scroll_t1'
    elif item_tier == 'SSR':
        return 'scroll_t2'
    elif item_tier == 'UR':
        return 'scroll_t3'
    return None
