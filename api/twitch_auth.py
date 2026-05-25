import os
import json
import requests
import time
from flask import redirect, request

TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tokens.json')

def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    return None

def save_tokens(tokens):
    # Add a timestamp so we know when it was saved
    if 'expires_in' in tokens:
        tokens['expires_at'] = time.time() + tokens['expires_in']
    
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f, indent=4)

def refresh_token(refresh_token_str):
    client_id = os.environ.get('TWITCH_CLIENT_ID')
    client_secret = os.environ.get('TWITCH_CLIENT_SECRET')

    if not client_id or not client_secret:
        return None

    url = 'https://id.twitch.tv/oauth2/token'
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token_str
    }
    
    response = requests.post(url, data=data)
    if response.status_code == 200:
        tokens = response.json()
        save_tokens(tokens)
        return tokens
    return None

def get_valid_token():
    tokens = load_tokens()
    if not tokens:
        return None
    
    # Check if access token is expired (adding 60 seconds buffer)
    if 'expires_at' in tokens and time.time() > tokens['expires_at'] - 60:
        if 'refresh_token' in tokens:
            new_tokens = refresh_token(tokens['refresh_token'])
            if new_tokens:
                return new_tokens.get('access_token')
            else:
                return None
        return None
        
    # Also check if it's currently valid by calling the validate endpoint
    headers = {
        'Authorization': f"OAuth {tokens['access_token']}"
    }
    resp = requests.get('https://id.twitch.tv/oauth2/validate', headers=headers)
    if resp.status_code == 200:
        return tokens['access_token']
        
    # If invalid, try to refresh
    if 'refresh_token' in tokens:
        new_tokens = refresh_token(tokens['refresh_token'])
        if new_tokens:
            return new_tokens.get('access_token')
            
    return None

def init_auth_routes(app):
    @app.route('/login')
    def login():
        client_id = os.environ.get('TWITCH_CLIENT_ID')
        if not client_id:
            return "TWITCH_CLIENT_ID is not set in .env", 500
            
        redirect_uri = 'http://localhost:5000/callback'
        # Request common scopes for a bot
        scopes = 'chat:read chat:edit bits:read channel:read:subscriptions channel:read:redemptions channel:manage:broadcast'
        
        auth_url = (
            f"https://id.twitch.tv/oauth2/authorize?client_id={client_id}"
            f"&redirect_uri={redirect_uri}&response_type=code&scope={scopes}"
        )
        return redirect(auth_url)

    @app.route('/callback')
    def callback():
        code = request.args.get('code')
        if not code:
            return "Authorization cancelled or failed.", 400
            
        client_id = os.environ.get('TWITCH_CLIENT_ID')
        client_secret = os.environ.get('TWITCH_CLIENT_SECRET')
        redirect_uri = 'http://localhost:5000/callback'
        
        url = 'https://id.twitch.tv/oauth2/token'
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri
        }
        
        response = requests.post(url, data=data)
        if response.status_code == 200:
            tokens = response.json()
            save_tokens(tokens)
            return "Authentication successful! You can close this window. The bot will now start automatically in your terminal."
        else:
            return f"Failed to get token: {response.text}", 400
