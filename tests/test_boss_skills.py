import sys
import os
import unittest
import json
import random

# Add root folder to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from database import db
from game.boss_manager import boss_manager
from game.combat import process_action, trigger_boss_aoe_attack
from game.logic import BOSSES, calculate_player_stats

class TestBossSkills(unittest.TestCase):
    def setUp(self):
        # We will use temporary players to test
        # Clean up database test players
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_user_%'")
            conn.commit()
        finally:
            conn.close()

        # Create 4 test players with different classes
        db.create_player("test_user_warrior", "123451", "TestWarrior", "warrior")
        db.create_player("test_user_mage", "123452", "TestMage", "mage")
        db.create_player("test_user_rogue", "123453", "TestRogue", "rogue")
        db.create_player("test_user_priest", "123454", "TestPriest", "priest")

        # Level them up to level 5 and restore full HP/MP
        for username, cls in [("test_user_warrior", "warrior"), ("test_user_mage", "mage"), 
                              ("test_user_rogue", "rogue"), ("test_user_priest", "priest")]:
            p = db.get_player(username)
            levels = {cls: {"level": 5, "exp": 0}}
            
            # Temporary mock player dict to calculate stats
            mock_p = p.copy()
            mock_p['class_levels'] = json.dumps(levels)
            mock_p['level'] = 5
            
            s = calculate_player_stats(mock_p)
            db.update_player(p['id'], {
                "class_levels": json.dumps(levels),
                "level": 5,
                "hp": s['max_hp'],
                "mp": s['max_mp']
            })

        self.warrior = db.get_player("test_user_warrior")
        self.mage = db.get_player("test_user_mage")
        self.rogue = db.get_player("test_user_rogue")
        self.priest = db.get_player("test_user_priest")

    def tearDown(self):
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_user_%'")
            conn.execute("DELETE FROM cooldowns WHERE player_id IN (?, ?, ?, ?)", 
                         (self.warrior['id'], self.mage['id'], self.rogue['id'], self.priest['id']))
            conn.commit()
        finally:
            conn.close()

    def test_boss_skills_loaded(self):
        print("\n--- Testing Boss Skills Config Loading ---")
        # Check that all bosses have skills configured
        for cat, pool in BOSSES.items():
            for boss in pool:
                self.assertIn('skills', boss)
                skills = boss['skills']
                name_ascii = boss['name'].encode('ascii', 'backslashreplace').decode('ascii')
                print(f"Boss: {name_ascii} (Type: {cat}) has {len(skills)} skills.")
                if cat == 'normal':
                    self.assertEqual(len(skills), 3)
                elif cat == 'weekly':
                    self.assertEqual(len(skills), 4)
                elif cat == 'monthly':
                    self.assertEqual(len(skills), 5)
                
                # Check skill fields
                for skill in skills:
                    self.assertIn('name', skill)
                    self.assertIn('type', skill)
                    self.assertIn('description', skill)
                    self.assertIn(skill['type'], ['physical', 'magic', 'piercing'])

    def test_spawn_and_warning_skill_selection(self):
        print("\n--- Testing Spawn and Warning Skill Selection ---")
        # Spawn Forest Guardian (ID 1)
        boss = boss_manager.spawn_boss(1, boss_type='1')
        self.assertIsNotNone(boss)
        self.assertEqual(boss['name'], "Forest Guardian")
        
        # Test !spawn type mapping
        print(f"Spawned boss type: {boss['type']}")
        self.assertEqual(boss['type'], 'normal')

        # Trigger warning
        # Forest Guardian has 3 skills. We will trigger warning and verify
        # that a random skill is selected and saved to boss state.
        for i in range(5):
            # Reset charge
            state = boss_manager.boss_state[boss['instance_id']]
            state['charge'] = 0
            state['is_charging'] = False
            
            # Record ultimate to trigger warning
            res = boss_manager.record_action(boss, self.warrior['id'], 'ultimate')
            self.assertTrue(res['warning'])
            self.assertIn('next_attack', res)
            next_atk = res['next_attack']
            name_ascii = next_atk['name'].encode('ascii', 'backslashreplace').decode('ascii')
            print(f"Warning triggered. Selected Skill: {name_ascii} ({next_atk['type']})")
            
            # Verify it's stored in state
            self.assertEqual(state['next_attack'], next_atk)

    def test_defense_effectiveness(self):
        print("\n--- Testing Defense Effectiveness ---")
        # We will mock the boss next attack type and verify each class's defense
        boss = boss_manager.spawn_boss(4, boss_type='1') # active player count 4
        
        # Manually override boss base_hp to 10 in the DB so that the boss_atk damage is survivable
        db.update_boss(boss['instance_id'], {'base_hp': 10, 'max_hp': 10, 'current_hp': 10})
        
        # Reload boss
        boss = db.get_active_boss()
        state = boss_manager.boss_state[boss['instance_id']]

        # Test cases: (atk_type, expected_ineffective_classes)
        test_scenarios = [
            ('magic', ['warrior']),
            ('physical', ['mage', 'priest']),
            ('piercing', ['rogue'])
        ]

        for atk_type, ineffective_classes in test_scenarios:
            print(f"\nSimulating boss attack type: {atk_type}")
            # Reset state and set next attack type
            state['charge'] = 100
            state['is_charging'] = True
            state['commands_counted'] = 0
            state['target_quota'] = 4
            state['defending_players'] = set()
            state['next_attack'] = {'name': f'Test {atk_type.capitalize()} Skill', 'type': atk_type}

            # Restore players' HP to max before each scenario
            for p_name in ["test_user_warrior", "test_user_mage", "test_user_rogue", "test_user_priest"]:
                p = db.get_player(p_name)
                s = calculate_player_stats(p)
                db.update_player_hp(p['id'], s['max_hp'])

            # All 4 players defend
            # Clear cooldowns first
            db.clear_cooldown(self.warrior['id'], 'respawn')
            db.clear_cooldown(self.mage['id'], 'respawn')
            db.clear_cooldown(self.rogue['id'], 'respawn')
            db.clear_cooldown(self.priest['id'], 'respawn')

            # Clear def cooldowns too
            db.clear_cooldown(self.warrior['id'], 'def')
            db.clear_cooldown(self.mage['id'], 'def')
            db.clear_cooldown(self.rogue['id'], 'def')
            db.clear_cooldown(self.priest['id'], 'def')

            # Reload local player variables to get fresh HP
            p_w = db.get_player("test_user_warrior")
            p_m = db.get_player("test_user_mage")
            p_r = db.get_player("test_user_rogue")
            p_p = db.get_player("test_user_priest")

            # Defend using process_action
            res_w = process_action(p_w, 'def', 'parry')
            res_m = process_action(p_m, 'def', 'barrier')
            res_r = process_action(p_r, 'def', 'dodge')
            res_p = process_action(p_p, 'def', 'absorb')

            # Check that all def actions succeeded
            self.assertTrue(res_w['success'], f"Warrior def failed: {res_w.get('message')}")
            self.assertTrue(res_m['success'], f"Mage def failed: {res_m.get('message')}")
            self.assertTrue(res_r['success'], f"Rogue def failed: {res_r.get('message')}")
            self.assertTrue(res_p['success'], f"Priest def failed: {res_p.get('message')}")

            # Trigger the AOE attack manually
            aoe_res = asyncio.run(trigger_boss_aoe_attack(boss))
            self.assertTrue(aoe_res['aoe_attack'])

            # Inspect victims info
            victims = aoe_res['victims_info']
            for v in victims:
                username = v['username']
                status = v['status']
                dmg = v['damage']
                
                # Extract class from username
                p_cls = username.replace('test_user_', '')
                print(f"Player: {username} ({p_cls}), Status: {status}, Damage Taken: {dmg}")
                
                if p_cls in ineffective_classes:
                    # Defense should be ineffective
                    self.assertEqual(status, 'ineffective', f"Class {p_cls} defense should be ineffective against {atk_type}")
                else:
                    # Defense should be effective: blocked or dodged
                    self.assertIn(status, ['blocked', 'dodged'], f"Class {p_cls} defense should be effective against {atk_type}")

    def test_party_wipe_preserves_participants_and_sets_hp_to_zero(self):
        print("\n--- Testing Party Wipe and HP Zero for Dead Players ---")
        # Spawn Forest Guardian (ID 1)
        boss = boss_manager.spawn_boss(2, boss_type='1')
        db.update_boss(boss['instance_id'], {'base_hp': 999999, 'max_hp': 999999, 'current_hp': 999999})
        boss = db.get_active_boss()
        
        state = boss_manager.boss_state[boss['instance_id']]
        state['charge'] = 100
        state['is_charging'] = True
        state['commands_counted'] = 0
        state['target_quota'] = 2
        state['defending_players'] = set()
        state['next_attack'] = {'name': 'Super Magic Blast', 'type': 'magic'}
        
        # Clear cooldowns
        db.clear_cooldown(self.warrior['id'], 'respawn')
        db.clear_cooldown(self.mage['id'], 'respawn')
        
        # Two players do actions instead of defending (so they take undefended fatal damage)
        p_w = db.get_player("test_user_warrior")
        p_m = db.get_player("test_user_mage")
        
        res_w = process_action(p_w, 'attack')
        res_m = process_action(p_m, 'attack')
        
        self.assertTrue(res_w['success'])
        self.assertTrue(res_m['success'])
        
        # Trigger the AOE attack manually (fetch latest boss data to capture participants)
        from game.combat import trigger_boss_aoe_attack
        import asyncio
        boss = boss_manager.get_current_boss()
        aoe_res = asyncio.run(trigger_boss_aoe_attack(boss))
        self.assertTrue(aoe_res['aoe_attack'])
        self.assertTrue(aoe_res.get('party_wipe'))
        
        # Check database: boss participants should NOT be empty
        boss_after = db.get_active_boss()
        self.assertIn(self.warrior['id'], boss_after['participants'])
        self.assertIn(self.mage['id'], boss_after['participants'])
        
        # Check get_party_data(boss_after) returns both players with hp=0 and is_dead=True
        from game.combat import get_party_data
        party = get_party_data(boss_after)
        self.assertEqual(len(party), 2)
        for p in party:
            self.assertEqual(p['hp'], 0)
            self.assertTrue(p['is_dead'])
            print(f"Party Overlay: Player {p['character_name']} HP is {p['hp']} (is_dead: {p['is_dead']})")
            
        # Check stats command HP is 0
        p_w_dead = db.get_player("test_user_warrior")
        # Run the stats logic:
        from game.combat import check_cooldown
        alive, cd = check_cooldown(p_w_dead['id'], 'respawn')
        self.assertFalse(alive)
        current_hp = 0 if not alive else p_w_dead.get('hp')
        self.assertEqual(current_hp, 0)
        print(f"Stats Command: Player {p_w_dead['character_name']} HP is {current_hp}")

    def test_item_level_requirements(self):
        print("\n--- Testing Item Level Requirements ---")
        # Give warrior an SSR weapon: Dragonslayer Greatsword (w_ssr_1, atk=450)
        # 1. Insert item in db
        item_data = {
            "id": "w_ssr_1",
            "name": "Dragonslayer Greatsword",
            "tier": "SSR",
            "type": "weapon",
            "atk": 450,
            "drop_weight": 10
        }
        item_doc = db.add_item(self.warrior['id'], item_data, "TestBoss")
        
        # 2. Equip it for warrior (warrior is currently level 5)
        db.update_player(self.warrior['id'], {"equipped_weapon": item_doc['id']})
        
        # 3. Calculate player stats - level 5 warrior should IGNORE the weapon's ATK bonus (atk=450)
        p_lvl5 = db.get_player("test_user_warrior")
        stats_lvl5 = calculate_player_stats(p_lvl5)
        # Base warrior ATK at lvl 5 is: base_stats['atk'] (100) + (level - 1) * growth['atk'] (8) = 100 + 4 * 8 = 132.
        # If weapon was applied, ATK would be 132 + 450 = 582.
        self.assertEqual(stats_lvl5['atk'], 132)
        print(f"Level 5 Warrior (equipped w_ssr_1) ATK: {stats_lvl5['atk']} (Dragonslayer Greatsword stats IGNORED: Correct)")

        # 4. Now level up warrior to level 30 (requirement for SSR at +0 is 25)
        levels = {"warrior": {"level": 30, "exp": 0}}
        db.update_player(self.warrior['id'], {
            "class_levels": json.dumps(levels),
            "level": 30
        })
        
        # 5. Calculate player stats again - level 30 warrior should APPLY the weapon's ATK bonus!
        p_lvl30 = db.get_player("test_user_warrior")
        stats_lvl30 = calculate_player_stats(p_lvl30)
        # Base warrior ATK at lvl 30: 100 + 29 * 8 = 332.
        # With weapon applied: 332 + 450 = 782.
        self.assertEqual(stats_lvl30['atk'], 782)
        print(f"Level 30 Warrior (equipped w_ssr_1) ATK: {stats_lvl30['atk']} (Dragonslayer Greatsword stats APPLIED: Correct)")

    def test_streamerbot_webhook_compatibility(self):
        print("\n--- Testing Streamer.bot Webhook Compatibility ---")
        from api.server import app
        client = app.test_client()
        
        # 1. Test GET request
        resp_get = client.get('/api/streamerbot?action=channel_point&reward=Revive%20Party&user=test_user')
        self.assertEqual(resp_get.status_code, 200)
        data_get = json.loads(resp_get.data)
        self.assertIn('status', data_get)
        self.assertIn('message', data_get)
        print(f"GET Response: {repr(data_get).encode('ascii', 'backslashreplace').decode('ascii')}")
        
        # 2. Test POST form-urlencoded request (Form Data)
        resp_post_form = client.post('/api/streamerbot', data={
            'action': 'channel_point',
            'reward': 'ชุบชีวิตปาร์ตี้',
            'user': 'test_user'
        })
        self.assertEqual(resp_post_form.status_code, 200)
        data_post_form = json.loads(resp_post_form.data)
        self.assertIn('status', data_post_form)
        self.assertIn('message', data_post_form)
        print(f"POST Form Response: {repr(data_post_form).encode('ascii', 'backslashreplace').decode('ascii')}")
        
        # 3. Test POST JSON request
        resp_post_json = client.post('/api/streamerbot', json={
            'action': 'channel_point',
            'reward': 'Revive Player',
            'user': 'test_user',
            'target': 'test_user_warrior'
        })
        self.assertEqual(resp_post_json.status_code, 200)
        data_post_json = json.loads(resp_post_json.data)
        self.assertIn('status', data_post_json)
        self.assertIn('message', data_post_json)
        print(f"POST JSON Response: {repr(data_post_json).encode('ascii', 'backslashreplace').decode('ascii')}")
        
        # Test self-targeting keyword 'me'
        resp_post_me = client.post('/api/streamerbot', json={
            'reward': 'revive',
            'user': 'test_user_warrior',
            'target': 'me'
        })
        self.assertEqual(resp_post_me.status_code, 200)
        data_post_me = json.loads(resp_post_me.data)
        self.assertIn('ยังไม่ตาย!', data_post_me.get('message', ''))

        # 4. Test fallback response has message key
        resp_fallback = client.post('/api/streamerbot', data={
            'action': 'invalid_action',
            'reward': 'invalid_reward'
        })
        self.assertEqual(resp_fallback.status_code, 200)
        data_fallback = json.loads(resp_fallback.data)
        self.assertEqual(data_fallback['status'], 'ignored')
        self.assertIn('message', data_fallback)
        print(f"Fallback Response: {repr(data_fallback).encode('ascii', 'backslashreplace').decode('ascii')}")

        # 5. Test character name lookup compatibility (case-insensitive character name 'testwarrior')
        resp_post_charname = client.post('/api/streamerbot', json={
            'action': 'channel_point',
            'reward': 'Revive Player',
            'user': 'test_user',
            'target': 'testwarrior'
        })
        self.assertEqual(resp_post_charname.status_code, 200)
        data_post_charname = json.loads(resp_post_charname.data)
        self.assertIn('status', data_post_charname)
        # Should return that the player is not in the party (rather than 'ไม่พบผู้เล่นชื่อ testwarrior')
        self.assertNotIn('ไม่พบผู้เล่นชื่อ', data_post_charname.get('message', ''))
        print(f"POST JSON Character Name Response: {repr(data_post_charname).encode('ascii', 'backslashreplace').decode('ascii')}")

    def test_equipment_tier_and_boss_stars(self):
        print("\n--- Testing Equipment Tier and Boss Stars ---")
        # 1. Equip an SSR item on warrior
        item_data = {
            "id": "w_ssr_1",
            "name": "Dragonslayer Greatsword",
            "tier": "SSR",
            "type": "weapon",
            "atk": 450,
            "drop_weight": 10
        }
        item_doc = db.add_item(self.warrior['id'], item_data, "TestBoss")
        db.update_player(self.warrior['id'], {"equipped_weapon": item_doc['id']})
        
        # Verify get_player_equipment returns tier key
        eq = db.get_player_equipment(self.warrior['id'])
        self.assertIn('equipped_weapon', eq)
        self.assertIsNotNone(eq['equipped_weapon'])
        self.assertEqual(eq['equipped_weapon']['tier'], 'SSR')
        print(f"Equipped weapon tier correctly identified: {eq['equipped_weapon']['tier']}")
        
        # 2. Spawn a boss and check stars calculation based on player average levels
        boss = boss_manager.spawn_boss(2, boss_type='1')
        db.update_boss(boss['instance_id'], {
            'participants': [self.warrior['id'], self.priest['id']]
        })
        boss_with_p = db.get_active_boss()
        # Avg level is 5 -> stars should be 1
        self.assertEqual(boss_with_p['stars'], 1)
        print(f"Boss spawned with average participant level 5. Stars: {boss_with_p['stars']} (Expected: 1)")
        
        # Level up warrior to level 60, priest to level 60
        levels_w = {"warrior": {"level": 60, "exp": 0}}
        levels_p = {"priest": {"level": 60, "exp": 0}}
        db.update_player(self.warrior['id'], {"class_levels": json.dumps(levels_w), "level": 60})
        db.update_player(self.priest['id'], {"class_levels": json.dumps(levels_p), "level": 60})
        
        # Fetch active boss again (dynamic calculation)
        boss_high_lvl = db.get_active_boss()
        # Avg level is 60 -> stars should be 5
        self.assertEqual(boss_high_lvl['stars'], 5)
        print(f"Boss fetched with average participant level 60. Stars: {boss_high_lvl['stars']} (Expected: 5)")

    def test_weapon_element_combat_application(self):
        print("\n--- Testing Weapon Element Combat Application ---")
        # 1. Spawn Forest Guardian (weak to fire)
        boss = boss_manager.spawn_boss(1, boss_type='1')
        db.update_boss(boss['instance_id'], {'base_hp': 999999, 'max_hp': 999999, 'current_hp': 999999})
        boss = db.get_active_boss()
        
        # 2. Level up warrior to level 30 so SSR items are active
        levels_w = {"warrior": {"level": 30, "exp": 0}}
        db.update_player(self.warrior['id'], {"class_levels": json.dumps(levels_w), "level": 30})
        
        # Calculate stats without weapon
        db.update_player(self.warrior['id'], {"equipped_weapon": None})
        p_no_weap = db.get_player("test_user_warrior")
        
        db.update_boss(boss['instance_id'], {'base_def': 0, 'participants': [self.warrior['id']]})
        boss = db.get_active_boss()
        
        # Check calculation using calculate_damage
        from game.combat import calculate_damage
        basic_attack_skill = {
            "name": "Basic Attack",
            "damage_multiplier": 1.0,
            "cooldown": 3,
            "type": "physical",
            "mp_cost": 0
        }
        
        import unittest.mock as mock
        with mock.patch('random.random', return_value=1.0):
            dmg_no_weap, _ = calculate_damage(p_no_weap, boss, basic_attack_skill)
            self.assertEqual(dmg_no_weap, 32)
            print(f"Damage without element: {dmg_no_weap} (Correct)")
            
            # 3. Equip w_ssr_1 (element: fire, atk: 450)
            item_data = {
                "id": "w_ssr_1",
                "name": "Dragonslayer Greatsword",
                "tier": "SSR",
                "type": "weapon",
                "atk": 450,
                "element": "fire",
                "drop_weight": 10
            }
            item_doc = db.add_item(self.warrior['id'], item_data, "TestBoss")
            db.update_player(self.warrior['id'], {"equipped_weapon": item_doc['id']})
            
            p_weap = db.get_player("test_user_warrior")
            dmg_weap, _ = calculate_damage(p_weap, boss, basic_attack_skill)
            self.assertEqual(dmg_weap, 873)
            print(f"Damage with fire element (1.5x elemental multiplier applied): {dmg_weap} (Correct)")

    def test_custom_chuunibyou_chat_format(self):
        print("\n--- Testing Custom Chuunibyou Chat Format ---")
        # 1. Spawn a boss
        boss = boss_manager.spawn_boss(1, boss_type='1')
        db.update_boss(boss['instance_id'], {'base_def': 0, 'participants': [self.warrior['id']]})
        boss = db.get_active_boss()
        
        # 2. Level up warrior to level 55 so UR items (requirement 50) are active
        levels_w = {"warrior": {"level": 55, "exp": 0}}
        db.update_player(self.warrior['id'], {"class_levels": json.dumps(levels_w), "level": 55})
        
        # 3. Equip w_ur_1 (ดาบสลักวิญญาณทมิฬกลืนกินแสงดารา, atk: 850)
        item_data = {
            "id": "w_ur_1",
            "name": "ดาบสลักวิญญาณทมิฬกลืนกินแสงดารา",
            "tier": "UR",
            "type": "weapon",
            "atk": 850,
            "crit_rate": 20,
            "element": "dark",
            "custom_chat_format": "ปลดปล่อยจิตวิญญาณทมิฬกลืนกินดวงดารา! 「{player}」ฟาดฟันบอส {boss} ดาเมจทะลุขีดจำกัด {damage}!",
            "drop_weight": 5
        }
        item_doc = db.add_item(self.warrior['id'], item_data, "TestBoss")
        db.update_player(self.warrior['id'], {"equipped_weapon": item_doc['id']})
        
        p = db.get_player("test_user_warrior")
        res = process_action(p, 'attack')
        
        self.assertTrue(res['success'])
        self.assertIn("ปลดปล่อยจิตวิญญาณทมิฬกลืนกินดวงดารา!", res['message'])
        self.assertIn("TestWarrior", res['message'])
        self.assertIn("Forest Guardian", res['message'])
        print(f"Generated message: {res['message'].encode('ascii', 'backslashreplace').decode('ascii')}")

if __name__ == '__main__':
    unittest.main()
