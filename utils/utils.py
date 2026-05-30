import concurrent.futures
import json
import os

import requests


_http_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="HTTPExecutor")


def load_config():
    def get_bool(key, default):
        val = os.environ.get(key)
        if val is None: return default
        return str(val).lower() in ('true', '1', 'yes')

    def get_int(key, default):
        val = os.environ.get(key)
        if val is None: return default
        try: return int(val)
        except: return default

    def get_float(key, default):
        val = os.environ.get(key)
        if val is None: return default
        try: return float(val)
        except: return default

    def get_list(key, default):
        val = os.environ.get(key)
        if val is None: return default
        return [x.strip() for x in val.split(',') if x.strip()]

    return {
        "twitch": {
            "username": os.environ.get("TWITCH_USERNAME", ""),
            # "oauth_token": os.environ.get("TWITCH_TOKEN", ""),
            "channel": os.environ.get("TWITCH_CHANNEL", ""),
            "client_id": os.environ.get("TWITCH_CLIENT_ID", ""),
            "client_secret": os.environ.get("TWITCH_CLIENT_SECRET", ""),
            "bot_id": os.environ.get("TWITCH_BOT_ID", "")
        },
        "gemini": {
            "api_key": os.environ.get("OPENAI_API_KEY", os.environ.get("GEMINI_API_KEY", "")),
            "model": os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")
        },
        "discord": {
            "webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", ""),
            "enabled": get_bool("DISCORD_ENABLED", False)
        },
        "tts": {
            "enabled": get_bool("TTS_ENABLED", False),
            "voice": os.environ.get("TTS_VOICE", "en-US-ChristopherNeural"),
            "rate": get_float("TTS_RATE", 1.2),
            "volume": get_float("TTS_VOLUME", 0.8),
            "min_message_length": get_int("TTS_MIN_MESSAGE_LENGTH", 3),
            "blacklist_users": get_list("TTS_BLACKLIST_USERS", ["nightbot", "streamelements", "streamlabs", "moobot", "fossabot"])
        },
        "overlay": {
            "websocket_port": get_int("OVERLAY_WEBSOCKET_PORT", 8080),
            "host": os.environ.get("OVERLAY_HOST", "localhost")
        },
        "game": {
            "boss_spawn_on_start": get_bool("GAME_BOSS_SPAWN_ON_START", True),
            "boss_timer_minutes": get_int("GAME_BOSS_TIMER_MINUTES", 20),
            "enable_weekly_boss": get_bool("GAME_ENABLE_WEEKLY_BOSS", True),
            "weekly_boss_chance": get_float("GAME_WEEKLY_BOSS_CHANCE", 0.1),
            "enable_monthly_boss": get_bool("GAME_ENABLE_MONTHLY_BOSS", True),
            "monthly_boss_chance": get_float("GAME_MONTHLY_BOSS_CHANCE", 0.05),
            "damage_multiplier": get_float("GAME_DAMAGE_MULTIPLIER", 1.0),
            "xp_multiplier": get_float("GAME_XP_MULTIPLIER", 1.0),
            "drop_rate_multiplier": get_float("GAME_DROP_RATE_MULTIPLIER", 1.0)
        },
        "bits_art": {
            "enabled": get_bool("BITS_ART_ENABLED", True),
            "min_bits_random": get_int("BITS_ART_MIN_BITS_RANDOM", 100),
            "min_bits_custom": get_int("BITS_ART_MIN_BITS_CUSTOM", 300),
            "display_duration_seconds": get_int("BITS_ART_DISPLAY_DURATION_SECONDS", 45),
            "random_prompts": [
                "A beautiful thank you card with flowers and sparkles, fantasy art style",
                "A cute chibi anime character saying thank you with heart eyes",
                "A fantasy wizard casting a gratitude spell with golden sparkles",
                "A kawaii cat holding a thank you sign in a flower garden",
                "An epic hero bowing in gratitude under cherry blossoms",
                "A magical forest spirit offering a glowing flower of thanks",
                "A futuristic robot displaying a heart on its holographic screen",
                "A pixel art hero throwing confetti and fireworks celebration",
                "A majestic dragon holding a thank you banner flying in the sky"
            ]
        },
        "streamerbot": {
            "enabled": get_bool("STREAMERBOT_ENABLED", True),
            "http_url": os.environ.get("STREAMERBOT_HTTP_URL", "http://127.0.0.1:7474/DoAction"),
            "bot_action_name": os.environ.get("STREAMERBOT_BOT_ACTION_NAME", "SendBotMessage"),
            "use_python_ws_server": get_bool("STREAMERBOT_USE_PYTHON_WS_SERVER", False),
            "ws_url": os.environ.get("STREAMERBOT_WS_URL", "ws://127.0.0.1:8080/"),
            "python_ws_port": get_int("STREAMERBOT_PYTHON_WS_PORT", 6789)
        },
        "chat": {
            "prefix_enabled": get_bool("TWITCH_CHAT_PREFIX_ENABLED", True),
            "prefix": os.environ.get("TWITCH_CHAT_PREFIX", "⚔️ ")
        }
    }


