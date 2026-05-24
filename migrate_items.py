import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'database.db')

def migrate_items():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Ensure enhancement_level column exists
    try:
        c.execute("ALTER TABLE items ADD COLUMN enhancement_level INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    c.execute("SELECT * FROM items")
    all_items = c.fetchall()
    
    # owner_id -> {item_id: [rows...]}
    player_inventory = {}
    for row in all_items:
        owner_id = row['owner_id']
        item_id = row['item_id']
        
        if owner_id not in player_inventory:
            player_inventory[owner_id] = {}
            
        if item_id not in player_inventory[owner_id]:
            player_inventory[owner_id][item_id] = []
            
        player_inventory[owner_id][item_id].append(dict(row))
        
    for owner_id, items_dict in player_inventory.items():
        for item_id_str, items in items_dict.items():
            if len(items) > 1:
                # Sort by id to keep the oldest one
                items.sort(key=lambda x: x['id'])
                kept_item = items[0]
                deleted_items = items[1:]
                
                # Calculate new enhancement
                current_enh = kept_item.get('enhancement_level') or 0
                added_enh = len(deleted_items)
                new_enh = min(9, current_enh + added_enh)
                
                # Update kept item
                c.execute("UPDATE items SET enhancement_level = ? WHERE id = ?", (new_enh, kept_item['id']))
                
                # Delete old items and re-link equipment
                for del_item in deleted_items:
                    del_id = del_item['id']
                    
                    c.execute("DELETE FROM items WHERE id = ?", (del_id,))
                    
                    c.execute("UPDATE players SET equipped_weapon = ? WHERE id = ? AND equipped_weapon = ?", (kept_item['id'], owner_id, del_id))
                    c.execute("UPDATE players SET equipped_armor = ? WHERE id = ? AND equipped_armor = ?", (kept_item['id'], owner_id, del_id))
                    c.execute("UPDATE players SET equipped_accessory = ? WHERE id = ? AND equipped_accessory = ?", (kept_item['id'], owner_id, del_id))
                    
                print(f"Player {owner_id} merged {len(items)} '{item_id_str}' items into -> +{new_enh}")
                
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate_items()
