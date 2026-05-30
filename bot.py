import asyncio
import datetime
import json
import os
import traceback

import websockets
from dotenv import load_dotenv
from twitchio.ext import commands as tio_commands

from cogs.combat import CombatCog
from cogs.info import InfoCog
from database import db
from game.boss_manager import boss_manager
from game.challenge_manager import init_challenges
from game.combat import LAST_ACTIVE
from game.helpers import split_message
from utils import load_config, emit_to_overlay, send_streamerbot_message, format_twitch_chat_message

load_dotenv()

# Instantiate the cogs with a dummy bot reference for local WS server mode
combat_cog = CombatCog(None)
info_cog = InfoCog(None)


class RPGBot(tio_commands.Bot):
    def __init__(self, client_id, client_secret, bot_id, prefix, initial_channels):
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id,
            prefix=prefix,
            initial_channels=initial_channels
        )
    async def setup_hook(self):
        await self.add_component(CombatCog(self))
        await self.add_component(InfoCog(self))

        # Start background game loops within the bot's event loop
        import asyncio
        asyncio.create_task(regen_loop())
        asyncio.create_task(boss_attack_loop())

    async def event_oauth_authorized(self, payload):
        """Override to save tokens immediately after OAuth, not just on shutdown."""
        await super().event_oauth_authorized(payload)
        # Force-save token file right away so it persists even if the bot crashes
        try:
            await self.save_tokens()
            print(f"[AUTH] ✓ OAuth token saved to .tio.tokens.json successfully!")
        except Exception as e:
            print(f"[AUTH] ✗ Failed to save token file: {e}")

    async def event_ready(self):
        print(f"Logged in | Bot ID: {self.bot_id}")
        if hasattr(self, 'user'):
            print(f"User: {self.user}")

        # Register bot instance for send_streamerbot_message fallback
        from utils import set_bot
        import asyncio
        set_bot(self, asyncio.get_running_loop())

        # TwitchIO 3.x requires explicitly subscribing to chat messages via EventSub
        try:
            import twitchio.eventsub as es
            channel_name = os.environ.get('TWITCH_CHANNEL')
            users = await self.fetch_users(logins=[channel_name])
            if users:
                broadcaster_id = users[0].id
                sub = es.ChatMessageSubscription(broadcaster_user_id=broadcaster_id, user_id=self.bot_id)
                await self.subscribe_websocket(payload=sub)
                print(f"Subscribed to chat messages for channel: {channel_name}")
        except Exception as e:
            print(f"Failed to subscribe to chat messages: {e}")

    async def event_message(self, message):
        if message.chatter and hasattr(self, 'bot_id') and message.chatter.id == self.bot_id:
            return

        author_name = message.chatter.name if message.chatter else "System"
        print(f"[Twitch Chat] {author_name}: {message.text}")

        # Bits detection
        bits = 0
        tags = getattr(message, 'tags', None)
        if tags and 'bits' in tags:
            try:
                bits = int(tags['bits'])
            except:
                pass
        if hasattr(message, 'cheer') and message.cheer:
            try:
                bits = getattr(message.cheer, 'bits', 0)
            except:
                pass
        if bits >= 100 and message.chatter:
            print(f"[Bits Art] {author_name} cheered {bits} bits with message: {message.text}")
            asyncio.create_task(process_art_bits(author_name, bits, message.text))

        await self.process_commands(message)


