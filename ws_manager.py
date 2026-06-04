"""
ws_manager.py
=============
All WebSocket / SocketIO logic for Adwa Bingo.
Imported by bot.py — bot.py never touches socketio or game_states directly.

Exports:
  socketio       — the SocketIO instance (attached to flask_app in bot.py)
  game_states    — dict of room_id → game state
  get_game_state(room) → game dict (creates if missing)
  count_total_cards(game) → int
  generate_game_id() → str
  start_auto_call_loop() → starts the background thread
"""

import time as time_module
import random
import threading
from flask_socketio import SocketIO, emit, join_room, leave_room

# ──────────────────────────────────────────────────────────────
# SocketIO instance  (flask_app is passed in from bot.py)
# ──────────────────────────────────────────────────────────────
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')


# ──────────────────────────────────────────────────────────────
# Game State Helpers
# ──────────────────────────────────────────────────────────────
def default_game_state():
    return {
        'running': False,
        'game_id': None,
        'called': [],
        'started_at': None,
        'time_left': 35,
        'timer_started_at': None,
        'total_players': 0,
        'total_pot': 0,
        'ready_players': {},
        'winner_declared': False,
        'max_winners': 1,
        'winner_count': 0,
        'paused': False,
        'current': None,
    }


game_states = {
    '10': default_game_state(),
    '20': default_game_state(),
}


def get_game_state(room: str) -> dict:
    """Get or create game state for a room."""
    if room not in game_states:
        game_states[room] = default_game_state()
    return game_states[room]


def count_total_cards(game: dict) -> int:
    """Count total cards across all ready players."""
    return sum(len(p.get('cards', [])) for p in game.get('ready_players', {}).values())


def generate_game_id() -> str:
    d = time_module.localtime()
    return f"{d.tm_year}{d.tm_mon:02d}{d.tm_mday:02d}_{int(time_module.time() % 10000)}"


# ──────────────────────────────────────────────────────────────
# SocketIO Event Handlers
# ──────────────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    print(f'🔌 Client connected')
    for room_id, game in game_states.items():
        time_left = 0
        if game['timer_started_at'] and not game['running']:
            time_left = max(0, 35 - int(time_module.time() - game['timer_started_at']))
        emit('game_state_update', {
            'room': room_id,
            'game_running': game['running'],
            'game_id': game['game_id'],
            'time_left': time_left,
            'total_players': count_total_cards(game),
            'called_numbers': list(game.get('called', [])),
            'current_number': game.get('current'),
        })


@socketio.on('disconnect')
def on_disconnect():
    print(f'🔌 Client disconnected')


@socketio.on('join_room')
def on_join_room(data):
    room = data.get('room', '10')
    socket_room = f'bingo_room_{room}'
    join_room(socket_room)
    print(f'👤 Player joined room: {socket_room}')


@socketio.on('leave_room')
def on_leave_room(data):
    room = data.get('room', '10')
    socket_room = f'bingo_room_{room}'
    leave_room(socket_room)


@socketio.on('request_countdown')
def on_request_countdown(data):
    room = data.get('room', '10')
    game = get_game_state(room)
    if not game['running']:
        game['timer_started_at'] = time_module.time()
        game['game_id'] = data.get('game_id', generate_game_id())
        socketio.emit('countdown_update', {
            'room': room,
            'game_id': game['game_id'],
            'time_left': 35,
        }, room=f'bingo_room_{room}')


@socketio.on('player_ready')
def on_player_ready(data):
    room = data.get('room', '10')
    game = get_game_state(room)

    user_id  = data.get('user_id')
    name     = data.get('name', 'Player')
    cards    = data.get('cards', [])
    game_id  = data.get('game_id')

    if game_id == game.get('game_id') and not game.get('winner_declared', False):
        game['ready_players'][user_id] = {
            'name': name,
            'cards': cards,
            'card_num': cards[0] if cards else '—',
        }

    total = count_total_cards(game)
    game['total_players'] = total

    socketio.emit('player_joined', {
        'room': room,
        'total_players': total,
        'player_name': name,
    }, room=f'bingo_room_{room}')


