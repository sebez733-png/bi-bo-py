import psycopg2
import psycopg2.extras
from psycopg2 import pool
from datetime import datetime, timedelta
import os

# ==========================================
# DATABASE CONNECTION — PostgreSQL (Supabase)
# ==========================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.wjekrnlbeykobbchfnrl:XzWUJYeDMMS.2!@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"
)

# Connection pool — handles multiple requests at once
connection_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL,
    sslmode='require'
)


def get_conn():
    """Get a connection from the pool."""
    return connection_pool.getconn()


def release_conn(conn):
    """Return connection to the pool."""
    connection_pool.putconn(conn)


def execute(query, params=(), fetch=None):
    """
    Execute a query safely.
    fetch=None    → no return (INSERT/UPDATE/DELETE)
    fetch='one'   → return one row
    fetch='all'   → return all rows
    fetch='id'    → return lastrowid (for INSERT)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if fetch == 'one':
                result = cur.fetchone()
            elif fetch == 'all':
                result = cur.fetchall()
            elif fetch == 'id':
                result = cur.fetchone()[0] if cur.rowcount > 0 else None
            else:
                result = cur.rowcount
            conn.commit()
            return result
    except Exception as e:
        conn.rollback()
        print(f"❌ DB Error: {e}")
        print(f"Query: {query}")
        print(f"Params: {params}")
        raise e
    finally:
        release_conn(conn)


# ==========================================
# TABLE CREATION — Run once on startup
# ==========================================

def init_db():
    """Create all tables if they don't exist."""

    execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            first_name TEXT DEFAULT '',
            phone TEXT,
            main_balance INTEGER DEFAULT 0,
            play_balance INTEGER DEFAULT 0,
            referred_by BIGINT DEFAULT NULL,
            is_agent INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0,
            language TEXT DEFAULT 'am',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            type TEXT,
            amount INTEGER,
            method TEXT DEFAULT 'System',
            tx_id TEXT,
            status TEXT DEFAULT 'pending',
            time TIMESTAMP DEFAULT NOW()
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            referred_by BIGINT
        )
    """)

    execute("""
        CREATE TABLE IF NOT EXISTS game_sessions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            game_id TEXT,
            cards TEXT,
            entry_amount INTEGER DEFAULT 10,
            status TEXT DEFAULT 'playing',
            result TEXT DEFAULT '-',
            prize INTEGER DEFAULT 0,
            time TIMESTAMP DEFAULT NOW()
        )
    """)

    # Indexes for performance
    try:
        execute("CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)")
        execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")
        execute("CREATE INDEX IF NOT EXISTS idx_transactions_type_status ON transactions(type, status)")
        execute("CREATE INDEX IF NOT EXISTS idx_game_sessions_user_id ON game_sessions(user_id)")
        execute("CREATE INDEX IF NOT EXISTS idx_game_sessions_game_id ON game_sessions(game_id)")
    except:
        pass

    print("✅ Database tables ready (PostgreSQL/Supabase)")


# Run on import
init_db()


# ==========================================
# USER FUNCTIONS
# ==========================================

def add_user(user_id, phone='', first_name='', referred_by=None):
    """Create a new user."""
    execute("""
        INSERT INTO users (user_id, phone, first_name, referred_by, status, created_at)
        VALUES (%s, %s, %s, %s, 'active', NOW())
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, phone, first_name, referred_by))
    # Update name if empty
    if first_name:
        execute("""
            UPDATE users SET first_name=%s
            WHERE user_id=%s AND (first_name IS NULL OR first_name='')
        """, (first_name, user_id))


def update_user_name(user_id, first_name):
    execute("UPDATE users SET first_name=%s WHERE user_id=%s", (first_name, user_id))