class WSContext:
    def __init__(self, websocket, data, config):
        self.websocket = websocket
        self.config = config
        self.data = data

        # Parse user details from Streamer.bot event payload
        user_info = data.get('user', {}) if isinstance(data.get('user'), dict) else {}
        self.author_name = (
                data.get('userName') or
                data.get('userLogin') or
                user_info.get('name') or
                user_info.get('login') or
                (data.get('user') if isinstance(data.get('user'), str) else "") or
                ""
        )
        self.author_id = data.get('userId') or user_info.get('id') or ""

        is_mod = data.get('isModerator') or data.get('moderator', False)
        is_broadcaster = data.get('isBroadcaster') or data.get('broadcaster', False)

        # Convert string representations of boolean if necessary (from Streamer.bot client variables)
        if isinstance(is_mod, str):
            is_mod = is_mod.lower() in ('true', '1', 'yes')
        if isinstance(is_broadcaster, str):
            is_broadcaster = is_broadcaster.lower() in ('true', '1', 'yes')

        self.is_mod = is_mod or is_broadcaster

    @property
    def chatter(self):
        class Chatter:
            def __init__(self, name, uid, is_mod):
                self.name = name
                self.id = uid
                self.is_mod = is_mod
                self.moderator = is_mod

        return Chatter(self.author_name, self.author_id, self.is_mod)

    async def send(self, message):
        message = format_twitch_chat_message(message)
        messages = split_message(message, max_len=400)

        import websockets
        for msg in messages:
            # 1. Send via WebSocket if connection is open (for client logging / Custom WS action)
            is_open = False
            if self.websocket:
                if hasattr(self.websocket, 'open'):
                    is_open = self.websocket.open
                elif hasattr(self.websocket, 'state'):
                    is_open = self.websocket.state == websockets.State.OPEN

            if is_open:
                try:
                    response_payload = {
                        "message": msg,
                        "text": msg
                    }
                    await self.websocket.send(json.dumps(response_payload))
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"Error sending message over WebSocket: {e}")

            # 2. Send via HTTP POST (this is the most reliable way to broadcast to Twitch)
            send_streamerbot_message(msg)


