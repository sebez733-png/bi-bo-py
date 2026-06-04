import random
import time as time_module
import threading
from core.game_state import game_states, get_game_state, count_total_cards

def generate_game_id():
    d = time_module.localtime()
    return f"{d.tm_year}{d.tm_mon:02d}{d.tm_mday:02d}_{int(time_module.time()%10000)}"

def schedule_room_reset(socketio, room):
    """Reset room 12 seconds after a winner is found"""
    def reset_task():
        time_module.sleep(12)
        from core.game_state import default_game_state
        game_states[room] = default_game_state()
        game_states[room]['timer_started_at'] = time_module.time()
        # Tell clients a new round is starting
        socketio.emit('countdown_update', {
            'room': room,
            'game_id': game_states[room]['game_id'],
            'time_left': 35
        }, room=f'bingo_room_{room}')

    threading.Thread(target=reset_task, daemon=True).start()

def auto_call_loop(socketio):
    """The ONLY place balls are generated. Server is the boss."""
    CALL_INTERVAL = 3
    while True:
        time_module.sleep(CALL_INTERVAL)
        for room_id in list(game_states.keys()):
            game = game_states.get(room_id)
            if not game:
                continue

            # AUTO-START: When countdown expires, start the game on server
            if not game['running'] and game.get('timer_started_at') and not game.get('winner_declared'):
                elapsed = int(time_module.time() - game['timer_started_at'])
                if elapsed >= 35:
                    game['running'] = True
                    game['started_at'] = time_module.time()
                    game['timer_started_at'] = None
                    game['winner_declared'] = False
                    game['winner_count'] = 0
                    game['called'] = []  # Reset called numbers!
                    game['current'] = None
                    
                    socketio.emit('game_started', {
                        'room': room_id,
                        'game_id': game.get('game_id', ''),
                        'total_players': count_total_cards(game)
                    }, room=f'bingo_room_{room_id}')

            # Call balls if game is running
            if game.get('running') and not game.get('paused') and not game.get('winner_declared'):
                called = game.get('called', [])
                if len(called) >= 75:
                    continue

                available = [n for n in range(1, 76) if n not in called]
                if not available:
                    continue

                number = random.choice(available)

                # Re-fetch in case game was reset
                game = game_states.get(room_id)
                if not game or not game.get('running'):
                    continue

                game.setdefault('called', []).append(number)
                game['current'] = number

                socketio.emit('ball_called', {
                    'room': room_id,
                    'number': number
                }, room=f'bingo_room_{room_id}')
