import os
import asyncio
import json
import uuid
import datetime
import traceback
import websockets
from dotenv import load_dotenv

from database import db
from game.boss_manager import boss_manager
from utils import load_config, emit_to_overlay, send_streamerbot_message
from cogs.combat import CombatCog
from cogs.info import InfoCog
from game.combat import LAST_ACTIVE
from game.challenge_manager import init_challenges

load_dotenv()

# Instantiate the cogs with a dummy bot reference
combat_cog = CombatCog(None)
info_cog = InfoCog(None)

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
    def author(self):
        class Author:
            def __init__(self, name, uid, is_mod):
                self.name = name
                self.id = uid
                self.is_mod = is_mod
        return Author(self.author_name, self.author_id, self.is_mod)

    async def send(self, message):
        # Split message if it's very long or contains newlines (Twitch has 500 char limit)
        messages = [message]
        if len(message) > 450:
            messages = []
            remaining = message
            while len(remaining) > 400:
                split_idx = remaining.rfind(' ', 0, 400)
                if split_idx == -1:
                    split_idx = 400
                messages.append(remaining[:split_idx])
                remaining = remaining[split_idx:].strip()
            if remaining:
                messages.append(remaining)

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

async def dispatch_command(command_name, args_str, ctx):
    command_name = command_name.lower()
    parts = args_str.strip().split() if args_str else []
    
    try:
        if command_name in ('attack', 'atk'):
            await combat_cog.cmd_attack._callback(combat_cog, ctx)
            
        elif command_name in ('skill', 'sk'):
            skill_name = parts[0] if len(parts) > 0 else ""
            target = " ".join(parts[1:]) if len(parts) > 1 else ""
            await combat_cog.cmd_skill._callback(combat_cog, ctx, skill_name=skill_name, target=target)
            
        elif command_name in ('ultimate', 'ult'):
            await combat_cog.cmd_ultimate._callback(combat_cog, ctx)
            
        elif command_name == 'def':
            skill_name = " ".join(parts) if parts else ""
            await combat_cog.cmd_def._callback(combat_cog, ctx, skill_name=skill_name)
            
        elif command_name in ('spawn', 'sp', 'spwn'):
            type_arg = parts[0] if parts else 'normal'
            await combat_cog.cmd_spawn._callback(combat_cog, ctx, type_arg=type_arg)
            
        elif command_name in ('boss', 'bs'):
            await info_cog.cmd_boss._callback(info_cog, ctx)
            
        elif command_name in ('register', 'reg', 'regis'):
            await info_cog.cmd_register._callback(info_cog, ctx, *parts)
            
        elif command_name in ('changeclass', 'cc', 'ccl'):
            new_class = parts[0] if parts else ""
            await info_cog.cmd_changeclass._callback(info_cog, ctx, new_class=new_class)
            
        elif command_name in ('rename', 'rn'):
            await info_cog.cmd_rename._callback(info_cog, ctx, new_name=args_str)
            
        elif command_name in ('inventory', 'inv'):
            await info_cog.cmd_inventory._callback(info_cog, ctx)
            
        elif command_name in ('equip', 'eq'):
            await info_cog.cmd_equip._callback(info_cog, ctx, item_name=args_str)
            
        elif command_name in ('unequip', 'uneq', 'uq'):
            slot_name = parts[0] if parts else ""
            await info_cog.cmd_unequip._callback(info_cog, ctx, slot_name=slot_name)
            
        elif command_name in ('sell', 'sel'):
            await info_cog.cmd_sell._callback(info_cog, ctx, target=args_str)
            
        elif command_name in ('stats', 'stat', 'st'):
            await info_cog.cmd_stats._callback(info_cog, ctx)
            
        elif command_name == 'info':
            await info_cog.cmd_info._callback(info_cog, ctx)
            
        elif command_name in ('classes', 'class', 'cls'):
            await info_cog.cmd_classes._callback(info_cog, ctx)
            
        elif command_name in ('gold', 'money', 'gld'):
            await info_cog.cmd_gold._callback(info_cog, ctx)
            
        elif command_name in ('shop', 'shp'):
            await info_cog.cmd_shop._callback(info_cog, ctx)
            
        elif command_name in ('buy', 'b'):
            item_name = parts[0] if parts else ""
            await info_cog.cmd_buy._callback(info_cog, ctx, item_name=item_name)

        elif command_name in ('inspect', 'equipment', 'equipments', 'ins'):
            target_name = parts[0] if parts else ""
            await info_cog.cmd_inspect._callback(info_cog, ctx, target_name=target_name)
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
            conn = db.get_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM players")
            players = c.fetchall()
            
            changed = False
            for row in players:
                player = dict(row)
                pid = player['id']
                stats = calculate_player_stats(player)
                
                max_hp = stats['max_hp']
                max_mp = stats['max_mp']
                current_hp = player.get('hp', 0)
                current_mp = player.get('mp', 0)
                
                # Cap HP and MP if they exceed max
                if current_hp > max_hp or current_mp > max_mp:
                    current_hp = min(current_hp, max_hp)
                    current_mp = min(current_mp, max_mp)
                    c.execute("UPDATE players SET hp = ?, mp = ? WHERE id = ?", (current_hp, current_mp, pid))
                    changed = True
                
                # MP Regen (all players)
                new_mp = current_mp
                if current_mp < max_mp:
                    new_mp = min(current_mp + 10, max_mp)
                    c.execute("UPDATE players SET mp = ? WHERE id = ?", (new_mp, pid))
                    changed = True
                    
                # HP Regen (active, alive players)
                alive, _ = check_cooldown(pid, 'respawn')
                last_active_time = LAST_ACTIVE.get(pid)
                active = last_active_time and (now - last_active_time) <= timeout_limit
                
                if alive and active:
                    if current_hp < max_hp:
                        regen_amount = max(5, int(max_hp * 0.02))
                        new_hp = min(current_hp + regen_amount, max_hp)
                        c.execute("UPDATE players SET hp = ? WHERE id = ?", (new_hp, pid))
                        changed = True
                        
            conn.commit()
            conn.close()
            
            boss = boss_manager.get_current_boss()
            if boss:
                # Boss wipe timeout check
                state = boss_manager.boss_state.get(boss['instance_id'])
                if state and 'wipe_time' in state:
                    if now - state['wipe_time'] > datetime.timedelta(minutes=3):
                        db.update_boss(boss['instance_id'], {'current_hp': boss['max_hp']})
                        del state['wipe_time']
                        boss['current_hp'] = boss['max_hp']
                        changed = True
                        emit_to_overlay('combat_event', {
                            'username': '💀 System',
                            'action': f'The party was wiped for 3 minutes. {boss["name"]} has fully recovered!',
                            'damage': 0, 'is_crit': False,
                            'boss_hp': boss['max_hp']
                        })
            
            if changed and boss:
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

