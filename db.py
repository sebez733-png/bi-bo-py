import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("bot.db", check_same_thread=False)

cursor = conn.cursor()

# ==========================================
# TABLE CREATION
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT DEFAULT '',
    phone TEXT,
    main_balance INTEGER DEFAULT 0,
    play_balance INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL,
    is_agent INTEGER DEFAULT 0,
    is_vip INTEGER DEFAULT 0,
    language TEXT DEFAULT 'am',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    method TEXT DEFAULT 'System',
    tx_id TEXT,
    status TEXT DEFAULT 'pending',
    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    referred_by INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS game_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    game_id TEXT,
    cards TEXT,
    entry_amount INTEGER DEFAULT 10,
    status TEXT DEFAULT 'playing',
    result TEXT DEFAULT '-',
    prize INTEGER DEFAULT 0,
    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# ==========================================
# MIGRATIONS — Add columns to existing databases
# ==========================================

migrations = [
    ("users", "first_name",  "TEXT DEFAULT ''"),
    ("users", "is_agent",    "INTEGER DEFAULT 0"),
    ("users", "is_vip",      "INTEGER DEFAULT 0"),
    ("users", "language",    "TEXT DEFAULT 'am'"),
    ("users", "status",      "TEXT DEFAULT 'active'"),
    ("users", "created_at",  "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("transactions", "type",   "TEXT DEFAULT 'unknown'"),
    ("transactions", "time",   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("transactions", "method", "TEXT DEFAULT 'System'"),
    ("transactions", "status", "TEXT DEFAULT 'pending'"),
    ("game_sessions", "time",  "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
]

for table, column, col_type in migrations:
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass  # Column already exists

conn.commit()


def get_cursor():
    return conn.cursor()


# ==========================================
# USER FUNCTIONS
# ==========================================

def add_user(user_id, phone='', first_name='', referred_by=None):
    """Create a new user. Optionally set referred_by on creation."""
    cur = get_cursor()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, phone, first_name, referred_by, status, created_at)
        VALUES (?, ?, ?, ?, 'active', ?)
    """, (user_id, phone, first_name, referred_by, now))
    conn.commit()
    # If user already existed but had no first_name, update it
    if first_name:
        cur.execute("UPDATE users SET first_name=? WHERE user_id=? AND (first_name IS NULL OR first_name='')", (first_name, user_id))
        conn.commit()


def update_user_name(user_id, first_name):
    cur = get_cursor()
    cur.execute("UPDATE users SET first_name=? WHERE user_id=?", (first_name, user_id))
    conn.commit()


def user_exists(user_id):
    cur = get_cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    return cur.fetchone() is not None


def get_user(user_id):
    """Return basic user info tuple."""
    cur = get_cursor()
    cur.execute("""
        SELECT user_id, phone, main_balance, play_balance, referred_by
        FROM users WHERE user_id=?
    """, (user_id,))
    return cur.fetchone()


def get_user_full(user_id):
    """Return full user info dict — used by admin panel."""
    cur = get_cursor()
    cur.execute("""
        SELECT user_id, first_name, phone, main_balance, play_balance,
               referred_by, is_agent, is_vip, language, status, created_at
        FROM users WHERE user_id=?
    """, (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        'user_id':      row[0],
        'first_name':   row[1] or '',
        'phone':        row[2] or '',
        'main_balance': row[3] or 0,
        'play_balance': row[4] or 0,
        'referred_by':  row[5],
        'is_agent':     row[6] or 0,
        'is_vip':       row[7] or 0,
        'language':     row[8] or 'am',
        'status':       row[9] or 'active',
        'created_at':   row[10] or '',
    }


def get_user_name(user_id):
    cur = get_cursor()
    cur.execute("SELECT first_name FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 'User'


def get_user_phone(user_id):
    cur = get_cursor()
    cur.execute("SELECT phone FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ==========================================
# BALANCE FUNCTIONS
# ==========================================

def get_main_balance(user_id):
    cur = get_cursor()
    cur.execute("SELECT main_balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def update_main_balance(user_id, amount):
    cur = get_cursor()
    cur.execute("UPDATE users SET main_balance = main_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    # Return new balance
    cur.execute("SELECT main_balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_play_balance(user_id):
    cur = get_cursor()
    cur.execute("SELECT play_balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def update_play_balance(user_id, amount):
    cur = get_cursor()
    cur.execute("UPDATE users SET play_balance = play_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    cur.execute("SELECT play_balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def deduct_bet_smart(user_id, amount):
    """
    Deduct bet amount: use play wallet first.
    If play wallet not enough, use main wallet.
    If both not enough, return False.
    Returns dict with new balances on success, False on failure.
    """
    play_bal = get_play_balance(user_id)
    main_bal = get_main_balance(user_id)

    if play_bal >= amount:
        # Enough in play wallet
        update_play_balance(user_id, -amount)
    elif play_bal + main_bal >= amount:
        # Use all play wallet + rest from main wallet
        remaining = amount - play_bal
        update_play_balance(user_id, -play_bal)
        update_main_balance(user_id, -remaining)
    else:
        return False

    return {
        'main_balance': get_main_balance(user_id),
        'play_balance': get_play_balance(user_id),
    }


# ==========================================
# REFERRAL FUNCTIONS
# ==========================================

def set_referral(user_id, referred_by):
    cur = get_cursor()
    # Don't overwrite if already set
    cur.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row and row[0] is None:
        cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user_id))
        conn.commit()


def get_referral_count(user_id):
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_depositing_referrals_count(user_id):
    cur = get_cursor()
    cur.execute("""
        SELECT COUNT(DISTINCT u.user_id)
        FROM users u
        JOIN transactions t ON u.user_id = t.user_id
        WHERE u.referred_by=? AND t.type='deposit' AND t.status='completed'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_total_referral_deposits(user_id):
    cur = get_cursor()
    cur.execute("""
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        WHERE u.referred_by=? AND t.type='deposit' AND t.status='completed'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


# ==========================================
# TRANSACTION FUNCTIONS
# ==========================================

def add_transaction(user_id, tx_type, amount, method="System", tx_id=None, status='completed'):
    """
    Add a transaction record.
    - status: 'pending' for deposits/withdrawals awaiting admin approval
    - status: 'completed' for instant transactions (admin_add, bingo_win, bet, etc.)
    - tx_id: optional transaction ID from payment provider
    """
    cur = get_cursor()
    # Generate a unique tx_id if none provided
    if tx_id is None and tx_type in ('deposit', 'withdraw'):
        tx_id = f"{tx_type.upper()}_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    cur.execute("""
        INSERT INTO transactions (user_id, type, amount, method, tx_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, tx_type, amount, method, tx_id, status))
    conn.commit()
    return cur.lastrowid


def update_transaction_status(tx_id_or_id, new_status):
    """
    Update a transaction's status by its tx_id or row id.
    Returns True if updated, False if not found.
    """
    cur = get_cursor()
    if isinstance(tx_id_or_id, int):
        cur.execute("UPDATE transactions SET status=? WHERE id=?", (new_status, tx_id_or_id))
    else:
        cur.execute("UPDATE transactions SET status=? WHERE tx_id=?", (new_status, tx_id_or_id))
    conn.commit()
    return cur.rowcount > 0


def get_transaction_by_id(tx_id):
    """Get a transaction by its row id or tx_id string."""
    cur = get_cursor()
    if isinstance(tx_id, int):
        cur.execute("SELECT * FROM transactions WHERE id=?", (tx_id,))
    else:
        cur.execute("SELECT * FROM transactions WHERE tx_id=?", (tx_id,))
    return cur.fetchone()


def get_last_5_transactions(user_id):
    cur = get_cursor()
    cur.execute("""
        SELECT type, amount, time
        FROM transactions
        WHERE user_id=? AND status='completed'
        ORDER BY id DESC LIMIT 5
    """, (user_id,))
    return cur.fetchall()


def get_all_transactions(user_id, limit=20):
    cur = get_cursor()
    cur.execute("""
        SELECT type, amount, status, time
        FROM transactions
        WHERE user_id=?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    return cur.fetchall()


def get_total_deposits(user_id):
    cur = get_cursor()
    cur.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id=? AND type='deposit' AND status='completed'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


def transaction_exists(tx_id):
    if not tx_id:
        return False
    cur = get_cursor()
    cur.execute("SELECT 1 FROM transactions WHERE tx_id=?", (tx_id,))
    return cur.fetchone() is not None


# ==========================================
# DEPOSIT FUNCTIONS (Admin)
# ==========================================

def add_pending_deposit(user_id, amount, method='Telebirr', tx_id=None, phone=None):
    """Create a pending deposit transaction. Admin must approve it."""
    if phone:
        cur = get_cursor()
        cur.execute("UPDATE users SET phone=? WHERE user_id=? AND (phone IS NULL OR phone='')", (phone, user_id))
        conn.commit()
    row_id = add_transaction(user_id, 'deposit', amount, method, tx_id, status='pending')
    return row_id


def approve_deposit(transaction_id):
    """
    Approve a pending deposit:
    1. Set transaction status to 'completed'
    2. Add amount to user's play_balance
    Returns (success, user_id, amount) tuple.
    """
    cur = get_cursor()
    # Get transaction details
    cur.execute("SELECT user_id, amount, status FROM transactions WHERE id=?", (transaction_id,))
    row = cur.fetchone()
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    # Update transaction status
    cur.execute("UPDATE transactions SET status='completed' WHERE id=?", (transaction_id,))
    # Add to play balance
    cur.execute("UPDATE users SET play_balance = play_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    return True, user_id, amount


def reject_deposit(transaction_id):
    """
    Reject a pending deposit:
    1. Set transaction status to 'rejected'
    Returns (success, user_id) tuple.
    """
    cur = get_cursor()
    cur.execute("SELECT user_id, status FROM transactions WHERE id=?", (transaction_id,))
    row = cur.fetchone()
    if not row:
        return False, None
    user_id, current_status = row[0], row[1]
    if current_status != 'pending':
        return False, user_id
    cur.execute("UPDATE transactions SET status='rejected' WHERE id=?", (transaction_id,))
    conn.commit()
    return True, user_id


def get_all_deposits(limit=200):
    """Get all deposit transactions for admin panel."""
    cur = get_cursor()
    cur.execute("""
        SELECT t.id, t.user_id, u.first_name, u.phone, t.amount, t.method, t.tx_id, t.status, t.time
        FROM transactions t
        LEFT JOIN users u ON t.user_id = u.user_id
        WHERE t.type='deposit'
        ORDER BY t.id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    deposits = []
    for r in rows:
        deposits.append({
            'id': r[0], 'user_id': r[1], 'username': r[2] or '—',
            'phone': r[3] or '—', 'amount': r[4], 'method': r[5] or 'Telebirr',
            'tx_id': r[6] or '—', 'status': r[7] or 'pending', 'time': r[8] or ''
        })
    return deposits


def get_pending_deposits_count():
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND status='pending'")
    row = cur.fetchone()
    return row[0] if row else 0


# ==========================================
# WITHDRAWAL FUNCTIONS (Admin)
# ==========================================

def add_pending_withdrawal(user_id, amount, method='Telebirr', phone=None):
    """Create a pending withdrawal. Deducts from main_balance immediately."""
    main_bal = get_main_balance(user_id)
    if main_bal < amount:
        return None  # Insufficient balance
    # Deduct from main balance
    update_main_balance(user_id, -amount)
    # Record as pending
    row_id = add_transaction(user_id, 'withdraw', amount, method, status='pending')
    return row_id


def approve_withdrawal(transaction_id):
    """
    Approve a pending withdrawal — money already deducted.
    Just mark transaction as completed.
    """
    cur = get_cursor()
    cur.execute("SELECT user_id, amount, status FROM transactions WHERE id=?", (transaction_id,))
    row = cur.fetchone()
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    cur.execute("UPDATE transactions SET status='completed' WHERE id=?", (transaction_id,))
    conn.commit()
    return True, user_id, amount


def reject_withdrawal(transaction_id):
    """
    Reject a pending withdrawal — refund the money back to user.
    """
    cur = get_cursor()
    cur.execute("SELECT user_id, amount, status FROM transactions WHERE id=?", (transaction_id,))
    row = cur.fetchone()
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    # Refund the money
    cur.execute("UPDATE transactions SET status='rejected' WHERE id=?", (transaction_id,))
    cur.execute("UPDATE users SET main_balance = main_balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    return True, user_id, amount


def get_all_withdrawals(limit=100):
    """Get all withdrawal transactions for admin panel."""
    cur = get_cursor()
    cur.execute("""
        SELECT t.id, t.user_id, u.first_name, u.phone, t.amount, t.method, t.status, t.time
        FROM transactions t
        LEFT JOIN users u ON t.user_id = u.user_id
        WHERE t.type='withdraw'
        ORDER BY t.id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    withdrawals = []
    for r in rows:
        withdrawals.append({
            'id': r[0], 'user_id': r[1], 'username': r[2] or '—',
            'phone': r[3] or '—', 'amount': r[4], 'method': r[5] or 'Telebirr',
            'status': r[6] or 'pending', 'time': r[7] or ''
        })
    return withdrawals


def get_pending_withdrawals_count():
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE type='withdraw' AND status='pending'")
    row = cur.fetchone()
    return row[0] if row else 0


# ==========================================
# GAME SESSION FUNCTIONS
# ==========================================

def add_game_session(user_id, game_id, cards, entry_amount=10):
    """Record that user joined a game — one row per card."""
    cur = get_cursor()
    if isinstance(cards, list) and len(cards) > 0:
        for card in cards:
            cur.execute("""
                INSERT INTO game_sessions (user_id, game_id, cards, entry_amount, status, result)
                VALUES (?, ?, ?, ?, 'playing', '-')
            """, (user_id, game_id, str(card), entry_amount))
    else:
        cur.execute("""
            INSERT INTO game_sessions (user_id, game_id, cards, entry_amount, status, result)
            VALUES (?, ?, ?, ?, 'playing', '-')
        """, (user_id, game_id, str(cards), entry_amount))
    conn.commit()


def complete_game_session(user_id, game_id, result='-', prize=0):
    """Update game session when game ends."""
    cur = get_cursor()
    status = 'Won' if prize > 0 else 'Completed'
    result_str = f'+{prize} Br' if prize > 0 else '-'
    cur.execute("""
        UPDATE game_sessions
        SET status=?, result=?, prize=?
        WHERE user_id=? AND game_id=? AND status='playing'
    """, (status, result_str, prize, user_id, game_id))
    conn.commit()


def get_game_history(user_id, limit=20):
    """Get user's game history for mini app."""
    cur = get_cursor()
    cur.execute("""
        SELECT game_id, entry_amount, status, result, time
        FROM game_sessions
        WHERE user_id=?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    return cur.fetchall()


def get_games_played_count(user_id):
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_games_won_count(user_id):
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=? AND status='Won'", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_total_won(user_id):
    cur = get_cursor()
    cur.execute("SELECT COALESCE(SUM(prize),0) FROM game_sessions WHERE user_id=? AND status='Won'", (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


# ==========================================
# PROFILE STATS
# ==========================================

def get_profile_stats(user_id):
    """Get all profile stats for mini app in one call."""
    cur = get_cursor()
    cur.execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=?", (user_id,))
    games_played = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=? AND status='Won'", (user_id,))
    games_won = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(prize),0) FROM game_sessions WHERE user_id=? AND status='Won'", (user_id,))
    total_won = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
    invited = cur.fetchone()[0]
    return {
        'games_played': games_played,
        'games_won':    games_won,
        'total_won':    total_won,
        'invited':      invited,
    }


# ==========================================
# LEADERBOARD FUNCTIONS
# ==========================================

def get_period_start(period):
    """Get the start datetime string for a given period."""
    now = datetime.utcnow()
    if period == 'week':
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=7)
    return start.strftime('%Y-%m-%d %H:%M:%S')


def get_top_by_deposit(period='week', limit=30):
    """Top users by number of completed deposits."""
    since = get_period_start(period)
    cur = get_cursor()
    cur.execute("""
        SELECT u.user_id, u.first_name, COUNT(t.id) as total
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.type='deposit' AND t.status='completed' AND t.time >= ?
        GROUP BY t.user_id
        ORDER BY total DESC
        LIMIT ?
    """, (since, limit))
    return cur.fetchall()


def get_top_by_invitations(period='week', limit=30):
    """Top users by number of invites."""
    since = get_period_start(period)
    cur = get_cursor()

    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]

    if 'created_at' in columns:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(inv.user_id) as total
            FROM users u
            JOIN users inv ON inv.referred_by = u.user_id
            WHERE inv.created_at >= ?
            GROUP BY u.user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
        """, (since, limit))
    else:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(inv.user_id) as total
            FROM users u
            JOIN users inv ON inv.referred_by = u.user_id
            GROUP BY u.user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
        """, (limit,))

    return cur.fetchall()


def get_top_by_games(period='week', limit=30):
    """Top users by number of games played."""
    since = get_period_start(period)
    cur = get_cursor()

    cur.execute("PRAGMA table_info(game_sessions)")
    columns = [col[1] for col in cur.fetchall()]

    if 'time' in columns:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(g.id) as total
            FROM game_sessions g
            JOIN users u ON g.user_id = u.user_id
            WHERE g.time >= ?
            GROUP BY g.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (since, limit))
    else:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(g.id) as total
            FROM game_sessions g
            JOIN users u ON g.user_id = u.user_id
            GROUP BY g.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (limit,))

    return cur.fetchall()


def get_top_by_wins(period='week', limit=30):
    """Top users by number of games won."""
    since = get_period_start(period)
    cur = get_cursor()

    cur.execute("PRAGMA table_info(game_sessions)")
    columns = [col[1] for col in cur.fetchall()]

    if 'time' in columns:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(g.id) as total
            FROM game_sessions g
            JOIN users u ON g.user_id = u.user_id
            WHERE g.status='Won' AND g.time >= ?
            GROUP BY g.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (since, limit))
    else:
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(g.id) as total
            FROM game_sessions g
            JOIN users u ON g.user_id = u.user_id
            WHERE g.status='Won'
            GROUP BY g.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (limit,))

    return cur.fetchall()


def get_user_rank(user_id, period='week', category='deposit'):
    """Get a user's rank and value for a given category."""
    if category == 'deposit':
        rows = get_top_by_deposit(period, 1000)
    elif category == 'invite':
        rows = get_top_by_invitations(period, 1000)
    elif category == 'wins':
        rows = get_top_by_wins(period, 1000)
    else:
        rows = get_top_by_games(period, 1000)

    for i, row in enumerate(rows):
        if row[0] == user_id:
            return i + 1, row[2]
    return None, 0


# ==========================================
# ADMIN: USER MANAGEMENT
# ==========================================

def get_all_users_with_stats(limit=500):
    """Get all users with their game/referral stats for admin panel."""
    cur = get_cursor()
    cur.execute("""
        SELECT u.user_id, u.first_name, u.phone, u.main_balance, u.play_balance,
               u.is_agent, u.is_vip, u.language, u.status,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id) as games_played,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id AND g.status='Won') as games_won,
               (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as referral_count
        FROM users u
        ORDER BY u.user_id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    users = []
    for r in rows:
        users.append({
            'user_id':        r[0],
            'first_name':     r[1] or '—',
            'phone':          r[2] or '—',
            'main_balance':   r[3] or 0,
            'play_balance':   r[4] or 0,
            'is_agent':       r[5] or 0,
            'is_vip':         r[6] or 0,
            'language':       r[7] or 'am',
            'status':         r[8] or 'active',
            'games_played':   r[9] or 0,
            'games_won':      r[10] or 0,
            'referral_count': r[11] or 0,
        })
    return users


def ban_user(user_id):
    cur = get_cursor()
    cur.execute("UPDATE users SET status='banned' WHERE user_id=?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def unban_user(user_id):
    cur = get_cursor()
    cur.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def mark_vip(user_id, vip=True):
    cur = get_cursor()
    cur.execute("UPDATE users SET is_vip=? WHERE user_id=?", (1 if vip else 0, user_id))
    conn.commit()
    return cur.rowcount > 0


def is_user_banned(user_id):
    cur = get_cursor()
    cur.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row and row[0] == 'banned'


# ==========================================
# ADMIN: DASHBOARD STATS
# ==========================================

def get_dashboard_stats():
    """Get all dashboard statistics in one call."""
    cur = get_cursor()
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Total users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

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

    # Pending deposits count
    cur.execute("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND status='pending'")
    pending_deposits = cur.fetchone()[0]

    # Pending withdrawals count
    cur.execute("SELECT COUNT(*) FROM transactions WHERE type='withdraw' AND status='pending'")
    pending_withdrawals = cur.fetchone()[0]

    today_profit = today_deposits - today_payout

    return {
        'total_users':         total_users,
        'today_deposits':      today_deposits,
        'today_withdrawals':   today_withdrawals,
        'today_profit':        today_profit,
        'today_payout':        today_payout,
        'games_today':         games_today,
        'pending_deposits':    pending_deposits,
        'pending_withdrawals': pending_withdrawals,
    }


# ==========================================
# ADMIN: GAME HISTORY
# ==========================================

def get_admin_game_history(limit=100):
    """Get game history for admin panel — grouped by game_id."""
    cur = get_cursor()
    cur.execute("""
        SELECT game_id,
               COUNT(user_id) as total_cards,
               SUM(entry_amount) as total_income,
               SUM(prize) as payout,
               MAX(time) as date
        FROM game_sessions
        GROUP BY game_id
        ORDER BY date DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    games = []
    for r in rows:
        pot    = r[2] or 0
        payout = r[3] or 0
        cards  = r[1] or 0
        bet    = round(pot / cards) if cards > 0 else 10
        games.append({
            'game_id':      r[0],
            'players':      cards,
            'bet':          bet,
            'total_income': pot,
            'payout':       payout,
            'profit':       pot - payout,
            'date':         r[4] or ''
        })
    return games


# ==========================================
# ADMIN: REPORTS
# ==========================================

def get_admin_reports(period='daily'):
    """Get financial reports for admin panel."""
    cur = get_cursor()
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
            rows.append({
                'date': d, 'deposits': dep, 'withdrawals': wit,
                'payout': pay, 'games': games, 'profit': dep - wit - pay
            })
    elif period == 'weekly':
        for i in range(3, -1, -1):
            week_start = (datetime.utcnow() - timedelta(weeks=i))
            week_start = week_start - timedelta(days=week_start.weekday())
            week_end = week_start + timedelta(days=6)
            d_start = week_start.strftime('%Y-%m-%d')
            d_end = week_end.strftime('%Y-%m-%d')
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time >= ? AND time <= ?", (d_start, d_end+'%'))
            dep = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time >= ? AND time <= ?", (d_start, d_end+'%'))
            wit = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time >= ? AND time <= ?", (d_start, d_end+'%'))
            pay = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM game_sessions WHERE time >= ? AND time <= ?", (d_start, d_end+'%'))
            games = cur.fetchone()[0]
            rows.append({
                'date': f"{d_start} to {d_end}", 'deposits': dep, 'withdrawals': wit,
                'payout': pay, 'games': games, 'profit': dep - wit - pay
            })
    elif period == 'monthly':
        for i in range(5, -1, -1):
            dt = datetime.utcnow() - timedelta(days=i*30)
            m = dt.strftime('%Y-%m')
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time LIKE ?", (m+'%',))
            dep = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time LIKE ?", (m+'%',))
            wit = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time LIKE ?", (m+'%',))
            pay = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM game_sessions WHERE time LIKE ?", (m+'%',))
            games = cur.fetchone()[0]
            rows.append({
                'date': m, 'deposits': dep, 'withdrawals': wit,
                'payout': pay, 'games': games, 'profit': dep - wit - pay
            })

    return rows


# ==========================================
# AGENT SYSTEM FUNCTIONS
# ==========================================

def is_user_agent(user_id):
    cur = get_cursor()
    cur.execute("SELECT is_agent FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row and row[0] == 1


def check_and_upgrade_agent(user_id):
    """Check if user qualifies for agent upgrade and upgrade if so."""
    if is_user_agent(user_id):
        return False
    invites = get_referral_count(user_id)
    depositors = get_depositing_referrals_count(user_id)
    total_deps = get_total_referral_deposits(user_id)
    # Thresholds — adjust as needed
    if invites >= 30 and depositors >= 20 and total_deps >= 3000:
        cur = get_cursor()
        cur.execute("UPDATE users SET is_agent=1 WHERE user_id=?", (user_id,))
        conn.commit()
        return True
    return False


# ==========================================
# LANGUAGE FUNCTIONS
# ==========================================

def get_user_language(user_id):
    cur = get_cursor()
    cur.execute("SELECT language FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 'am'


def set_user_language(user_id, lang):
    cur = get_cursor()
    cur.execute("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))
    conn.commit()


# ==========================================
# PHONE LOOKUP
# ==========================================
def get_user_by_phone(phone):
    """Find a user by phone number — handles various Ethiopian phone formats."""
    clean = phone.replace(" ", "").replace("+", "").replace("-", "").replace("(", "").replace(")", "")
    variations = [clean]
    if clean.startswith("251"):
        variations.append("0" + clean[3:])
        variations.append("+251" + clean[3:])
    elif clean.startswith("0"):
        variations.append("251" + clean[1:])
        variations.append("+251" + clean[1:])
    elif len(clean) == 9 and not clean.startswith("0"):
        variations.append("0" + clean)
        variations.append("251" + clean)
        variations.append("+251" + clean)
    variations = list(set(variations))
    placeholders = ",".join(["?"] * len(variations))
    cur = get_cursor()
    cur.execute(f"""
        SELECT user_id, phone, main_balance, play_balance, referred_by
        FROM users WHERE phone IN ({placeholders})
    """, variations)
    return cur.fetchone()


def freeze_user(user_id):
    cur = get_cursor()
    cur.execute("UPDATE users SET status='frozen' WHERE user_id=?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def unfreeze_user(user_id):
    cur = get_cursor()
    cur.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
    conn.commit()
    return cur.rowcount > 0
