import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import websockets
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Set loop policy for Windows if needed
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Patch utils.load_config to configure the bot for Server Integration testing
import utils.utils
import utils
original_load_config = utils.utils.load_config
def patched_load_config():
    cfg = original_load_config()
    if 'streamerbot' in cfg:
        cfg['streamerbot'] = dict(cfg['streamerbot']) # Copy
        cfg['streamerbot']['use_python_ws_server'] = True
        cfg['streamerbot']['python_ws_port'] = 6789
        cfg['streamerbot']['http_url'] = 'http://127.0.0.1:8075/DoAction'
    return cfg
utils.utils.load_config = patched_load_config
utils.load_config = patched_load_config

captured_responses = []

class MockHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress log messages
        
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data.decode('utf-8'))
            action = data.get('action', {}).get('name')
            msg = data.get('args', {}).get('message', '')
            print(f"[Mock HTTP Server] Captured message response: '{msg}'")
            captured_responses.append(msg)
        except Exception as e:
            print(f"[Mock HTTP Server] Error parsing request: {e}")
            
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

def start_mock_http_server():
    server = HTTPServer(('127.0.0.1', 8075), MockHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print("[Mock HTTP Server] Listening on http://127.0.0.1:8075/DoAction...")
    return server

async def run_client_workflow(stop_event):
    ws_url = "ws://127.0.0.1:6789/"
    print(f"[Test Client] Connecting to Python WS Server at {ws_url}...")
    
    # Connect to the bot's WebSocket server
    async with websockets.connect(ws_url) as ws:
        print("[Test Client] Connected to Python WebSocket Server!")
        
        # 1. Send !register command payload
        reg_payload = {
            "userName": "test_user_123",
            "userId": "99999",
            "message": "!register TestWarrior warrior",
            "isModerator": "false",
            "isBroadcaster": "false"
        }
        print("[Test Client] Sending mock '!register' chat event...")
        await ws.send(json.dumps(reg_payload))
        
        # Wait for HTTP server to capture the response
        start_time = time.time()
        registered = False
        while time.time() - start_time < 5:
            await asyncio.sleep(0.2)
            # Check if any captured message contains register confirmation or already registered
            if any("registered" in r.lower() for r in captured_responses):
                registered = True
                break
                
        if not registered:
            print("[Test Client] Error: Registration response not captured.")
            return False
            
        print("[Test Client] Registration verified!")
        
        # Clear captured responses to verify the next one cleanly
        captured_responses.clear()
        
        # 2. Send !stats command payload
        stats_payload = {
            "userName": "test_user_123",
            "userId": "99999",
            "message": "!stats",
            "isModerator": "false",
            "isBroadcaster": "false"
        }
        print("[Test Client] Sending mock '!stats' chat event...")
        await ws.send(json.dumps(stats_payload))
        
        # Wait for HTTP server to capture the stats response
        start_time = time.time()
        stats_verified = False
        while time.time() - start_time < 5:
            await asyncio.sleep(0.2)
            if any("stats for" in r.lower() or "hp" in r.lower() for r in captured_responses):
                stats_verified = True
                break
                
        if not stats_verified:
            print("[Test Client] Error: Stats response not captured.")
            return False
            
        print("[Test Client] Stats verified!")
        print("[Test Client] Integration Test SUCCESSFUL!")
        stop_event.set()
        return True

async def main():
    # Start HTTP server
    http_server = start_mock_http_server()
    
    # Start RPG bot in a daemon thread
    from bot import run_bot
    print("[Test Runner] Starting RPG bot...")
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Wait for RPG Bot WebSocket server to boot
    await asyncio.sleep(2)
    
    stop_event = asyncio.Event()
    success = False
    try:
        success = await asyncio.wait_for(run_client_workflow(stop_event), timeout=15)
    except asyncio.TimeoutError:
        print("[Test Runner] Error: Test timed out.")
    except Exception as e:
        print(f"[Test Runner] Error running test workflow: {e}")
        
    if success:
        print("[Test Runner] Integration test completed with SUCCESS!")
        sys.exit(0)
    else:
        print("[Test Runner] Integration test FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
