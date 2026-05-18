import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("bot.db", check_same_thread=False)

cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    phone TEXT,
    main_balance INTEGER DEFAULT 0,
    play_balance INTEGER DEFAULT 0,
    referred_by INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    method TEXT,
    tx_id TEXT UNIQUE,
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

# Game sessions table — tracks every game a user plays
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

try:
    cursor.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'unknown'")
except:
    pass

try:
    cursor.execute("ALTER TABLE transactions ADD COLUMN time TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
except:
    pass

try:
    cursor.execute("ALTER TABLE users ADD COLUMN is_agent INTEGER DEFAULT 0")
except:
    pass

try:
    cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'am'")
except:
    pass

try:
    cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''")
except:
    pass

# ✅ FIX: Add created_at column for invite period filtering
try:
    cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
except:
    pass

conn.commit()


def get_cursor():
    return conn.cursor()


# ==========================================
# USER FUNCTIONS
# ==========================================

def add_user(user_id, phone, first_name=''):
    cur = get_cursor()
    # ✅ FIX: Use strftime to match SQLite CURRENT_TIMESTAMP format
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, phone, main_balance, play_balance, first_name, created_at)
        VALUES (?, ?, 0, 0, ?, ?)
    """, (user_id, phone, first_name, now))
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
    cur = get_cursor()
    cur.execute("""
        SELECT user_id, phone, main_balance, play_balance, referred_by
        FROM users WHERE user_id=?
    """, (user_id,))
    return cur.fetchone()


def get_user_name(user_id):
    cur = get_cursor()
    cur.execute("SELECT first_name FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 'User'


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
    cur.execute("""
        UPDATE users SET main_balance = main_balance + ? WHERE user_id=?
    """, (amount, user_id))
    conn.commit()


def get_play_balance(user_id):
    cur = get_cursor()
    cur.execute("SELECT play_balance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def update_play_balance(user_id, amount):
    cur = get_cursor()
    cur.execute("""
        UPDATE users SET play_balance = play_balance + ? WHERE user_id=?
    """, (amount, user_id))
    conn.commit()


def deduct_bet_smart(user_id, amount):
    """
    Deduct bet amount: use play wallet first.
    If play wallet not enough, use main wallet.
    If both not enough, return False.
    """
    play_bal = get_play_balance(user_id)
    main_bal = get_main_balance(user_id)

    if play_bal >= amount:
        # Enough in play wallet
        update_play_balance(user_id, -amount)
        return True
    elif play_bal + main_bal >= amount:
        # Use all play wallet + rest from main wallet
        remaining = amount - play_bal
        update_play_balance(user_id, -play_bal)
        update_main_balance(user_id, -remaining)
        return True
    else:
        return False


# ==========================================
# REFERRAL FUNCTIONS
# ==========================================

def set_referral(user_id, referred_by):
    cur = get_cursor()
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
        WHERE u.referred_by=? AND t.type='deposit'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0


def get_total_referral_deposits(user_id):
    cur = get_cursor()
    cur.execute("""
        SELECT SUM(t.amount)
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        WHERE u.referred_by=? AND t.type='deposit'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


# ==========================================
# TRANSACTION FUNCTIONS
# ==========================================

def add_transaction(user_id, tx_type, amount, method="System"):
    cur = get_cursor()
    cur.execute("""
        INSERT INTO transactions (user_id, type, amount, method, tx_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, tx_type, amount, method, None, 'completed'))
    conn.commit()


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
        SELECT SUM(amount)
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
# GAME SESSION FUNCTIONS
# ==========================================

def add_game_session(user_id, game_id, cards, entry_amount=10):
    """Record that user joined a game"""
    cur = get_cursor()
    cards_str = ','.join(str(c) for c in cards) if isinstance(cards, list) else str(cards)
    cur.execute("""
        INSERT INTO game_sessions (user_id, game_id, cards, entry_amount, status, result)
        VALUES (?, ?, ?, ?, 'playing', '-')
    """, (user_id, game_id, cards_str, entry_amount))
    conn.commit()


def complete_game_session(user_id, game_id, result='-', prize=0):
    """Update game session when game ends"""
    cur = get_cursor()
    status = 'Won' if prize > 0 else 'Completed'
    result_str = f'+{prize} Br' if prize > 0 else '-'
    cur.execute("""
        UPDATE game_sessions
        SET status=?, result=?, prize=?
        WHERE user_id=? AND game_id=?
    """, (status, result_str, prize, user_id, game_id))
    conn.commit()


def get_game_history(user_id, limit=20):
    """Get user's game history for mini app"""
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
    cur.execute("""
        SELECT SUM(prize) FROM game_sessions WHERE user_id=? AND status='Won'
    """, (user_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0


# ==========================================
# LEADERBOARD FUNCTIONS
# ==========================================

# ✅ FIX: Use strftime to match SQLite CURRENT_TIMESTAMP format (space, not T)
def get_period_start(period):
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
    since = get_period_start(period)
    cur = get_cursor()
    # ✅ FIX: COUNT(t.id) = how many times deposited, NOT SUM(t.amount)
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
    since = get_period_start(period)
    cur = get_cursor()

    # Check if created_at column exists (for older databases)
    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]

    if 'created_at' in columns:
        # Period-filtered: count only users referred since the period start
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
        # Fallback: all-time count (no created_at column yet)
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
    since = get_period_start(period)
    cur = get_cursor()

    # Check if time column exists in game_sessions
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
        # Fallback: all-time
        cur.execute("""
            SELECT u.user_id, u.first_name, COUNT(g.id) as total
            FROM game_sessions g
            JOIN users u ON g.user_id = u.user_id
            GROUP BY g.user_id
            ORDER BY total DESC
            LIMIT ?
        """, (limit,))

    return cur.fetchall()


def get_user_rank(user_id, period='week', category='deposit'):
    if category == 'deposit':
        rows = get_top_by_deposit(period, 1000)
    elif category == 'invite':
        rows = get_top_by_invitations(period, 1000)
    else:
        rows = get_top_by_games(period, 1000)

    for i, row in enumerate(rows):
        if row[0] == user_id:
            return i + 1, row[2]
    return None, 0


# ==========================================
# AGENT SYSTEM FUNCTIONS
# ==========================================

def is_user_agent(user_id):
    cur = get_cursor()
    cur.execute("SELECT is_agent FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return row and row[0] == 1


def check_and_upgrade_agent(user_id):
    if is_user_agent(user_id):
        return False
    invites = get_referral_count(user_id)
    depositors = get_depositing_referrals_count(user_id)
    total_deps = get_total_referral_deposits(user_id)
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