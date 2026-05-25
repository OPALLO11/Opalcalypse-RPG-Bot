import asyncio
import os
import sys
import unittest

# Add root folder to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.info import InfoCog


class TestReload(unittest.TestCase):
    def test_reload_unauthorized(self):
        print("\n--- Testing Reload Command (Unauthorized) ---")

        class MockAuthor:
            def __init__(self, name, is_mod=False):
                self.name = name
                self.is_mod = is_mod

        class MockContext:
            def __init__(self):
                self.author = MockAuthor("regular_user", is_mod=False)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        info_cog = InfoCog(None)

        ctx = MockContext()
        # Execute cmd_reload callback
        asyncio.run(info_cog.cmd_reload._callback(info_cog, ctx))

        self.assertTrue(any("❌ You are not allowed to use this command!" in m for m in ctx.sent_messages))
        print("Unauthorized reload blocked: Correct")

    def test_reload_authorized_native_mode(self):
        print("\n--- Testing Reload Command (Authorized Native Mode) ---")

        class MockBot:
            def __init__(self):
                self.removed_cogs = []
                self.added_cogs = []
                self.cogs = {}

            def remove_cog(self, name):
                self.removed_cogs.append(name)
                if name in self.cogs:
                    del self.cogs[name]

            def add_cog(self, cog):
                self.added_cogs.append(cog.__class__.__name__)
                self.cogs[cog.__class__.__name__] = cog

            def get_cog(self, name):
                return self.cogs.get(name)

        class MockAuthor:
            def __init__(self, name, is_mod=True):
                self.name = name
                self.is_mod = is_mod

        class MockContext:
            def __init__(self, bot):
                self.author = MockAuthor("broadcaster_user", is_mod=True)
                self.sent_messages = []
                self.bot = bot

            async def send(self, msg):
                self.sent_messages.append(msg)

        # Mock the sys.modules['bot'] if not present
        import types
        bot_mock_mod = types.ModuleType('bot')
        bot_mock_mod.combat_cog = None
        bot_mock_mod.info_cog = None
        sys.modules['bot'] = bot_mock_mod

        mock_bot = MockBot()
        info_cog = InfoCog(mock_bot)

        ctx = MockContext(mock_bot)

        # Execute cmd_reload callback
        asyncio.run(info_cog.cmd_reload._callback(info_cog, ctx))

        # Verify removal and additions happened
        self.assertIn("CombatCog", mock_bot.removed_cogs)
        self.assertIn("InfoCog", mock_bot.removed_cogs)
        self.assertIn("CombatCog", mock_bot.added_cogs)
        self.assertIn("InfoCog", mock_bot.added_cogs)

        # Verify global refs in bot module were updated
        self.assertIsNotNone(bot_mock_mod.combat_cog)
        self.assertIsNotNone(bot_mock_mod.info_cog)

        self.assertTrue(any("🔄 Cogs and game rules successfully reloaded!" in m for m in ctx.sent_messages))
        print("Authorized reload in Native Bot Mode succeeded: Correct")

    def test_reload_authorized_ws_mode(self):
        print("\n--- Testing Reload Command (Authorized WS Mode) ---")

        class MockAuthor:
            def __init__(self, name, is_mod=True):
                self.name = name
                self.is_mod = is_mod

        class MockContext:
            def __init__(self):
                self.author = MockAuthor("moderator_user", is_mod=True)
                self.sent_messages = []
                self.bot = None  # WS mode has no bot reference on the cog

            async def send(self, msg):
                self.sent_messages.append(msg)

        # Mock sys.modules['bot']
        import types
        bot_mock_mod = types.ModuleType('bot')
        bot_mock_mod.combat_cog = None
        bot_mock_mod.info_cog = None
        sys.modules['bot'] = bot_mock_mod

        info_cog = InfoCog(None)
        ctx = MockContext()

        # Execute cmd_reload callback
        asyncio.run(info_cog.cmd_reload._callback(info_cog, ctx))

        # Verify global refs in bot module were updated
        self.assertIsNotNone(bot_mock_mod.combat_cog)
        self.assertIsNotNone(bot_mock_mod.info_cog)

        self.assertTrue(any("🔄 Cogs and game rules successfully reloaded!" in m for m in ctx.sent_messages))
        print("Authorized reload in WS Mode succeeded: Correct")


if __name__ == "__main__":
    unittest.main()
