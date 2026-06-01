import json
from sqlalchemy import text
from .models import Base
from .connection import engine

def run_migrations():
    """Apply schema updates and perform data migrations to SQLAlchemy ORM structure."""
    print("[DB Migration] Ensuring tables exist via SQLAlchemy...")
    Base.metadata.create_all(engine)
    
    with engine.begin() as conn:
        # 1. Drop cooldowns
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='cooldowns'"))
        if result.fetchone():
            print("[DB Migration] Dropping legacy cooldowns table...")
            conn.execute(text("DROP TABLE cooldowns"))
            
        # 2. Migrate class_levels if they exist in players table
        res = conn.execute(text("PRAGMA table_info(players)"))
        columns = [row[1] for row in res]
        if 'class_levels' in columns:
            count_res = conn.execute(text("SELECT COUNT(*) FROM player_class_levels"))
            if count_res.scalar() == 0:
                print("[DB Migration] Migrating player class_levels to relational table...")
                players = conn.execute(text("SELECT id, class_levels, level, exp, class FROM players")).fetchall()
                for p_id, class_levels_str, p_level, p_exp, p_class in players:
                    if not class_levels_str:
                        class_levels_str = "{}"
                    try:
                        c_levels = json.loads(class_levels_str)
                    except Exception:
                        c_levels = {}
                        
                    p_class_low = (p_class or 'warrior').lower()
                    if p_class_low not in c_levels:
                        c_levels[p_class_low] = {'level': p_level or 1, 'exp': p_exp or 0}
                    
                    for c_name, c_data in c_levels.items():
                        conn.execute(text(
                            "INSERT INTO player_class_levels (player_id, class_name, level, exp) "
                            "VALUES (:pid, :cname, :lvl, :exp)"
                        ), {
                            "pid": p_id,
                            "cname": c_name,
                            "lvl": c_data.get('level', 1),
                            "exp": c_data.get('exp', 0)
                        })
                        
        # 3. Migrate boss participants if they exist
        res = conn.execute(text("PRAGMA table_info(bosses)"))
        columns = [row[1] for row in res]
        if 'participants' in columns:
            count_res = conn.execute(text("SELECT COUNT(*) FROM boss_participants"))
            if count_res.scalar() == 0:
                print("[DB Migration] Migrating boss participants to relational table...")
                bosses = conn.execute(text("SELECT instance_id, participants FROM bosses")).fetchall()
                for b_id, parts_str in bosses:
                    if not parts_str:
                        continue
                    try:
                        p_ids = json.loads(parts_str)
                    except:
                        p_ids = []
                    
                    # Dedup ids just in case
                    p_ids = set(p_ids)
                    for p_id in p_ids:
                        conn.execute(text(
                            "INSERT INTO boss_participants (boss_instance_id, player_id) VALUES (:bid, :pid)"
                        ), {"bid": b_id, "pid": p_id})
                        
    print("[DB Migration] Schema is up to date.")