def user_exists(user_id):
    row = execute("SELECT 1 FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row is not None


def get_user(user_id):
    """Return basic user info tuple."""
    return execute("""
        SELECT user_id, phone, main_balance, play_balance, referred_by
        FROM users WHERE user_id=%s
    """, (user_id,), fetch='one')


def get_user_full(user_id):
    """Return full user info dict."""
    row = execute("""
        SELECT user_id, first_name, phone, main_balance, play_balance,
               referred_by, is_agent, is_vip, language, status, created_at
        FROM users WHERE user_id=%s
    """, (user_id,), fetch='one')
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
        'created_at':   str(row[10]) if row[10] else '',
    }


def get_user_name(user_id):
    row = execute("SELECT first_name FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row and row[0] else 'User'


def get_user_phone(user_id):
    row = execute("SELECT phone FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else None


# ==========================================
# BALANCE FUNCTIONS
# ==========================================

def get_main_balance(user_id):
    row = execute("SELECT main_balance FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def update_main_balance(user_id, amount):
    execute("UPDATE users SET main_balance = main_balance + %s WHERE user_id=%s", (amount, user_id))
    row = execute("SELECT main_balance FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def get_play_balance(user_id):
    row = execute("SELECT play_balance FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def update_play_balance(user_id, amount):
    execute("UPDATE users SET play_balance = play_balance + %s WHERE user_id=%s", (amount, user_id))
    row = execute("SELECT play_balance FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def deduct_bet_smart(user_id, amount):
    """
    Deduct bet: use play wallet first.
    If play wallet not enough, use main wallet for the rest.
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
    """Set referral only if not already set."""
    row = execute("SELECT referred_by FROM users WHERE user_id=%s", (user_id,), fetch='one')
    if row and row[0] is None:
        execute("UPDATE users SET referred_by=%s WHERE user_id=%s", (referred_by, user_id))


def get_referral_count(user_id):
    row = execute("SELECT COUNT(*) FROM users WHERE referred_by=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def get_depositing_referrals_count(user_id):
    row = execute("""
        SELECT COUNT(DISTINCT u.user_id)
        FROM users u
        JOIN transactions t ON u.user_id = t.user_id
        WHERE u.referred_by=%s AND t.type='deposit' AND t.status='completed'
    """, (user_id,), fetch='one')
    return row[0] if row else 0


def get_total_referral_deposits(user_id):
    row = execute("""
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        WHERE u.referred_by=%s AND t.type='deposit' AND t.status='completed'
    """, (user_id,), fetch='one')
    return row[0] if row and row[0] else 0


# ==========================================
# TRANSACTION FUNCTIONS
# ==========================================

def add_transaction(user_id, tx_type, amount, method="System", tx_id=None, status='completed'):
    """Add a transaction record."""
    if tx_id is None and tx_type in ('deposit', 'withdraw'):
        tx_id = f"{tx_type.upper()}_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    row = execute("""
        INSERT INTO transactions (user_id, type, amount, method, tx_id, status, time)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
    """, (user_id, tx_type, amount, method, tx_id, status), fetch='one')
    return row[0] if row else None


def update_transaction_status(tx_id_or_id, new_status):
    if isinstance(tx_id_or_id, int):
        rows = execute("UPDATE transactions SET status=%s WHERE id=%s", (new_status, tx_id_or_id))
    else:
        rows = execute("UPDATE transactions SET status=%s WHERE tx_id=%s", (new_status, tx_id_or_id))
    return rows > 0


def get_transaction_by_id(tx_id):
    if isinstance(tx_id, int):
        return execute("SELECT * FROM transactions WHERE id=%s", (tx_id,), fetch='one')
    else:
        return execute("SELECT * FROM transactions WHERE tx_id=%s", (tx_id,), fetch='one')


def get_last_5_transactions(user_id):
    return execute("""
        SELECT type, amount, time
        FROM transactions
        WHERE user_id=%s AND status='completed'
        ORDER BY id DESC LIMIT 5
    """, (user_id,), fetch='all')


def get_all_transactions(user_id, limit=20):
    return execute("""
        SELECT type, amount, status, time
        FROM transactions
        WHERE user_id=%s
        ORDER BY id DESC LIMIT %s
    """, (user_id, limit), fetch='all')


def get_total_deposits(user_id):
    row = execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id=%s AND type='deposit' AND status='completed'
    """, (user_id,), fetch='one')
    return row[0] if row and row[0] else 0


def transaction_exists(tx_id):
    if not tx_id:
        return False
    row = execute("SELECT 1 FROM transactions WHERE tx_id=%s", (tx_id,), fetch='one')
    return row is not None


# ==========================================
# DEPOSIT FUNCTIONS (Admin)
# ==========================================

def add_pending_deposit(user_id, amount, method='Telebirr', tx_id=None, phone=None):
    if phone:
        execute("UPDATE users SET phone=%s WHERE user_id=%s AND (phone IS NULL OR phone='')", (phone, user_id))
    return add_transaction(user_id, 'deposit', amount, method, tx_id, status='pending')


def approve_deposit(transaction_id):
    """Approve pending deposit → add to play_balance."""
    row = execute("SELECT user_id, amount, status FROM transactions WHERE id=%s", (transaction_id,), fetch='one')
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    execute("UPDATE transactions SET status='completed' WHERE id=%s", (transaction_id,))
    execute("UPDATE users SET play_balance = play_balance + %s WHERE user_id=%s", (amount, user_id))
    return True, user_id, amount


def reject_deposit(transaction_id):
    """Reject pending deposit."""
    row = execute("SELECT user_id, status FROM transactions WHERE id=%s", (transaction_id,), fetch='one')
    if not row:
        return False, None
    user_id, current_status = row[0], row[1]
    if current_status != 'pending':
        return False, user_id
    execute("UPDATE transactions SET status='rejected' WHERE id=%s", (transaction_id,))
    return True, user_id


def get_all_deposits(limit=200):
    """Get all deposits for admin panel."""
    rows = execute("""
        SELECT t.id, t.user_id, u.first_name, u.phone, t.amount, t.method, t.tx_id, t.status, t.time
        FROM transactions t
        LEFT JOIN users u ON t.user_id = u.user_id
        WHERE t.type='deposit'
        ORDER BY t.id DESC LIMIT %s
    """, (limit,), fetch='all')
    deposits = []
    for r in rows:
        deposits.append({
            'id': r[0], 'user_id': r[1], 'username': r[2] or '—',
            'phone': r[3] or '—', 'amount': r[4], 'method': r[5] or 'Telebirr',
            'tx_id': r[6] or '—', 'status': r[7] or 'pending', 'time': str(r[8]) if r[8] else ''
        })
    return deposits


def get_pending_deposits_count():
    row = execute("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND status='pending'", fetch='one')
    return row[0] if row else 0


# ==========================================
# WITHDRAWAL FUNCTIONS (Admin)
# ==========================================

def add_pending_withdrawal(user_id, amount, method='Telebirr', phone=None):
    main_bal = get_main_balance(user_id)
    if main_bal < amount:
        return None
    update_main_balance(user_id, -amount)
    return add_transaction(user_id, 'withdraw', amount, method, status='pending')


def approve_withdrawal(transaction_id):
    """Mark withdrawal as completed."""
    row = execute("SELECT user_id, amount, status FROM transactions WHERE id=%s", (transaction_id,), fetch='one')
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    execute("UPDATE transactions SET status='completed' WHERE id=%s", (transaction_id,))
    return True, user_id, amount


def reject_withdrawal(transaction_id):
    """Reject withdrawal → refund money."""
    row = execute("SELECT user_id, amount, status FROM transactions WHERE id=%s", (transaction_id,), fetch='one')
    if not row:
        return False, None, 0
    user_id, amount, current_status = row[0], row[1], row[2]
    if current_status != 'pending':
        return False, user_id, amount
    execute("UPDATE transactions SET status='rejected' WHERE id=%s", (transaction_id,))
    execute("UPDATE users SET main_balance = main_balance + %s WHERE user_id=%s", (amount, user_id))
    return True, user_id, amount


def get_all_withdrawals(limit=100):
    """Get all withdrawals with FULL user info for admin panel."""
    rows = execute("""
        SELECT t.id, t.user_id, u.first_name, u.phone,
               u.main_balance, u.play_balance,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id) as games_played,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id AND g.status='Won') as games_won,
               (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as referral_count,
               u.is_agent,
               t.amount, t.method, t.status, t.time
        FROM transactions t
        LEFT JOIN users u ON t.user_id = u.user_id
        WHERE t.type='withdraw'
        ORDER BY t.id DESC LIMIT %s
    """, (limit,), fetch='all')
    withdrawals = []
    for r in rows:
        withdrawals.append({
            'id':             r[0],
            'user_id':        r[1],
            'username':       r[2] or '—',
            'phone':          r[3] or '—',
            'main_balance':   r[4] or 0,
            'play_balance':   r[5] or 0,
            'games_played':   r[6] or 0,
            'games_won':      r[7] or 0,
            'referral_count': r[8] or 0,
            'is_agent':       r[9] or 0,
            'amount':         r[10],
            'method':         r[11] or 'Telebirr',
            'status':         r[12] or 'pending',
            'time':           str(r[13]) if r[13] else ''
        })
    return withdrawals


def get_pending_withdrawals_count():
    row = execute("SELECT COUNT(*) FROM transactions WHERE type='withdraw' AND status='pending'", fetch='one')
    return row[0] if row else 0


# ==========================================
# GAME SESSION FUNCTIONS
# ==========================================

def add_game_session(user_id, game_id, cards, entry_amount=10):
    cards_str = ','.join(str(c) for c in cards) if isinstance(cards, list) else str(cards)
    execute("""
        INSERT INTO game_sessions (user_id, game_id, cards, entry_amount, status, result, time)
        VALUES (%s, %s, %s, %s, 'playing', '-', NOW())
    """, (user_id, game_id, cards_str, entry_amount))


def complete_game_session(user_id, game_id, result='-', prize=0):
    status = 'Won' if prize > 0 else 'Completed'
    result_str = f'+{prize} Br' if prize > 0 else '-'
    execute("""
        UPDATE game_sessions
        SET status=%s, result=%s, prize=%s
        WHERE user_id=%s AND game_id=%s AND status='playing'
    """, (status, result_str, prize, user_id, game_id))


def get_game_history(user_id, limit=20):
    return execute("""
        SELECT game_id, entry_amount, status, result, time
        FROM game_sessions
        WHERE user_id=%s
        ORDER BY id DESC LIMIT %s
    """, (user_id, limit), fetch='all')


def get_games_played_count(user_id):
    row = execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row else 0


def get_games_won_count(user_id):
    row = execute("SELECT COUNT(*) FROM game_sessions WHERE user_id=%s AND status='Won'", (user_id,), fetch='one')
    return row[0] if row else 0


def get_total_won(user_id):
    row = execute("SELECT COALESCE(SUM(prize),0) FROM game_sessions WHERE user_id=%s AND status='Won'", (user_id,), fetch='one')
    return row[0] if row and row[0] else 0


# ==========================================
# PROFILE STATS
# ==========================================

def get_profile_stats(user_id):
    games_played = get_games_played_count(user_id)
    games_won    = get_games_won_count(user_id)
    total_won    = get_total_won(user_id)
    invited      = get_referral_count(user_id)
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
    return execute("""
        SELECT u.user_id, u.first_name, COUNT(t.id) as total
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.type='deposit' AND t.status='completed' AND t.time >= %s
        GROUP BY u.user_id, u.first_name
        ORDER BY total DESC LIMIT %s
    """, (since, limit), fetch='all')


def get_top_by_invitations(period='week', limit=30):
    since = get_period_start(period)
    return execute("""
        SELECT u.user_id, u.first_name, COUNT(inv.user_id) as total
        FROM users u
        JOIN users inv ON inv.referred_by = u.user_id
        WHERE inv.created_at >= %s
        GROUP BY u.user_id, u.first_name
        HAVING COUNT(inv.user_id) > 0
        ORDER BY total DESC LIMIT %s
    """, (since, limit), fetch='all')


def get_top_by_games(period='week', limit=30):
    since = get_period_start(period)
    return execute("""
        SELECT u.user_id, u.first_name, COUNT(g.id) as total
        FROM game_sessions g
        JOIN users u ON g.user_id = u.user_id
        WHERE g.time >= %s
        GROUP BY u.user_id, u.first_name
        ORDER BY total DESC LIMIT %s
    """, (since, limit), fetch='all')


def get_top_by_wins(period='week', limit=30):
    since = get_period_start(period)
    return execute("""
        SELECT u.user_id, u.first_name, COUNT(g.id) as total
        FROM game_sessions g
        JOIN users u ON g.user_id = u.user_id
        WHERE g.status='Won' AND g.time >= %s
        GROUP BY u.user_id, u.first_name
        ORDER BY total DESC LIMIT %s
    """, (since, limit), fetch='all')


def get_user_rank(user_id, period='week', category='deposit'):
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
    """Get all users with full stats for admin panel."""
    rows = execute("""
        SELECT u.user_id, u.first_name, u.phone, u.main_balance, u.play_balance,
               u.is_agent, u.is_vip, u.language, u.status,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id) as games_played,
               (SELECT COUNT(*) FROM game_sessions g WHERE g.user_id=u.user_id AND g.status='Won') as games_won,
               (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as referral_count,
               (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as inv_count,
               (SELECT COUNT(DISTINCT r2.user_id) FROM users r2
                JOIN transactions t2 ON r2.user_id=t2.user_id
                WHERE r2.referred_by=u.user_id AND t2.type='deposit' AND t2.status='completed') as depositing_count,
               (SELECT COALESCE(SUM(t3.amount),0) FROM transactions t3
                JOIN users r3 ON t3.user_id=r3.user_id
                WHERE r3.referred_by=u.user_id AND t3.type='deposit' AND t3.status='completed') as referral_volume
        FROM users u
        ORDER BY u.user_id DESC LIMIT %s
    """, (limit,), fetch='all')
    users = []
    for r in rows:
        users.append({
            'user_id':             r[0],
            'first_name':          r[1] or '—',
            'phone':               r[2] or '—',
            'main_balance':        r[3] or 0,
            'play_balance':        r[4] or 0,
            'is_agent':            r[5] or 0,
            'is_vip':              r[6] or 0,
            'language':            r[7] or 'am',
            'status':              r[8] or 'active',
            'games_played':        r[9] or 0,
            'games_won':           r[10] or 0,
            'referral_count':      r[11] or 0,
            'referral_depositors': r[13] or 0,
            'referral_volume':     r[14] or 0,
        })
    return users


def ban_user(user_id):
    execute("UPDATE users SET status='banned' WHERE user_id=%s", (user_id,))


def unban_user(user_id):
    execute("UPDATE users SET status='active' WHERE user_id=%s", (user_id,))


def mark_vip(user_id, vip=True):
    execute("UPDATE users SET is_vip=%s WHERE user_id=%s", (1 if vip else 0, user_id))


def mark_agent(user_id, is_agent=True):
    execute("UPDATE users SET is_agent=%s WHERE user_id=%s", (1 if is_agent else 0, user_id))


def is_user_banned(user_id):
    row = execute("SELECT status FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row and row[0] == 'banned'


# ==========================================
# AGENT SYSTEM
# ==========================================

def is_user_agent(user_id):
    row = execute("SELECT is_agent FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row and row[0] == 1


def check_and_upgrade_agent(user_id):
    """Check if user qualifies for agent and upgrade if so."""
    if is_user_agent(user_id):
        return False
    invites    = get_referral_count(user_id)
    depositors = get_depositing_referrals_count(user_id)
    total_deps = get_total_referral_deposits(user_id)
    if invites >= 30 and depositors >= 20 and total_deps >= 3000:
        execute("UPDATE users SET is_agent=1 WHERE user_id=%s", (user_id,))
        return True
    return False


def get_agents_with_stats(period='week', limit=100):
    """
    Get all agents with their referral stats and commission earned.
    Used by admin panel Agent section.
    """
    since = get_period_start(period)
    rows = execute("""
        SELECT
            u.user_id,
            u.first_name,
            u.phone,
            u.is_agent,
            (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) as total_invites,
            (SELECT COUNT(DISTINCT r2.user_id)
             FROM users r2
             JOIN transactions t2 ON r2.user_id=t2.user_id
             WHERE r2.referred_by=u.user_id
               AND t2.type='deposit' AND t2.status='completed') as depositing_referrals,
            (SELECT COALESCE(SUM(t3.amount),0)
             FROM transactions t3
             JOIN users r3 ON t3.user_id=r3.user_id
             WHERE r3.referred_by=u.user_id
               AND t3.type='deposit' AND t3.status='completed'
               AND t3.time >= %s) as referral_volume_period,
            (SELECT COALESCE(SUM(t4.amount),0)
             FROM transactions t4
             JOIN users r4 ON t4.user_id=r4.user_id
             WHERE r4.referred_by=u.user_id
               AND t4.type='deposit' AND t4.status='completed') as referral_volume_total
        FROM users u
        WHERE u.is_agent=1 OR (
            (SELECT COUNT(*) FROM users r WHERE r.referred_by=u.user_id) >= 30
            AND
            (SELECT COUNT(DISTINCT r2.user_id)
             FROM users r2 JOIN transactions t2 ON r2.user_id=t2.user_id
             WHERE r2.referred_by=u.user_id AND t2.type='deposit' AND t2.status='completed') >= 20
            AND
            (SELECT COALESCE(SUM(t3.amount),0)
             FROM transactions t3 JOIN users r3 ON t3.user_id=r3.user_id
             WHERE r3.referred_by=u.user_id AND t3.type='deposit' AND t3.status='completed') >= 3000
        )
        ORDER BY referral_volume_period DESC
        LIMIT %s
    """, (since, limit), fetch='all')

    agents = []
    for r in rows:
        vol_period = r[6] or 0
        vol_total  = r[7] or 0
        commission = round(vol_period * 0.10)
        agents.append({
            'user_id':              r[0],
            'first_name':           r[1] or '—',
            'phone':                r[2] or '—',
            'is_agent':             bool(r[3]),
            'referral_count':       r[4] or 0,
            'referral_depositors':  r[5] or 0,
            'referral_volume':      vol_total,
            'referral_volume_period': vol_period,
            'commission_earned':    commission,
            'commission_paid':      False,  # Can add a table for this later
        })
    return agents


# ==========================================
# ADMIN: DASHBOARD STATS
# ==========================================

def get_dashboard_stats():
    today = datetime.utcnow().strftime('%Y-%m-%d')

    row = execute("SELECT COUNT(*) FROM users", fetch='one')
    total_users = row[0] if row else 0

    row = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time::date = %s::date", (today,), fetch='one')
    today_deposits = row[0] if row else 0

    row = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time::date = %s::date", (today,), fetch='one')
    today_withdrawals = row[0] if row else 0

    row = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time::date = %s::date", (today,), fetch='one')
    today_payout = row[0] if row else 0

    row = execute("SELECT COUNT(*) FROM game_sessions WHERE time::date = %s::date", (today,), fetch='one')
    games_today = row[0] if row else 0

    row = execute("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND status='pending'", fetch='one')
    pending_deposits = row[0] if row else 0

    row = execute("SELECT COUNT(*) FROM transactions WHERE type='withdraw' AND status='pending'", fetch='one')
    pending_withdrawals = row[0] if row else 0

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
    rows = execute("""
        SELECT game_id,
               COUNT(DISTINCT user_id) as players,
               SUM(entry_amount) as total_income,
               SUM(prize) as payout,
               MAX(time) as date
        FROM game_sessions
        GROUP BY game_id
        ORDER BY date DESC LIMIT %s
    """, (limit,), fetch='all')
    games = []
    for r in rows:
        pot    = r[2] or 0
        payout = r[3] or 0
        games.append({
            'game_id':      r[0],
            'players':      r[1],
            'total_income': pot,
            'payout':       payout,
            'profit':       pot - payout,
            'date':         str(r[4]) if r[4] else ''
        })
    return games


# ==========================================
# ADMIN: REPORTS
# ==========================================

def get_admin_reports(period='daily'):
    rows = []

    if period == 'daily':
        for i in range(7, -1, -1):
            d = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
            dep = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time::date=%s::date", (d,), fetch='one')[0]
            wit = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time::date=%s::date", (d,), fetch='one')[0]
            pay = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time::date=%s::date", (d,), fetch='one')[0]
            gms = execute("SELECT COUNT(*) FROM game_sessions WHERE time::date=%s::date", (d,), fetch='one')[0]
            rows.append({'date': d, 'deposits': dep, 'withdrawals': wit, 'payout': pay, 'games': gms, 'profit': dep - wit - pay})

    elif period == 'weekly':
        for i in range(3, -1, -1):
            ws = (datetime.utcnow() - timedelta(weeks=i))
            ws = ws - timedelta(days=ws.weekday())
            ws = ws.replace(hour=0, minute=0, second=0, microsecond=0)
            we = ws + timedelta(days=6)
            dep = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND time>=%s AND time<=%s", (ws, we), fetch='one')[0]
            wit = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND time>=%s AND time<=%s", (ws, we), fetch='one')[0]
            pay = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND time>=%s AND time<=%s", (ws, we), fetch='one')[0]
            gms = execute("SELECT COUNT(*) FROM game_sessions WHERE time>=%s AND time<=%s", (ws, we), fetch='one')[0]
            rows.append({'date': f"{ws.strftime('%Y-%m-%d')} to {we.strftime('%Y-%m-%d')}", 'deposits': dep, 'withdrawals': wit, 'payout': pay, 'games': gms, 'profit': dep - wit - pay})

    elif period == 'monthly':
        for i in range(5, -1, -1):
            dt = datetime.utcnow() - timedelta(days=i*30)
            m = dt.strftime('%Y-%m')
            dep = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='completed' AND TO_CHAR(time,'YYYY-MM')=%s", (m,), fetch='one')[0]
            wit = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdraw' AND status='completed' AND TO_CHAR(time,'YYYY-MM')=%s", (m,), fetch='one')[0]
            pay = execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='bingo_win' AND TO_CHAR(time,'YYYY-MM')=%s", (m,), fetch='one')[0]
            gms = execute("SELECT COUNT(*) FROM game_sessions WHERE TO_CHAR(time,'YYYY-MM')=%s", (m,), fetch='one')[0]
            rows.append({'date': m, 'deposits': dep, 'withdrawals': wit, 'payout': pay, 'games': gms, 'profit': dep - wit - pay})

    return rows


# ==========================================
# LANGUAGE FUNCTIONS
# ==========================================

def get_user_language(user_id):
    row = execute("SELECT language FROM users WHERE user_id=%s", (user_id,), fetch='one')
    return row[0] if row and row[0] else 'am'


def set_user_language(user_id, lang):
    execute("UPDATE users SET language=%s WHERE user_id=%s", (lang, user_id))


# ==========================================
# PHONE LOOKUP
# ==========================================

def get_user_by_phone(phone):
    """Find user by phone — handles Ethiopian phone formats."""
    clean = phone.replace(" ","").replace("+","").replace("-","").replace("(","").replace(")","")
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
    placeholders = ",".join(["%s"] * len(variations))
    return execute(f"""
        SELECT user_id, phone, main_balance, play_balance, referred_by
        FROM users WHERE phone IN ({placeholders})
    """, tuple(variations), fetch='one')