# ---------------------------------------------------------------------------
# Command registry: maps command names (incl. aliases) to cog + method + args.
# 'args' defines how to parse the raw args_str into keyword arguments.
#   - 'all'          -> passes the full args_str as the first kwarg
#   - 'parts'        -> passes the full parts list as *args
#   - 'first'        -> passes only parts[0] (or "") as the first kwarg
#   - 'skill_target' -> passes parts[0] as skill_name, rest as target
#   - None / []      -> no arguments
# ---------------------------------------------------------------------------
COMMAND_REGISTRY = {
    # CombatCog commands
    'attack': {'cog': 'combat', 'method': 'cmd_attack'},
    'atk': {'cog': 'combat', 'method': 'cmd_attack'},
    'skill': {'cog': 'combat', 'method': 'cmd_skill', 'args': 'skill_target'},
    'sk': {'cog': 'combat', 'method': 'cmd_skill', 'args': 'skill_target'},
    'ultimate': {'cog': 'combat', 'method': 'cmd_ultimate'},
    'ult': {'cog': 'combat', 'method': 'cmd_ultimate'},
    'def': {'cog': 'combat', 'method': 'cmd_def', 'args': ('all', 'skill_name')},
    'spawn': {'cog': 'combat', 'method': 'cmd_spawn', 'args': ('first', 'type_arg')},
    'sp': {'cog': 'combat', 'method': 'cmd_spawn', 'args': ('first', 'type_arg')},
    'spwn': {'cog': 'combat', 'method': 'cmd_spawn', 'args': ('first', 'type_arg')},
    # InfoCog commands
    'test': {'cog': 'info', 'method': 'cmd_test'},
    'boss': {'cog': 'info', 'method': 'cmd_boss'},
    'bs': {'cog': 'info', 'method': 'cmd_boss'},
    'register': {'cog': 'info', 'method': 'cmd_register', 'args': 'parts'},
    'reg': {'cog': 'info', 'method': 'cmd_register', 'args': 'parts'},
    'regis': {'cog': 'info', 'method': 'cmd_register', 'args': 'parts'},
    'changeclass': {'cog': 'info', 'method': 'cmd_changeclass', 'args': ('first', 'new_class')},
    'cc': {'cog': 'info', 'method': 'cmd_changeclass', 'args': ('first', 'new_class')},
    'ccl': {'cog': 'info', 'method': 'cmd_changeclass', 'args': ('first', 'new_class')},
    'rename': {'cog': 'info', 'method': 'cmd_rename', 'args': ('all', 'new_name')},
    'rn': {'cog': 'info', 'method': 'cmd_rename', 'args': ('all', 'new_name')},
    'inventory': {'cog': 'info', 'method': 'cmd_inventory'},
    'inv': {'cog': 'info', 'method': 'cmd_inventory'},
    'equip': {'cog': 'info', 'method': 'cmd_equip', 'args': ('all', 'item_name')},
    'eq': {'cog': 'info', 'method': 'cmd_equip', 'args': ('all', 'item_name')},
    'unequip': {'cog': 'info', 'method': 'cmd_unequip', 'args': ('first', 'slot_name')},
    'uneq': {'cog': 'info', 'method': 'cmd_unequip', 'args': ('first', 'slot_name')},
    'uq': {'cog': 'info', 'method': 'cmd_unequip', 'args': ('first', 'slot_name')},
    'sell': {'cog': 'info', 'method': 'cmd_sell', 'args': ('all', 'target')},
    'sel': {'cog': 'info', 'method': 'cmd_sell', 'args': ('all', 'target')},
    'stats': {'cog': 'info', 'method': 'cmd_stats'},
    'stat': {'cog': 'info', 'method': 'cmd_stats'},
    'st': {'cog': 'info', 'method': 'cmd_stats'},
    'info': {'cog': 'info', 'method': 'cmd_info'},
    'classes': {'cog': 'info', 'method': 'cmd_classes'},
    'class': {'cog': 'info', 'method': 'cmd_classes'},
    'cls': {'cog': 'info', 'method': 'cmd_classes'},
    'gold': {'cog': 'info', 'method': 'cmd_gold'},
    'money': {'cog': 'info', 'method': 'cmd_gold'},
    'gld': {'cog': 'info', 'method': 'cmd_gold'},
    'shop': {'cog': 'info', 'method': 'cmd_shop'},
    'shp': {'cog': 'info', 'method': 'cmd_shop'},
    'buy': {'cog': 'info', 'method': 'cmd_buy', 'args': ('first', 'item_name')},
    'b': {'cog': 'info', 'method': 'cmd_buy', 'args': ('first', 'item_name')},
    'inspect': {'cog': 'info', 'method': 'cmd_inspect', 'args': ('first', 'target_name')},
    'equipment': {'cog': 'info', 'method': 'cmd_inspect', 'args': ('first', 'target_name')},
    'equipments': {'cog': 'info', 'method': 'cmd_inspect', 'args': ('first', 'target_name')},
    'ins': {'cog': 'info', 'method': 'cmd_inspect', 'args': ('first', 'target_name')},
    'reload': {'cog': 'info', 'method': 'cmd_reload'},
}


async def dispatch_command(command_name, args_str, ctx):
    command_name = command_name.lower()
    entry = COMMAND_REGISTRY.get(command_name)
    if not entry:
        return  # Unknown command, silently ignore

    cog = combat_cog if entry['cog'] == 'combat' else info_cog
    method = getattr(cog, entry['method'])
    args_spec = entry.get('args')
    parts = args_str.strip().split() if args_str else []

    try:
        if args_spec is None:
            await method._callback(cog, ctx)
        elif args_spec == 'parts':
            await method._callback(cog, ctx, *parts)
        elif args_spec == 'skill_target':
            skill_name = parts[0] if parts else ""
            target = " ".join(parts[1:]) if len(parts) > 1 else ""
            await method._callback(cog, ctx, skill_name=skill_name, target=target)
        elif isinstance(args_spec, tuple):
            mode, kwarg_name = args_spec
            if mode == 'all':
                await method._callback(cog, ctx, **{kwarg_name: args_str or ""})
            elif mode == 'first':
                await method._callback(cog, ctx, **{kwarg_name: parts[0] if parts else ""})
    except Exception as e:
        print(f"Error executing command !{command_name}: {e}")
        traceback.print_exc()


async def process_art_bits(username, bits, content):
    from services.ai_art import handle_bits
    success, result = await asyncio.to_thread(handle_bits, username, bits, content)
    if success:
        emit_to_overlay('show_art', result)


