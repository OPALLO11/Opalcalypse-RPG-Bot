import os
import sys
import time
import asyncio
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fix common Windows asyncio bug (RuntimeError: Event loop is closed)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from api.server import run_flask_api
from bot import run_bot

def main():
    print("Starting Twitch RPG Bot Services...")

    # Register helper callbacks to break circular imports
    try:
        from database import db
        from game.helpers import find_item_data
        from game.logic import calculate_player_stats, get_required_exp
        db.register_helpers(find_item_data, calculate_player_stats, get_required_exp)
        print("[DB] Injected helper callbacks successfully.")
    except Exception as e:
        print(f"[DB Error] Failed to register dynamic helpers: {e}")
    
    # Start Flask API in a separate daemon thread
    flask_thread = threading.Thread(target=run_flask_api, daemon=True)
    flask_thread.start()
    
    # Give Flask a moment to bind the port before the bot starts sending API requests
    time.sleep(1.5)
    
    print("\nStarting Streamer.bot WebSocket bridge client...")
    
    # Start Twitch Bot in the main thread (since it requires the main asyncio event loop)
    # This will block until the bot is closed
    try:
        run_bot()
    except Exception as e:
        import traceback
        print("\n[CRITICAL ERROR] Bot crashed with the following error:")
        traceback.print_exc()
        
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down services gracefully...")
