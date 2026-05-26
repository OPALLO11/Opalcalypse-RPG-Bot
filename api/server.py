import os

from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO

from database import db

# Use the proj/public directory for overlay and art
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
ART_DIR = os.path.join(PUBLIC_DIR, 'art')

app = Flask(__name__, template_folder=PUBLIC_DIR, static_url_path='', static_folder=PUBLIC_DIR)
app.config['SECRET_KEY'] = 'secret_twitch_rpg!'
socketio = SocketIO(app, cors_allowed_origins='*')


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    boss = db.get_active_boss()
    if boss:
        socketio.emit('boss_update', boss, to=request.sid)
        from game.combat import get_party_data
        socketio.emit('party_update', get_party_data(boss), to=request.sid)

    active_challenge = db.get_active_challenge()
    if active_challenge:
        socketio.emit('challenge_update', active_challenge, to=request.sid)


@app.route('/internal/emit', methods=['POST'])
def internal_emit():
    data = request.json
    if data and 'event' in data and 'data' in data:
        socketio.emit(data['event'], data['data'])
        return {"status": "ok"}
    return {"status": "error"}, 400


@app.route('/art/<path:filename>')
def serve_art(filename):
    return send_from_directory(ART_DIR, filename)


@app.route('/api/streamerbot', methods=['GET', 'POST'])
def streamerbot_webhook():
    # Merge query arguments, form data, and JSON data
    data = {}
    if request.args:
        data.update(request.args.to_dict())
    if request.form:
        data.update(request.form.to_dict())
    if request.is_json and request.json:
        data.update(request.json)

    safe_data = str(data).encode('ascii', errors='backslashreplace').decode('ascii')
    print(f"[WEBHOOK] Raw data received: {safe_data}")

    user = data.get('user') or data.get('userName') or data.get('userLogin')
    reward = data.get('reward') or data.get('rewardName') or data.get('reward_name') or data.get('rewardTitle')
    target = data.get('target') or data.get('rawInput')

    safe_user = str(user).encode('ascii', errors='backslashreplace').decode('ascii')
    safe_reward = str(reward).encode('ascii', errors='backslashreplace').decode('ascii')
    safe_target = str(target).encode('ascii', errors='backslashreplace').decode('ascii')
    print(f"[WEBHOOK] Parsed user={safe_user}, reward={safe_reward}, target={safe_target}")

    reward_clean = reward.strip().lower().replace('!', '') if reward else ""

    safe_reward_clean = str(reward_clean).encode('ascii', errors='backslashreplace').decode('ascii')
    print(f"[WEBHOOK] Clean reward: {safe_reward_clean}")

    if reward_clean in ('revive party', 'ชุบชีวิตปาร์ตี้'):
        from game.combat import revive_party_members
        success, msg = revive_party_members(user)
        return {"status": "success" if success else "failed", "message": msg}, 200
    elif reward_clean in ('revive', 'revive player', 'ชุบชีวิต', 'ชุบชีวิตรายบุคคล', 'ชุบชีวิตผู้เล่น'):
        target_user = target if target else user
        if target_user:
            clean_target = target_user.strip().lower()
            if clean_target in ('me', 'myself', 'ตัวเอง', 'ชุบตัวเอง'):
                target_user = user
        if not target_user:
            return {"status": "error", "message": "No target user specified"}, 400
        from game.combat import revive_single_player
        success, msg = revive_single_player(user, target_user)
        return {"status": "success" if success else "failed", "message": msg}, 200

    return {"status": "ignored", "message": "Request ignored (invalid action or reward)"}, 200




def run_flask_api():
    port = int(os.environ.get('FLASK_PORT', 5000))
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    print(f"Starting Flask API horizontally on {host}:{port}")
    # Run without debug to avoid thread locking issues with TwitchIO
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    run_flask_api()