@socketio.on('declare_winner')
def on_declare_winner(data):
    room = data.get('room', '10')
    game = get_game_state(room)

    if game.get('winner_declared', False):
        return
    game['winner_declared'] = True

    try:
        stake = int(room)
    except ValueError:
        stake = 10

    user_id      = data.get('user_id')
    winner_name  = data.get('name', 'Player')
    card_num     = data.get('card_num', '—')
    card_index   = data.get('card_index', 0)
    game_id      = data.get('game_id', game.get('game_id'))

    if user_id not in game['ready_players']:
        game['ready_players'][user_id] = {'name': winner_name, 'cards': [], 'card_num': card_num}

    total_players = count_total_cards(game)
    prize = round(total_players * stake * 0.8)

    socketio.emit('winner_found', {
        'room': room,
        'user_id': user_id,
        'winner_name': winner_name,
        'card_num': card_num,
        'card_index': card_index,
        'prize': prize,
        'total_players': total_players,
        'game_id': game_id,
    }, room=f'bingo_room_{room}')


@socketio.on('admin_manual_call')
def on_admin_manual_call(data):
    room   = data.get('room', '10')
    game   = get_game_state(room)
    number = data.get('number')

    if not number or not isinstance(number, int) or number < 1 or number > 75:
        return
    if number in game.get('called', []):
        return

    game.setdefault('called', []).append(number)
    game['current'] = number
    socketio.emit('ball_called', {
        'room': room,
        'number': number,
        'manual': True,
        'admin': data.get('admin', 'admin'),
    }, room=f'bingo_room_{room}')


@socketio.on('set_max_winners')
def on_set_max_winners(data):
    room = data.get('room', '10')
    game = get_game_state(room)
    mx = max(1, min(4, int(data.get('max', 1))))
    game['max_winners'] = mx
    socketio.emit('max_winners_updated', {'room': room, 'max': mx}, room=f'bingo_room_{room}')


@socketio.on('admin_pause_game')
def on_admin_pause_game(data):
    room = data.get('room', '10')
    game = get_game_state(room)
    game['paused'] = not game.get('paused', False)
    socketio.emit('game_paused', {'room': room, 'paused': game['paused']}, room=f'bingo_room_{room}')


@socketio.on('admin_cancel_game')
def on_admin_cancel_game(data):
    room = data.get('room', '10')
    game_states[room] = default_game_state()
    game_states[room]['timer_started_at'] = time_module.time()
    socketio.emit('game_cancelled', {'room': room, 'reason': 'admin_cancelled'}, room=f'bingo_room_{room}')


# ──────────────────────────────────────────────────────────────
# Auto-Call Background Thread
# ──────────────────────────────────────────────────────────────
CALL_INTERVAL = 2  # seconds between ball calls


def _auto_call_loop():
    while True:
        time_module.sleep(CALL_INTERVAL)
        for room_id in list(game_states.keys()):
            game = game_states.get(room_id)
            if not game:
                continue

            # Auto-start when countdown expires
            if (not game['running']
                    and game.get('timer_started_at')
                    and not game.get('winner_declared')):
                elapsed = int(time_module.time() - game['timer_started_at'])
                if elapsed >= 35:
                    game['running']          = True
                    game['started_at']       = time_module.time()
                    game['timer_started_at'] = None
                    game['winner_declared']  = False
                    game['winner_count']     = 0
                    socketio.emit('game_started', {
                        'room': room_id,
                        'game_id': game.get('game_id', ''),
                        'total_players': count_total_cards(game),
                    }, room=f'bingo_room_{room_id}')

            # Call balls while game is running
            if game.get('running') and not game.get('paused') and not game.get('winner_declared'):
                called = game.get('called', [])
                if len(called) >= 75:
                    continue

                available = [n for n in range(1, 76) if n not in called]
                if not available:
                    continue

                number = random.choice(available)

                # Re-fetch in case the game was reset while sleeping
                game = game_states.get(room_id)
                if not game or not game.get('running'):
                    continue

                game.setdefault('called', []).append(number)
                game['current'] = number

                socketio.emit('ball_called', {
                    'room': room_id,
                    'number': number,
                }, room=f'bingo_room_{room_id}')


def start_auto_call_loop():
    """Call this once from bot.py to start the background ball-caller."""
    t = threading.Thread(target=_auto_call_loop, daemon=True)
    t.start()
    print("✅ Auto-call loop started")