async def boss_attack_loop():
    from game.combat import trigger_boss_aoe_attack
    print("Background Boss Attack Loop Started.")
    while True:
        try:
            await asyncio.sleep(1)
            boss = boss_manager.get_current_boss()
            if boss:
                state = boss_manager.boss_state.get(boss['instance_id'])
                if state and state.get('is_charging'):
                    start_time = state.get('charge_start_time')
                    if start_time:
                        elapsed = (datetime.datetime.now() - start_time).total_seconds()
                        if elapsed >= 20:
                            await trigger_boss_aoe_attack(boss)
        except Exception as e:
            print(f"Error in boss_attack_loop: {e}")
            traceback.print_exc()


async def regen_loop():
    from game.logic import calculate_player_stats
    from game.combat import check_cooldown, get_party_data

    timeout_limit = datetime.timedelta(minutes=15)
    print("Background Regen Loop Started.")

    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.datetime.now()

            # Use repository to get all players (hydrated)
            players = db.players.get_all_players()

            updates_to_apply = []
            for player in players:
                if not player:
                    continue
                pid = player['id']
                stats = calculate_player_stats(player)

                max_hp = stats['max_hp']
                max_mp = stats['max_mp']
                current_hp = player.get('hp', 0)
                current_mp = player.get('mp', 0)

                player_updates = {}

                # Cap HP and MP if they exceed max
                if current_hp > max_hp:
                    current_hp = max_hp
                    player_updates['hp'] = current_hp
                if current_mp > max_mp:
                    current_mp = max_mp
                    player_updates['mp'] = current_mp

                # MP Regen (all players)
                if current_mp < max_mp:
                    new_mp = min(current_mp + 10, max_mp)
                    player_updates['mp'] = new_mp

                # HP Regen (active, alive players)
                alive, _ = check_cooldown(pid, 'respawn')
                last_active_time = LAST_ACTIVE.get(pid)
                active = last_active_time and (now - last_active_time) <= timeout_limit

                if alive and active:
                    if current_hp < max_hp:
                        regen_amount = max(5, int(max_hp * 0.02))
                        new_hp = min(current_hp + regen_amount, max_hp)
                        player_updates['hp'] = new_hp

                if player_updates:
                    updates_to_apply.append((pid, player_updates))

            # Batch-write all player updates in a single transaction
            if updates_to_apply:
                db.players.batch_regen_update(updates_to_apply)

            boss = boss_manager.get_current_boss()
            if boss:
                # Boss wipe timeout check
                state = boss_manager.boss_state.get(boss['instance_id'])
                if state and 'wipe_time' in state:
                    if now - state['wipe_time'] > datetime.timedelta(minutes=3):
                        db.update_boss(boss['instance_id'], {'current_hp': boss['max_hp']})
                        del state['wipe_time']
                        boss['current_hp'] = boss['max_hp']
                        emit_to_overlay('combat_event', {
                            'username': '💀 System',
                            'action': f'The party was wiped for 3 minutes. {boss["name"]} has fully recovered!',
                            'damage': 0, 'is_crit': False,
                            'boss_hp': boss['max_hp']
                        })

            if updates_to_apply and boss:
                emit_to_overlay('party_update', get_party_data(boss))
        except Exception as e:
            print(f"Error in regen_loop: {e}")


def handle_websocket_revive(user):
    from game.combat import revive_party_members
    success, msg = revive_party_members(user)
    print(f"WebSocket Revive Party request by {user}: {msg}")


