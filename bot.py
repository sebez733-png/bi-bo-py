# ============================================================
# ADMIN PANEL ROUTES — ADD THESE TO bot.py (inside Flask section)
# ============================================================
# Place these routes BEFORE the run_flask() function in bot.py
# ============================================================

# ── CONFIG (place near the top of bot.py with other configs) ──
ADMIN_CREDENTIALS = {
    'superadmin': {'password': 'admin123', 'role': 'super'},
    'admin1':     {'password': 'pass123',  'role': 'regular'},
}

# ── ADD THIS TO game_state dict (already in bot.py, just add missing keys) ──
# game_state['max_winners'] = 1
# game_state['winner_count'] = 0
# game_state['paused'] = False

# ============================================================
# SOCKET EVENTS — Add to initSocket section (after existing events)
# ============================================================

@socketio.on('admin_manual_call')
def on_admin_manual_call(data):
    """Admin manually calls a specific number."""
    number = data.get('number')
    admin  = data.get('admin', 'admin')
    if not number or not isinstance(number, int) or number < 1 or number > 75:
        return
    if number in game_state.get('called', []):
        return  # Already called
    game_state.setdefault('called', []).append(number)
    game_state['current'] = number
    print(f"📞 Admin {admin} manually called: {number}")
    emit('ball_called', {'number': number, 'manual': True, 'admin': admin}, room='bingo_main')


@socketio.on('set_max_winners')
def on_set_max_winners(data):
    """Admin sets max winners for next round."""
    mx = data.get('max', 1)
    game_state['max_winners'] = max(1, min(4, int(mx)))
    emit('max_winners_updated', {'max': game_state['max_winners']}, room='bingo_main')


@socketio.on('admin_pause_game')
def on_admin_pause_game(data):
    """Admin pauses/resumes the game."""
    game_state['paused'] = not game_state.get('paused', False)
    emit('game_paused', {'paused': game_state['paused']}, room='bingo_main')


@socketio.on('admin_cancel_game')
def on_admin_cancel_game(data):
    """Admin cancels current game."""
    game_state['running'] = False
    game_state['called']  = []
    game_state['current'] = None
    game_state['ready_players'] = {}
    game_state['winner_declared'] = False
    game_state['winner_count'] = 0
    game_state['timer_started_at'] = time_module.time()
    emit('game_cancelled', {'reason': 'admin_cancelled'}, room='bingo_main')


# ============================================================
# ADMIN API ROUTES
# ============================================================

