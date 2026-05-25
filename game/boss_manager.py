import random
import datetime
from .logic import BOSSES, calculate_boss_hp
from database import db

class BossManager:
    def __init__(self):
        self.boss_state = {}

        
    def spawn_boss(self, active_players_count, boss_type='normal'):
        if boss_type == 'normal':
            import json, os
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                game_config = config.get('game', {})
                enable_monthly = game_config.get('enable_monthly_boss', False)
                monthly_chance = game_config.get('monthly_boss_chance', 0.05)
                enable_weekly = game_config.get('enable_weekly_boss', False)
                weekly_chance = game_config.get('weekly_boss_chance', 0.1)
                
                roll = random.random()
                if enable_monthly and roll < monthly_chance:
                    boss_type = 'monthly'
                elif enable_weekly and roll < (monthly_chance + weekly_chance):
                    boss_type = 'weekly'
            except Exception as e:
                print(f"Error checking boss spawn config: {e}")

        # Check if boss_type is actually a specific ID
        if str(boss_type).isdigit():
            boss = None
            target_id = int(boss_type)
            for cat, pool_list in BOSSES.items():
                for b in pool_list:
                    if b['id'] == target_id:
                        boss = b
                        boss_type = cat
                        break
                if boss:
                    break
            if not boss:
                return None
        else:
            pool = BOSSES.get(boss_type, [])
            if not pool:
                return None
            boss = random.choice(pool)

        hp = calculate_boss_hp(boss['base_hp'], active_players_count)
        
        # In JSON database, we just overwrite the active instance or mark old as escaped
        old_boss = db.get_active_boss()
        if old_boss and old_boss.get('status') == 'active':
            db.update_boss(old_boss['instance_id'], {'status': 'escaped'})
            
        boss_data = {
            'boss_id': boss['id'],
            'name': boss['name'],
            'type': boss_type,
            'element': boss['element'],
            'base_hp': boss['base_hp'],
            'base_def': boss.get('base_def', 0),
            'current_hp': hp,
            'max_hp': hp,
            'weakness': boss.get('weakness', []),
            'resist': boss.get('resist', []),
            'image_url': boss.get('image_url', ''),
            'participants': []
        }
        
        db.set_active_boss(boss_data)
        active_boss = db.get_active_boss()
        if active_boss:
            try:
                from utils import write_obs_boss_files
                write_obs_boss_files(active_boss['name'], active_boss['current_hp'], active_boss['max_hp'])
            except Exception as e:
                print(f"Error calling write_obs_boss_files in spawn_boss: {e}")
                
            self.boss_state[active_boss['instance_id']] = {
                'charge': 0,
                'is_charging': False,
                'target_quota': 0,
                'commands_counted': 0,
                'defending_players': set(),
                'next_attack': None
            }
        return active_boss
        
    def get_current_boss(self):
        boss = db.get_active_boss()
        if boss and boss.get('status') == 'active':
            if boss['instance_id'] not in self.boss_state:
                self.boss_state[boss['instance_id']] = {
                    'charge': 0,
                    'is_charging': False,
                    'target_quota': 0,
                    'commands_counted': 0,
                    'defending_players': set(),
                    'next_attack': None
                }
            return boss
        return None

    def take_damage(self, amount, player_id):
        boss = self.get_current_boss()
        if not boss:
            return False, 0
            
        new_hp = max(0, boss['current_hp'] - amount)
        updated_boss = db.update_boss(boss['instance_id'], {'current_hp': new_hp})
        
        if updated_boss:
            try:
                from utils import write_obs_boss_files
                write_obs_boss_files(updated_boss['name'], updated_boss['current_hp'], updated_boss['max_hp'])
            except Exception as e:
                print(f"Error calling write_obs_boss_files in take_damage: {e}")
                
        is_dead = (new_hp == 0)
        return is_dead, new_hp 
        
    def record_action(self, boss, player_id, action_type):
        instance_id = boss['instance_id']
        state = self.boss_state[instance_id]
        
        result = {'warning': False, 'aoe_attack': False, 'defenders': set()}
        
        if state['is_charging']:
            if action_type == 'def':
                state['defending_players'].add(player_id)
            return result
            
        # Normal accumulation logic
        if action_type == 'attack':
            state['charge'] += random.randint(10, 14)
        elif action_type == 'skill':
            state['charge'] += 34
        elif action_type == 'ultimate':
            state['charge'] += 100
        elif action_type == 'def':
            pass
            
        if state['charge'] >= 100:
            state['is_charging'] = True
            state['charge_start_time'] = datetime.datetime.now()
            state['defending_players'] = set()
            
            # Select random skill
            from .logic import BOSSES
            static_boss = None
            for cat, pool in BOSSES.items():
                for b in pool:
                    if str(b['id']) == str(boss['boss_id']):
                        static_boss = b
                        break
                if static_boss:
                    break
                    
            skills = static_boss.get('skills', []) if static_boss else []
            if skills:
                chosen_skill = random.choice(skills)
            else:
                chosen_skill = {"name": "Mighty Strike", "type": "physical", "description": "โจมตีอย่างรุนแรง"}
                
            state['next_attack'] = chosen_skill
            result['next_attack'] = chosen_skill
            result['warning'] = True
            
        return result

boss_manager = BossManager()
