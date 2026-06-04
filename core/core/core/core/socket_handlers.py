from flask import request
from flask_socketio import emit, join_room, leave_room
import time as time_module
from core.game_state import get_game_state, count_total_cards, default_game_state, game_states
from core.game_logic import generate_game_id, schedule_room_reset

def register_socket_events(socketio):
    
    @socketio.on('connect')
    def on_connect():
        print(f'🔌 Client connected: {request.sid}')

    @socketio.on('disconnect')
    def on_disconnect():
        print(f'🔌 Client disconnected: {request.sid}')

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
        
        # ✅ SERVER GENERATES THE GAME ID! Client does NOT decide.
        if not game['running']:
            game['timer_started_at'] = time_module.time()
            game['game_id'] = generate_game_id()
            socketio.emit('countdown_update', {
                'room': room, 
                'game_id': game['game_id'], 
                'time_left': 35
            }, room=f'bingo_room_{room}')

    @socketio.on('player_ready')
    def on_player_ready(data):
        room = data.get('room', '10')
        game = get_game_state(room)
        user_id = data.get('user_id')
        name = data.get('name', 'Player')
        cards = data.get('cards', [])
        game_id = data.get('game_id')

        if game_id == game.get('game_id') and not game.get('winner_declared', False):
            game['ready_players'][user_id] = {
                'name': name, 'cards': cards, 'card_num': cards[0] if cards else '—'
            }
            total = count_total_cards(game)
            game['total_players'] = total
        else:
            total = count_total_cards(game)

        socketio.emit('player_joined', {
            'room': room, 'total_players': total, 'player_name': name
        }, room=f'bingo_room_{room}')

    @socketio.on('declare_winner')
    def on_declare_winner(data):
        room = data.get('room', '10')
        game = get_game_state(room)
        
        try: stake = int(room)
        except ValueError: stake = 10

        user_id = data.get('user_id')
        winner_name = data.get('name', 'Player')
        card_num = data.get('card_num', '—')
        card_index = data.get('card_index', 0)
        game_id = data.get('game_id', game.get('game_id'))

        if game.get('winner_declared', False): return
        
        game['winner_declared'] = True
        game['running'] = False # Stop calling balls!

        if user_id not in game['ready_players']:
            game['ready_players'][user_id] = {'name': winner_name, 'cards': [], 'card_num': card_num}

        total_players = count_total_cards(game)
        prize = round(total_players * stake * 0.8)

        socketio.emit('winner_found', {
            'room': room, 'user_id': user_id, 'winner_name': winner_name, 
            'card_num': card_num, 'card_index': card_index, 'prize': prize, 
            'total_players': total_players, 'game_id': game_id,
        }, room=f'bingo_room_{room}')

        # Schedule the room reset
        schedule_room_reset(socketio, room)

    @socketio.on('admin_manual_call')
    def on_admin_manual_call(data):
        room = data.get('room', '10')
        game = get_game_state(room)
        number = data.get('number')
        if not number or not isinstance(number, int) or number < 1 or number > 75: return
        if number in game.get('called', []): return
        game.setdefault('called', []).append(number)
        game['current'] = number
        socketio.emit('ball_called', {'room': room, 'number': number, 'manual': True}, room=f'bingo_room_{room}')

    @socketio.on('set_max_winners')
    def on_set_max_winners(data):
        room = data.get('room', '10')
        game = get_game_state(room)
        mx = data.get('max', 1)
        game['max_winners'] = max(1, min(4, int(mx)))
        socketio.emit('max_winners_updated', {'room': room, 'max': game['max_winners']}, room=f'bingo_room_{room}')

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
