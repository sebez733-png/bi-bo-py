import time as time_module

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
        'current': None
    }

# Separate states for Room 10 and Room 20
game_states = {
    '10': default_game_state(),
    '20': default_game_state()
}

def get_game_state(room):
    """Get or create game state for a room"""
    if room not in game_states:
        game_states[room] = default_game_state()
    return game_states[room]

def count_total_cards(game):
    """Count total cards across all ready players"""
    return sum(len(p.get('cards', [])) for p in game.get('ready_players', {}).values())