async def websocket_server_handler(websocket, path=None):
    config = load_config()
    print(f"[WebSocket Server] Client connected from {websocket.remote_address}")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)

                # Check for test message or heartbeat
                if data.get('request') == 'Ping' or data.get('type') == 'ping':
                    await websocket.send(json.dumps({"type": "pong"}))
                    continue

                msg_text = data.get('message') or data.get('text') or ""
                username = data.get('userName') or data.get('user') or data.get('userLogin') or ""
                user_id = data.get('userId') or ""

                # Bits detection (can be passed from Streamer.bot custom payload)
                bits = 0
                try:
                    bits = int(data.get('bits') or 0)
                except:
                    pass

                if bits >= 100:
                    print(f"[Bits Art] {username} cheered {bits} bits with message: {msg_text}")
                    asyncio.create_task(process_art_bits(username, bits, msg_text))

                if msg_text.startswith('!'):
                    parts = msg_text.split(' ', 1)
                    command_name = parts[0][1:].lower()
                    args_str = parts[1] if len(parts) > 1 else ""
                    print(f"[WebSocket Server Command] {username}: !{command_name} '{args_str}'")

                    ctx = WSContext(websocket, data, config)
                    asyncio.create_task(dispatch_command(command_name, args_str, ctx))
                else:
                    # Log non-command chat messages
                    if username:
                        print(f"[WebSocket Server Chat] {username}: {msg_text}")

                # Handle RewardRedemption event
                if data.get('type') == 'RewardRedemption' or 'rewardName' in data:
                    reward_name = data.get('rewardName')
                    user = data.get('user') or data.get('userName') or ""
                    if reward_name == 'Revive Party':
                        handle_websocket_revive(user)

            except json.JSONDecodeError:
                # Support plain text command input for simple manual testing
                msg_text = message.strip()
                if msg_text.startswith('!'):
                    parts = msg_text.split(' ', 1)
                    command_name = parts[0][1:].lower()
                    args_str = parts[1] if len(parts) > 1 else ""
                    print(f"[WebSocket Server Raw Text Command] !{command_name} '{args_str}'")

                    ctx = WSContext(websocket, {}, config)
                    asyncio.create_task(dispatch_command(command_name, args_str, ctx))
            except Exception as e:
                print(f"Error in WebSocket Server message handler: {e}")
                traceback.print_exc()
    except websockets.exceptions.ConnectionClosed:
        print("[WebSocket Server] Client disconnected")
    except Exception as e:
        print(f"[WebSocket Server] Unexpected error: {e}")


async def websocket_server_listener():
    config = load_config()
    sb_config = config.get('streamerbot', {})
    port = int(sb_config.get('python_ws_port', 6789))
    host = '127.0.0.1'

    print(f"Starting Python WebSocket Server at ws://{host}:{port}/...")
    try:
        async with websockets.serve(websocket_server_handler, host, port):
            print(f"WebSocket Server is successfully running and listening on port {port}!")
            await asyncio.Future()  # Keep server running forever
    except Exception as e:
        print(f"Failed to start WebSocket Server on port {port}: {e}")
        traceback.print_exc()


def run_bot():
    db.reset_rename_limits()

    # Initialize stream challenges on startup
    init_challenges()

    # Make sure we have a boss active on startup
    boss = boss_manager.get_current_boss()
    if not boss:
        boss = boss_manager.spawn_boss(1)
    if boss:
        emit_to_overlay('boss_update', boss)

    # Check mode from config
    config = load_config()
    sb_config = config.get('streamerbot', {})
    use_server = sb_config.get('use_python_ws_server', False)

    if use_server:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.create_task(regen_loop())
        loop.create_task(boss_attack_loop())
        loop.run_until_complete(websocket_server_listener())
    else:
        client_id = os.environ.get('TWITCH_CLIENT_ID') or config.get('twitch', {}).get('client_id')
        client_secret = os.environ.get('TWITCH_CLIENT_SECRET') or config.get('twitch', {}).get('client_secret')
        bot_id = os.environ.get('TWITCH_BOT_ID') or config.get('twitch', {}).get('bot_id')
        channel = os.environ.get('TWITCH_CHANNEL') or config.get('twitch', {}).get('channel') or 'opallo11'
        prefix = '!'

        print("Initializing native TwitchIO RPGBot...")
        bot = RPGBot(client_id=client_id, client_secret=client_secret, bot_id=bot_id, prefix=prefix, initial_channels=[channel])
        
        bot.run()
