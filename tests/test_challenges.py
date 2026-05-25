import sys
import os
import unittest
import json
import time
from datetime import datetime, timedelta

# Add root folder to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db
from game.challenge_manager import spawn_challenge, init_challenges, track_progress, CHALLENGE_TEMPLATES
from game.combat import process_action, log_combat
from game.boss_manager import boss_manager

class TestStreamChallenges(unittest.TestCase):
    def setUp(self):
        # Setup temporary players
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_challenger_%'")
            conn.execute("DELETE FROM stream_challenges")
            conn.execute("DELETE FROM combat_log")
            conn.commit()
        finally:
            conn.close()

        db.create_player("test_challenger_1", "99901", "ChallengerOne", "warrior")
        db.create_player("test_challenger_2", "99902", "ChallengerTwo", "mage")

        self.p1 = db.get_player("test_challenger_1")
        self.p2 = db.get_player("test_challenger_2")

    def tearDown(self):
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM players WHERE username LIKE 'test_challenger_%'")
            conn.execute("DELETE FROM stream_challenges")
            conn.execute("DELETE FROM combat_log")
            conn.commit()
        finally:
            conn.close()

    def test_spawn_challenge(self):
        print("\n--- Testing Challenge Spawning ---")
        active = spawn_challenge()
        self.assertIsNotNone(active)
        self.assertEqual(active['status'], 'active')
        self.assertEqual(active['current_value'], 0)
        self.assertIn(active['challenge_type'], ['damage', 'crits', 'boss_kills'])
        self.assertTrue(active['target_value'] > 0)
        self.assertTrue(active['reward_amount'] > 0)
        self.assertIsNotNone(active['created_at'])

    def test_init_challenges_exist(self):
        print("\n--- Testing init_challenges with Existing Challenge ---")
        # Spawn one first
        created_id = db.create_challenge("damage", "ทำดาเมจรวม", 1000, "gold", 200)
        
        # Run init
        init_challenges()
        
        active = db.get_active_challenge()
        self.assertIsNotNone(active)
        self.assertEqual(active['id'], created_id)
        self.assertEqual(active['status'], 'active')

    def test_init_challenges_expired(self):
        print("\n--- Testing Challenge Expiration (12+ hours) ---")
        # Spawn an old challenge (13 hours ago)
        old_time = (datetime.now() - timedelta(hours=13)).isoformat()
        
        conn = db.get_connection()
        try:
            conn.execute('''INSERT INTO stream_challenges (challenge_type, description, target_value, current_value, reward_type, reward_amount, status, created_at)
                             VALUES ('damage', 'Test Expired', 100, 10, 'gold', 100, 'active', ?)''', (old_time,))
            conn.commit()
        finally:
            conn.close()
            
        # Run init, which should detect the expired challenge and spawn a new one
        init_challenges()
        
        # Verify the old one is no longer active, and a new one exists
        conn = db.get_connection()
        try:
            old = conn.execute("SELECT * FROM stream_challenges WHERE description = 'Test Expired'").fetchone()
            self.assertEqual(old['status'], 'expired')
        finally:
            conn.close()
            
        active = db.get_active_challenge()
        self.assertIsNotNone(active)
        self.assertNotEqual(active['description'], 'Test Expired')

    def test_track_progress_damage(self):
        print("\n--- Testing Progress Tracking: Damage ---")
        # Force a damage challenge
        db.create_challenge("damage", "ทำดาเมจรวม", 10000, "gold", 200)
        
        # Track some progress
        track_progress("damage", 2500)
        active = db.get_active_challenge()
        self.assertEqual(active['current_value'], 2500)
        
        # Tracking other type shouldn't change it
        track_progress("crits", 5)
        active = db.get_active_challenge()
        self.assertEqual(active['current_value'], 2500)

    def test_challenge_completion_rewards(self):
        print("\n--- Testing Challenge Completion & Rewards Distribution ---")
        # Force a crit challenge
        db.create_challenge("crits", "โจมตีคริติคอล", 2, "both", 500)
        
        # Mock players doing combat to log them as participants
        # We need their ID in combat_log
        boss = boss_manager.spawn_boss(1)
        self.assertIsNotNone(boss)
        
        # P1 registers a hit (adds to combat_log)
        log_combat(boss['instance_id'], self.p1['id'], "Slash", 100, False)
        # P2 registers a hit
        log_combat(boss['instance_id'], self.p2['id'], "Fireball", 150, True)
        
        # Give combat log worker a moment to process the batch queue if running asynchronously
        # But in test environment we might want to manually flush, or we can just write directly since combat_log uses batching worker thread.
        # Wait, since combat log worker runs in a separate thread every 1s, let's wait 1.2s to ensure the log is committed.
        time.sleep(1.2)
        
        # Now track crits to trigger completion (Target is 2, let's add 2)
        track_progress("crits", 2)
        
        conn = db.get_connection()
        try:
            active = conn.execute("SELECT * FROM stream_challenges ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        self.assertEqual(active['status'], 'completed')
        self.assertEqual(active['current_value'], 2)
        
        # Check that participants received 500 Gold and 500 EXP
        p1_updated = db.get_player("test_challenger_1")
        p2_updated = db.get_player("test_challenger_2")
        
        self.assertTrue(p1_updated['gold'] >= 500)
        self.assertTrue(p2_updated['gold'] >= 500)
        
        # Exp verification
        # Since level 1 max exp requires 250, 500 exp will trigger a level up to level 2!
        self.assertEqual(p1_updated['level'], 2)
        self.assertEqual(p2_updated['level'], 2)

if __name__ == '__main__':
    unittest.main()