def emit_to_overlay(event_name, data):
    def _do_post():
        try:
            host = os.environ.get('FLASK_HOST', '127.0.0.1')
            port = os.environ.get('FLASK_PORT', '5000')
            url = f"http://{host}:{port}/internal/emit"
            resp = requests.post(url, json={"event": event_name, "data": data}, timeout=1)
            if resp.status_code != 200:
                print(f"[Overlay Error] Failed to emit event {event_name}: Status {resp.status_code}")
        except Exception:
            pass

    _http_executor.submit(_do_post)


def write_obs_boss_files(boss_name, current_hp, max_hp):
    """Write boss details to local text files for OBS GDI+ text source integration"""
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(data_dir, exist_ok=True)

        name_path = os.path.join(data_dir, 'obs_boss_name.txt')
        hp_path = os.path.join(data_dir, 'obs_boss_hp.txt')

        with open(name_path, 'w', encoding='utf-8') as f:
            f.write(boss_name)

        pct = (current_hp / max_hp) * 100 if max_hp > 0 else 0
        hp_str = f"HP: {current_hp:,} / {max_hp:,} ({pct:.1f}%)"

        with open(hp_path, 'w', encoding='utf-8') as f:
            f.write(hp_str)
    except Exception as e:
        print(f"Error writing OBS boss text files: {e}")


_bot_instance = None
_loop_instance = None


def set_bot(bot, loop):
    global _bot_instance, _loop_instance
    _bot_instance = bot
    _loop_instance = loop


def format_twitch_chat_message(message):
    """Apply the optional Twitch chat prefix without duplicating it."""
    msg = str(message)
    chat_config = load_config().get("chat", {})
    if not chat_config.get("prefix_enabled", True):
        return msg

    prefix = chat_config.get("prefix", "⚔️ ")
    if not prefix or msg.startswith(prefix):
        return msg

    return f"{prefix}{msg}"


async def send_twitch_chat(ctx, message):
    await ctx.send(format_twitch_chat_message(message))


def send_streamerbot_message(message):
    """Send message to Twitch chat using RPGBot if active; fallback to Streamer.bot HTTP API"""
    global _bot_instance, _loop_instance
    message = format_twitch_chat_message(message)

    def _fallback_send_streamerbot(msg):
        config = load_config()
        sb_config = config.get('streamerbot', {})
        if not sb_config.get('enabled', False):
            return

        http_url = sb_config.get('http_url', 'http://127.0.0.1:8080/DoAction')
        action_name = sb_config.get('bot_action_name', 'SendBotMessage')

        payload = {
            "action": {
                "name": action_name
            },
            "args": {
                "message": msg
            }
        }
        try:
            res = requests.post(http_url, json=payload, timeout=2)
            success = res.status_code in (200, 204)
            safe_msg = msg[:80].encode('ascii', 'backslashreplace').decode('ascii')
            if success:
                print(f"[HTTP->SB] Message sent successfully (status {res.status_code}): {safe_msg}")
            else:
                print(f"[HTTP->SB] Unexpected status {res.status_code} for message: {safe_msg}")
        except Exception as e:
            print(f"[HTTP->SB Exception] Failed to send message to Streamer.bot: {e}")

    if _bot_instance and _loop_instance:
        config = load_config()
        twitch_config = config.get('twitch', {})
        channel_name = twitch_config.get('channel') or os.environ.get('TWITCH_CHANNEL') or 'opallo11'

        async def _send():
            sent = False
            try:
                from game.helpers import split_message
                messages = split_message(message, max_len=400)

                users = await _bot_instance.fetch_users(logins=[channel_name])
                if users:
                    broadcaster = users[0]
                    for msg in messages:
                        await broadcaster.send_message(msg, sender=_bot_instance.bot_id)
                    sent = True
                else:
                    print(
                        f"[TwitchIO Send Error] Bot has not joined channel: {channel_name}. Falling back to Streamer.bot...")
            except Exception as ex:
                print(f"[TwitchIO Send Exception] {ex}. Falling back to Streamer.bot...")

            if not sent:
                _http_executor.submit(_fallback_send_streamerbot, message)

        import asyncio
        try:
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None

            if current_loop == _loop_instance:
                _loop_instance.create_task(_send())
            else:
                asyncio.run_coroutine_threadsafe(_send(), _loop_instance)
            return True
        except Exception as e:
            print(f"Error scheduling native Twitch message: {e}")
            _http_executor.submit(_fallback_send_streamerbot, message)
            return True

    _http_executor.submit(_fallback_send_streamerbot, message)
    return True
