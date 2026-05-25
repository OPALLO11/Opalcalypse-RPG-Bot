import sys
import os
import unittest
import json
import datetime
import asyncio

# Add root folder to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from game.boss_manager import boss_manager
from game.combat import process_action, trigger_boss_aoe_attack
from game.logic import calculate_player_stats, CLASSES

class TestRPGChanges(unittest.TestCase):
    def setUp(self):
        # Clean up database test players
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_user_%' OR twitch_id = '9999' OR username = 'test_new_user'")
            conn.commit()
        finally:
            conn.close()

        # Create test players
        db.create_player("test_user_warrior", "123451", "TestWarrior", "warrior")
        db.create_player("test_user_priest", "123452", "TestPriest", "priest")

        self.warrior = db.get_player("test_user_warrior")
        self.priest = db.get_player("test_user_priest")

    def tearDown(self):
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_user_%' OR twitch_id = '9999' OR username = 'test_new_user'")
            conn.commit()
        finally:
            conn.close()

    def test_registration_validation(self):
        print("\n--- Testing Registration Validation ---")
        from cogs.info import InfoCog
        class MockAuthor:
            def __init__(self, name):
                self.name = name
                self.id = "9999"
        class MockContext:
            def __init__(self):
                self.author = MockAuthor("test_user_new")
                self.sent_messages = []
            async def send(self, msg):
                self.sent_messages.append(msg)
                
        info_cog = InfoCog(None)
        
        # Scenario 1: missing class (only name)
        ctx = MockContext()
        asyncio.run(info_cog.cmd_register._callback(info_cog, ctx, "John"))
        self.assertTrue(any("ลงทะเบียนไม่สำเร็จ" in m for m in ctx.sent_messages))
        print("Register with missing class failed: Correct")

        # Scenario 2: invalid class
        ctx = MockContext()
        asyncio.run(info_cog.cmd_register._callback(info_cog, ctx, "John", "ninja"))
        self.assertTrue(any("ลงทะเบียนไม่สำเร็จ" in m for m in ctx.sent_messages))
        print("Register with invalid class failed: Correct")

        # Scenario 3: valid register
        ctx = MockContext()
        asyncio.run(info_cog.cmd_register._callback(info_cog, ctx, "John", "priest"))
        self.assertTrue(any("Successfully registered" in m for m in ctx.sent_messages))
        print("Register with valid class succeeded: Correct")

    def test_priest_skills_and_gold(self):
        print("\n--- Testing Priest Skills and Gold ---")
        # 1. Verify revive is not in classes.json Priest skills, but holysmite is
        priest_skills = CLASSES['priest']['skills']
        self.assertNotIn('revive', priest_skills)
        self.assertIn('holysmite', priest_skills)
        print("CLASSES config verified: Revive replaced with Holy Smite.")

        # 2. Spawn a boss
        boss = boss_manager.spawn_boss(1, boss_type='1')
        db.update_boss(boss['instance_id'], {'base_hp': 10000, 'max_hp': 10000, 'current_hp': 10000, 'participants': [self.priest['id'], self.warrior['id']]})
        boss = db.get_active_boss()
        
        # 3. Test Holy Smite damage dealing
        # Restore priest MP
        db.update_player(self.priest['id'], {'mp': 100, 'hp': 1000})
        p = db.get_player("test_user_priest")
        
        res = process_action(p, 'skill', 'holysmite')
        self.assertTrue(res['success'])
        self.assertTrue(res['damage'] > 0)
        # Check MP reduced by 15
        p_after = db.get_player("test_user_priest")
        self.assertEqual(p_after['mp'], 85)
        print(f"Holy Smite damage dealt: {res['damage']}, MP reduced to {p_after['mp']}")

        # 4. Test Heal skill: doesn't damage boss, logs heal amount, but NO real-time gold
        db.update_player(self.priest['id'], {'mp': 100, 'hp': 50}) # low HP
        p = db.get_player("test_user_priest")
        boss_before = db.get_active_boss()
        
        # Clear combat logs and set initial gold to 0
        conn = db.get_connection()
        conn.execute("DELETE FROM combat_log")
        conn.execute("UPDATE players SET gold = 0 WHERE id IN (?, ?)", (self.priest['id'], self.warrior['id']))
        conn.commit()
        conn.close()

        res_heal = process_action(p, 'skill', 'heal')
        self.assertTrue(res_heal['success'])
        # Check boss took NO damage
        boss_after = db.get_active_boss()
        self.assertEqual(boss_after['current_hp'], boss_before['current_hp'])
        self.assertEqual(res_heal['damage'], 0)
        
        # Flush combat log batch queue directly
        db.combat_logs.flush()
        
        p_healed = db.get_player("test_user_priest")
        self.assertTrue(p_healed['hp'] > 50)
        # Gold must still be 0 (no real-time gold reward!)
        self.assertEqual(p_healed['gold'], 0)
        print(f"Heal skill casted: HP restored to {p_healed['hp']}, Gold remained {p_healed['gold']} (No real-time Gold)")

        # 5. Simulate boss death and check proportional Gold distribution
        # Set boss HP to 1 and active participants, and base_hp/max_hp to 1 to avoid scaling up current_hp
        db.update_boss(boss['instance_id'], {
            'base_hp': 1,
            'max_hp': 1,
            'current_hp': 1,
            'participants': [self.priest['id'], self.warrior['id']]
        })
        boss = db.get_active_boss()

        # Let's check combat logs first to make sure there's healing logged
        # We need to add some damage for the warrior as well
        p_warrior = db.get_player("test_user_warrior")
        
        # Warrior basic attacks the boss, dealing enough damage to defeat it
        res_kill = process_action(p_warrior, 'attack')
        self.assertTrue(res_kill['success'])
        self.assertTrue(res_kill['is_dead'])

        # Flush combat log batch queue directly
        db.combat_logs.flush()

        # Confirm rankings are retrieved
        rankings = db.get_boss_rankings(boss['instance_id'])
        print(f"Defeat rankings: {rankings}")
        
        # Check gold rewards in results
        gold_rewards = res_kill.get('gold_rewards', {})
        print(f"Distributed gold rewards: {gold_rewards}")

        p_priest_after = db.get_player("test_user_priest")
        p_warrior_after = db.get_player("test_user_warrior")

        # Gold should be distributed proportionally based on contribution
        # Total boss gold for Star 1 Normal = 1,000 Gold
        total_boss_gold = 1000
        total_contrib = sum(r['damage'] for r in rankings)
        self.assertTrue(total_contrib > 0)

        expected_priest_gold = 0
        expected_warrior_gold = 0
        for r in rankings:
            pct = r['damage'] / total_contrib
            expected = int(total_boss_gold * pct)
            if r['id'] == self.priest['id']:
                expected_priest_gold = expected
            elif r['id'] == self.warrior['id']:
                expected_warrior_gold = expected

        self.assertEqual(p_priest_after['gold'], expected_priest_gold)
        self.assertEqual(p_warrior_after['gold'], expected_warrior_gold)
        print(f"Gold successfully distributed! Priest: {p_priest_after['gold']}G, Warrior: {p_warrior_after['gold']}G")

    def test_ultimates_mp_consumption(self):
        print("\n--- Testing Ultimates MP Consumption ---")
        # Check MP cost in classes.json
        self.assertEqual(CLASSES['warrior']['skills']['ultimate']['mp_cost'], 30)
        self.assertEqual(CLASSES['mage']['skills']['ultimate']['mp_cost'], 50)
        self.assertEqual(CLASSES['rogue']['skills']['ultimate']['mp_cost'], 40)
        self.assertEqual(CLASSES['priest']['skills']['ultimate']['mp_cost'], 40)
        print("Ultimates MP costs are correctly set in CLASSES config.")

    def test_boss_charging_time_attack(self):
        print("\n--- Testing Boss Charging Time-Based AOE ---")
        boss = boss_manager.spawn_boss(1, boss_type='1')
        db.update_boss(boss['instance_id'], {'participants': [self.warrior['id']]})
        boss = db.get_active_boss()
        
        # Trigger charging
        state = boss_manager.boss_state[boss['instance_id']]
        state['charge'] = 0
        state['is_charging'] = False
        
        # Warrior ultimate should charge 100%
        p = db.get_player("test_user_warrior")
        db.update_player(p['id'], {'mp': 100})
        p = db.get_player("test_user_warrior")
        res = process_action(p, 'ultimate')
        self.assertTrue(res['success'])
        
        # Check if boss is charging and charge_start_time is set
        self.assertTrue(state['is_charging'])
        self.assertIsNotNone(state['charge_start_time'])
        print(f"Boss starts charging. is_charging: {state['is_charging']}, charge_start_time: {state['charge_start_time']}")

        # Simulate 20 seconds elapse
        state['charge_start_time'] = datetime.datetime.now() - datetime.timedelta(seconds=21)
        
        # Run trigger_boss_aoe_attack manually
        asyncio.run(trigger_boss_aoe_attack(boss))
        
        # Verify boss state reset
        self.assertFalse(state['is_charging'])
        self.assertEqual(state['charge'], 0)
        print("Boss AOE attack triggered successfully after 20s and state reset.")

if __name__ == '__main__':
    unittest.main()
