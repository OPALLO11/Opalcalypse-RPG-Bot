import random

from .enhancement import give_item_or_enhance
from .logic import ITEMS


def roll_item(tier):
    pool = []
    for cat in ['weapons', 'armors', 'accessories']:
        items_in_tier = ITEMS.get(cat, {}).get(tier, [])
        for item in items_in_tier:
            pool.append((item, item.get('drop_weight', 10)))

    if not pool:
        return None

    total_weight = sum(w for _, w in pool)
    r = random.uniform(0, total_weight)
    upto = 0
    for item, w in pool:
        if upto + w >= r:
            return item
        upto += w
    return pool[-1][0]


def distribute_loot(boss_name, participants_list):
    """
    Distributes loot among participants when boss is defeated.
    participants_list format: [{'id': "1", 'rank': 1, 'damage': 1500}, ...]
    returns dict marking which player got what item.
    """
    results = {}
    base_rates = {'SSR': 0.05, 'SR': 0.30, 'R': 0.65}

    for p in participants_list:
        pid = p['id']
        rank = p['rank']

        mult = 1.0
        if rank == 1:
            mult = 2.0
        elif rank <= 3:
            mult = 1.5
        elif rank <= 5:
            mult = 1.2

        roll_val = random.random()

        ssr_chance = base_rates['SSR'] * mult
        sr_chance = base_rates['SR'] * mult + ssr_chance

        tier_won = None
        if roll_val <= ssr_chance:
            tier_won = 'SSR'
        elif roll_val <= sr_chance:
            tier_won = 'SR'
        elif roll_val <= (base_rates['R'] * mult + sr_chance):
            tier_won = 'R'

        if tier_won:
            item = roll_item(tier_won)
            if item:
                # Add or enhance via the dedicated enhancement module
                item_doc = give_item_or_enhance(pid, item, boss_name)
                item_doc['item_name'] = item.get('name', 'Unknown')
                item_doc['tier'] = tier_won
                results[pid] = item_doc
    return results