# ── DASHBOARD ──
@flask_app.route('/api/admin/dashboard', methods=['GET', 'OPTIONS'])
def api_admin_dashboard():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()

        # Total users
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        # Today's date
        today = time_module.strftime('%Y-%m-%d')

        # Today deposits
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time LIKE ?", (today+'%',))
        today_deposits = cur.fetchone()[0]

        # Today withdrawals
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time LIKE ?", (today+'%',))
        today_withdrawals = cur.fetchone()[0]

        # Today payout (bingo wins)
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND status='completed' AND time LIKE ?", (today+'%',))
        today_payout = cur.fetchone()[0]

        # Today games
        cur.execute("SELECT COUNT(*) FROM game_sessions WHERE time LIKE ?", (today+'%',))
        games_today = cur.fetchone()[0]

        # Pending deposits (type=deposit, status=pending)
        cur.execute("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND status='pending'")
        pending_deposits = cur.fetchone()[0]

        con.close()

        today_profit = today_deposits - today_payout

        return jsonify({
            'success': True,
            'active_online': len(game_state.get('ready_players', {})),
            'total_users': total_users,
            'today_deposits': today_deposits,
            'today_withdrawals': today_withdrawals,
            'today_profit': today_profit,
            'today_payout': today_payout,
            'games_today': games_today,
            'running_games': 1 if game_state.get('running') else 0,
            'pending_deposits': pending_deposits,
            'pending_withdrawals': len(withdraw_requests),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── DEPOSITS ──
@flask_app.route('/api/admin/deposits', methods=['GET', 'OPTIONS'])
def api_admin_deposits():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("""
            SELECT t.id, t.user_id, u.first_name, u.phone, t.amount, t.method, t.tx_id, t.status, t.time
            FROM transactions t
            LEFT JOIN users u ON t.user_id = u.user_id
            WHERE t.type='deposit'
            ORDER BY t.id DESC LIMIT 200
        """)
        rows = cur.fetchall()
        con.close()
        deposits = []
        for r in rows:
            deposits.append({
                'id': r[0], 'user_id': r[1], 'username': r[2] or '—',
                'phone': r[3] or '—', 'amount': r[4], 'method': r[5] or 'Telebirr',
                'tx_id': r[6] or '—', 'status': r[7] or 'pending', 'time': r[8] or ''
            })
        return jsonify({'success': True, 'deposits': deposits})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── APPROVE DEPOSIT ──
@flask_app.route('/api/admin/approve_deposit', methods=['POST', 'OPTIONS'])
def api_approve_deposit():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    deposit_id = data.get('deposit_id')
    user_id    = data.get('user_id')
    amount     = data.get('amount', 0)
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("UPDATE transactions SET status='completed' WHERE id=?", (deposit_id,))
        cur.execute("UPDATE users SET play_balance = play_balance + ? WHERE user_id=?", (amount, user_id))
        con.commit()
        con.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── REJECT DEPOSIT ──
@flask_app.route('/api/admin/reject_deposit', methods=['POST', 'OPTIONS'])
def api_reject_deposit():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    deposit_id = data.get('deposit_id')
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("UPDATE transactions SET status='rejected' WHERE id=?", (deposit_id,))
        con.commit()
        con.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── WITHDRAWALS ──
@flask_app.route('/api/admin/withdrawals', methods=['GET', 'OPTIONS'])
def api_admin_withdrawals():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    # Merge in-memory withdraw_requests with DB records
    withdrawals = []
    for req_num, req in withdraw_requests.items():
        withdrawals.append({
            'id': req_num,
            'user_id': req['user_id'],
            'username': '—',
            'phone': req.get('phone', '—'),
            'amount': req['amount'],
            'method': req.get('method', 'Telebirr'),
            'status': 'pending',
            'time': time_module.strftime('%Y-%m-%d %H:%M:%S'),
        })
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("""
            SELECT t.id, t.user_id, u.first_name, u.phone, t.amount, t.method, t.status, t.time
            FROM transactions t LEFT JOIN users u ON t.user_id=u.user_id
            WHERE t.type='withdraw' ORDER BY t.id DESC LIMIT 100
        """)
        for r in cur.fetchall():
            withdrawals.append({'id':r[0],'user_id':r[1],'username':r[2]or'—','phone':r[3]or'—','amount':r[4],'method':r[5]or'Telebirr','status':r[6]or'pending','time':r[7]or''})
        con.close()
    except:
        pass
    return jsonify({'success': True, 'withdrawals': withdrawals})


# ── APPROVE WITHDRAWAL ──
@flask_app.route('/api/admin/approve_withdrawal', methods=['POST', 'OPTIONS'])
def api_approve_withdrawal():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    withdrawal_id = data.get('withdrawal_id')
    user_id       = data.get('user_id')
    amount        = data.get('amount', 0)
    if withdrawal_id in withdraw_requests:
        update_main_balance(user_id, -amount)
        add_transaction(user_id, 'withdraw', amount)
        del withdraw_requests[withdrawal_id]
    return jsonify({'success': True})


# ── REJECT WITHDRAWAL ──
@flask_app.route('/api/admin/reject_withdrawal', methods=['POST', 'OPTIONS'])
def api_reject_withdrawal():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    withdrawal_id = data.get('withdrawal_id')
    if withdrawal_id in withdraw_requests:
        del withdraw_requests[withdrawal_id]
    return jsonify({'success': True})


# ── USERS LIST ──
@flask_app.route('/api/admin/users', methods=['GET', 'OPTIONS'])
def api_admin_users():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("""
            SELECT u.user_id, u.first_name, u.phone, u.main_balance, u.play_balance,
                   u.is_agent, u.language,
                   (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id) as games_played,
                   (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id AND g.status='Won') as games_won,
                   (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as referral_count
            FROM users u ORDER BY u.user_id DESC LIMIT 500
        """)
        rows = cur.fetchall()
        con.close()
        users = []
        for r in rows:
            users.append({
                'user_id': r[0], 'first_name': r[1] or '—', 'phone': r[2] or '—',
                'main_balance': r[3] or 0, 'play_balance': r[4] or 0,
                'is_agent': r[5] or 0, 'language': r[6] or 'am',
                'games_played': r[7] or 0, 'games_won': r[8] or 0,
                'referral_count': r[9] or 0, 'status': 'active',
            })
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── ADD BALANCE ──
@flask_app.route('/api/admin/add_balance', methods=['POST', 'OPTIONS'])
def api_add_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    update_main_balance(user_id, amount)
    add_transaction(user_id, 'admin_add', amount)
    return jsonify({'success': True, 'new_balance': get_main_balance(user_id)})


# ── REMOVE BALANCE ──
@flask_app.route('/api/admin/remove_balance', methods=['POST', 'OPTIONS'])
def api_remove_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    update_main_balance(user_id, -amount)
    add_transaction(user_id, 'admin_remove', amount)
    return jsonify({'success': True, 'new_balance': get_main_balance(user_id)})


# ── BAN USER ──
@flask_app.route('/api/admin/ban_user', methods=['POST', 'OPTIONS'])
def api_ban_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        con.execute("UPDATE users SET status='banned' WHERE user_id=?", (user_id,))
        con.commit(); con.close()
    except: pass
    return jsonify({'success': True})


# ── UNBAN USER ──
@flask_app.route('/api/admin/unban_user', methods=['POST', 'OPTIONS'])
def api_unban_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        con.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
        con.commit(); con.close()
    except: pass
    return jsonify({'success': True})


# ── MARK VIP ──
@flask_app.route('/api/admin/mark_vip', methods=['POST', 'OPTIONS'])
def api_mark_vip():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    vip     = data.get('vip', True)
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        con.execute("UPDATE users SET is_vip=? WHERE user_id=?", (1 if vip else 0, user_id))
        con.commit(); con.close()
    except: pass
    return jsonify({'success': True})


# ── MANUAL CALL ──
@flask_app.route('/api/admin/manual_call', methods=['POST', 'OPTIONS'])
def api_manual_call():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data   = request.json or {}
    number = data.get('number')
    if not number or number < 1 or number > 75:
        return jsonify({'success': False, 'error': 'Invalid number'}), 400
    if number in game_state.get('called', []):
        return jsonify({'success': False, 'error': 'Already called'}), 400
    game_state.setdefault('called', []).append(number)
    game_state['current'] = number
    socketio.emit('ball_called', {'number': number, 'manual': True}, room='bingo_main')
    return jsonify({'success': True, 'number': number})


# ── SET MAX WINNERS ──
@flask_app.route('/api/admin/set_max_winners', methods=['POST', 'OPTIONS'])
def api_set_max_winners():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    mx = max(1, min(4, int(data.get('max_winners', 1))))
    game_state['max_winners'] = mx
    socketio.emit('max_winners_updated', {'max': mx}, room='bingo_main')
    return jsonify({'success': True, 'max_winners': mx})


# ── PAUSE GAME ──
@flask_app.route('/api/admin/pause_game', methods=['POST', 'OPTIONS'])
def api_pause_game():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    game_state['paused'] = not game_state.get('paused', False)
    socketio.emit('game_paused', {'paused': game_state['paused']}, room='bingo_main')
    return jsonify({'success': True, 'paused': game_state['paused']})


# ── CANCEL GAME ──
@flask_app.route('/api/admin/cancel_game', methods=['POST', 'OPTIONS'])
def api_cancel_game():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    game_state['running'] = False
    game_state['called']  = []
    game_state['ready_players'] = {}
    game_state['winner_declared'] = False
    game_state['timer_started_at'] = time_module.time()
    socketio.emit('game_cancelled', {'reason': 'admin_cancelled'}, room='bingo_main')
    return jsonify({'success': True})


# ── RANKINGS ──
@flask_app.route('/api/admin/rankings', methods=['GET', 'OPTIONS'])
def api_admin_rankings():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    category = request.args.get('category', 'deposit')
    period   = request.args.get('period', 'week')
    limit    = int(request.args.get('limit', 30))
    if category == 'deposit':
        rows = get_top_by_deposit(period, limit)
    elif category == 'invite':
        rows = get_top_by_invitations(period, limit)
    else:
        rows = get_top_by_games(period, limit)
    rankings = []
    for r in rows:
        try:
            import sqlite3
            con = sqlite3.connect("bot.db", check_same_thread=False)
            cur = con.cursor()
            cur.execute("SELECT phone FROM users WHERE user_id=?", (r[0],))
            ph = cur.fetchone()
            con.close()
            phone = ph[0] if ph else '—'
        except:
            phone = '—'
        rankings.append({'user_id': r[0], 'name': r[1] or 'User', 'phone': phone, 'value': r[2]})
    return jsonify({'success': True, 'rankings': rankings})


# ── GAME HISTORY (admin) ──
@flask_app.route('/api/admin/game_history', methods=['GET', 'OPTIONS'])
def api_admin_game_history():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        import sqlite3
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        cur.execute("""
            SELECT game_id,
                   COUNT(DISTINCT user_id) as players,
                   SUM(entry_amount) as total_income,
                   SUM(prize) as payout,
                   MAX(time) as date
            FROM game_sessions
            GROUP BY game_id
            ORDER BY date DESC LIMIT 100
        """)
        rows = cur.fetchall()
        con.close()
        games = []
        for r in rows:
            pot    = r[2] or 0
            payout = r[3] or 0
            games.append({
                'game_id': r[0], 'players': r[1], 'total_income': pot,
                'payout': payout, 'profit': pot - payout, 'date': r[4] or ''
            })
        return jsonify({'success': True, 'games': games})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── REPORTS ──
@flask_app.route('/api/admin/reports', methods=['GET', 'OPTIONS'])
def api_admin_reports():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    period = request.args.get('period', 'daily')
    try:
        import sqlite3
        from datetime import datetime, timedelta
        con = sqlite3.connect("bot.db", check_same_thread=False)
        cur = con.cursor()
        rows = []
        if period == 'daily':
            for i in range(7, -1, -1):
                d = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
                cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time LIKE ?", (d+'%',))
                dep = cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time LIKE ?", (d+'%',))
                wit = cur.fetchone()[0]
                cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time LIKE ?", (d+'%',))
                pay = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM game_sessions WHERE time LIKE ?", (d+'%',))
                games = cur.fetchone()[0]
                rows.append({'date':d,'deposits':dep,'withdrawals':wit,'payout':pay,'games':games,'profit':dep-wit-pay})
        con.close()
        return jsonify({'success': True, 'rows': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── SETTINGS ──
@flask_app.route('/api/admin/settings', methods=['POST', 'OPTIONS'])
def api_admin_settings():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    # Settings are stored in memory for now — connect to DB in future
    data = request.json or {}
    print(f"⚙️ Settings updated by {data.get('admin','admin')}: {data}")
    return jsonify({'success': True})
