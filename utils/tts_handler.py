import os
import json
import threading

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')

with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

class TTSManager:
    def __init__(self):
        self.enabled = config['tts'].get('enabled', True)
        self.blacklist = config['tts'].get('blacklist_users', [])
        self.min_len = config['tts'].get('min_message_length', 3)
        self.engine = None
        if self.enabled:
            try:
                import pyttsx3
                self.engine = pyttsx3.init()
                self.engine.setProperty('rate', int(config['tts'].get('rate', 1.2) * 150))
                self.engine.setProperty('volume', config['tts'].get('volume', 0.8))
            except Exception as e:
                print(f"TTS Init Error, Disabling. Error: {e}")
                self.enabled = False

    def speak(self, username, message):
        if not self.enabled or not self.engine: return
        if username.lower() in self.blacklist: return
        if len(message) < self.min_len: return
        if message.startswith('!'): return
        
        text = f"{username} says. {message}"
        def run_tts():
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                pass
            
        threading.Thread(target=run_tts, daemon=True).start()

tts_manager = TTSManager()