async def websocket_listener():
    config = load_config()
    sb_config = config.get('streamerbot', {})
    ws_url = sb_config.get('ws_url', 'ws://127.0.0.1:8080/')
    
    while True:
        try:
            print(f"Connecting to Streamer.bot WebSocket at {ws_url}...")
            async with websockets.connect(ws_url) as websocket:
                print("Connected to Streamer.bot WebSocket!")
                
                # Subscribe to Twitch events
                sub_payload = {
                    "request": "Subscribe",
                    "events": {
                        "Twitch": ["ChatMessage", "RewardRedemption"]
                    },
                    "id": "rpg-bot-subscription"
                }
                await websocket.send(json.dumps(sub_payload))
                
                async for message in websocket:
                    try:
                        event_obj = json.loads(message)
                        
                        # Check subscription confirmation
                        if event_obj.get('status') == 'ok' and event_obj.get('id') == 'rpg-bot-subscription':
                            print("Successfully subscribed to Twitch events!")
                            continue
                            
                        event_type = event_obj.get('event', {}).get('type')
                        event_source = event_obj.get('event', {}).get('source')
                        data = event_obj.get('data', {})
                        
                        if event_source == 'Twitch':
                            if event_type == 'ChatMessage':
                                msg_text = data.get('text') or data.get('message', {}).get('message') or ""
                                username = data.get('userName') or data.get('userLogin') or data.get('user', {}).get('name') or data.get('user', {}).get('login') or ""
                                print(f"[Twitch Chat] {username}: {msg_text}")
                                
                                # Process bits if present
                                bits = 0
                                try:
                                    bits = int(data.get('bits') or data.get('message', {}).get('bits') or 0)
                                except:
                                    pass
                                    
                                if bits >= 100:
                                    print(f"[Bits Art] {username} cheered {bits} bits with message: {msg_text}")
                                    asyncio.create_task(process_art_bits(username, bits, msg_text))
                                    
                                if msg_text.startswith('!'):
                                    parts = msg_text.split(' ', 1)
                                    command_name = parts[0][1:].lower()
                                    args_str = parts[1] if len(parts) > 1 else ""
                                    print(f"[Command] Triggered !{command_name} with args '{args_str}' by {username}")
                                    
                                    ctx = WSContext(websocket, data, config)
                                    asyncio.create_task(dispatch_command(command_name, args_str, ctx))
                                    
                            elif event_type == 'RewardRedemption':
                                reward_name = data.get('rewardName')
                                user = data.get('user') or data.get('userName') or ""
                                if reward_name == 'Revive Party':
                                    handle_websocket_revive(user)
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        print(f"Error handling WebSocket message: {e}")
                        traceback.print_exc()
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"WebSocket connection error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error in WebSocket client: {e}. Reconnecting in 5 seconds...")
            traceback.print_exc()
            await asyncio.sleep(5)

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
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Start both the listener and the background tasks
    loop.create_task(regen_loop())
    loop.create_task(boss_attack_loop())
    
    # Check mode from config
    config = load_config()
    sb_config = config.get('streamerbot', {})
    use_server = sb_config.get('use_python_ws_server', False)
    
    if use_server:
        loop.run_until_complete(websocket_server_listener())
    else:
        loop.run_until_complete(websocket_listener())