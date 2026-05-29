const mongoose = require('mongoose');

// ══ CONNECT TO MONGODB CLOUD ══
// (Connection is handled in bot.js, but we get the native collections here)

let users_col, transactions_col, game_sessions_col, counters_col, telebirr_transactions_col;

function getCollections() {
    if (!users_col) {
        const db = mongoose.connection.db;
        users_col = db.collection("users");
        transactions_col = db.collection("transactions");
        game_sessions_col = db.collection("game_sessions");
        counters_col = db.collection("counters");
        telebirr_transactions_col = db.collection("telebirr_transactions");
    }
    return { users_col, transactions_col, game_sessions_col, counters_col, telebirr_transactions_col };
}

// ══ HELPER FOR AUTO-INCREMENT IDS ══
async function get_next_id(name) {
    const { counters_col } = getCollections();
    const result = await counters_col.findOneAndUpdate(
        { _id: name },
        { $inc: { seq: 1 } },
        { upsert: true, returnDocument: 'after' }
    );
    return result.seq;
}

function getDateTimeNow() {
    return new Date().toISOString().replace('T', ' ').split('.')[0];
}


// ==========================================
// TELEBIRR TRANSACTION (Used by bot.js)
// ==========================================

async function isTransactionUsed(transaction_id) {
    const { telebirr_transactions_col } = getCollections();
    const doc = await telebirr_transactions_col.findOne({ transaction_id: transaction_id });
    return doc !== null;
}

async function markTransactionUsed(transaction_id, user_id, amount) {
    const { telebirr_transactions_col } = getCollections();
    await telebirr_transactions_col.updateOne(
        { transaction_id: transaction_id },
        { $setOnInsert: { transaction_id: transaction_id, user_id: user_id, amount: amount, created_at: getDateTimeNow() } },
        { upsert: true }
    );
}


// ==========================================
// USER FUNCTIONS
// ==========================================

async function add_user(user_id, phone = '', first_name = '', referred_by = null) {
    const { users_col } = getCollections();
    const now = getDateTimeNow();
    await users_col.updateOne(
        { user_id: user_id },
        { $setOnInsert: { phone: phone, first_name: first_name, referred_by: referred_by, status: "active", created_at: now, main_balance: 0, play_balance: 0, is_agent: 0, is_vip: 0, language: "am" } },
        { upsert: true }
    );
    if (first_name) {
        await users_col.updateOne({ user_id: user_id, $or: [{ first_name: null }, { first_name: "" }] }, { $set: { first_name: first_name } });
    }
}

async function update_user_name(user_id, first_name) {
    const { users_col } = getCollections();
    await users_col.updateOne({ user_id: user_id }, { $set: { first_name: first_name } });
}

async function user_exists(user_id) {
    const { users_col } = getCollections();
    const doc = await users_col.findOne({ user_id: user_id });
    return doc !== null;
}

async function get_user(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    if (!u) return null;
    return [u.user_id, u.phone, u.main_balance || 0, u.play_balance || 0, u.referred_by];
}

async function get_user_full(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    if (!u) return null;
    return {
        user_id: u.user_id,
        first_name: u.first_name || '',
        phone: u.phone || '',
        main_balance: u.main_balance || 0,
        play_balance: u.play_balance || 0,
        referred_by: u.referred_by,
        is_agent: u.is_agent || 0,
        is_vip: u.is_vip || 0,
        language: u.language || 'am',
        status: u.status || 'active',
        created_at: u.created_at || '',
    };
}

async function get_user_name(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.first_name || 'User') : 'User';
}

async function get_user_phone(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u ? u.phone : null;
}


// ==========================================
// BALANCE FUNCTIONS
// ==========================================

async function get_main_balance(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.main_balance || 0) : 0;
}

async function update_main_balance(user_id, amount) {
    const { users_col } = getCollections();
    await users_col.updateOne({ user_id: user_id }, { $inc: { main_balance: amount } });
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.main_balance || 0) : 0;
}

async function get_play_balance(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.play_balance || 0) : 0;
}

async function update_play_balance(user_id, amount) {
    const { users_col } = getCollections();
    await users_col.updateOne({ user_id: user_id }, { $inc: { play_balance: amount } });
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.play_balance || 0) : 0;
}

async function deduct_bet_smart(user_id, amount) {
    const play_bal = await get_play_balance(user_id);
    const main_bal = await get_main_balance(user_id);
    if (play_bal >= amount) {
        await update_play_balance(user_id, -amount);
    } else if (play_bal + main_bal >= amount) {
        const remaining = amount - play_bal;
        await update_play_balance(user_id, -play_bal);
        await update_main_balance(user_id, -remaining);
    } else {
        return false;
    }
    return { main_balance: await get_main_balance(user_id), play_balance: await get_play_balance(user_id) };
}


// ==========================================
// REFERRAL FUNCTIONS
// ==========================================

async function set_referral(user_id, referred_by) {
    const { users_col } = getCollections();
    await users_col.updateOne({ user_id: user_id, referred_by: null }, { $set: { referred_by: referred_by } });
}

async function get_referral_count(user_id) {
    const { users_col } = getCollections();
    return await users_col.countDocuments({ referred_by: user_id });
}

async function get_depositing_referrals_count(user_id) {
    const { users_col, transactions_col } = getCollections();
    const invitedUsers = await users_col.find({ referred_by: user_id }, { projection: { user_id: 1 } }).toArray();
    const invited_ids = invitedUsers.map(u => u.user_id);
    return await transactions_col.countDocuments({ user_id: { $in: invited_ids }, type: "deposit", status: "completed" });
}

async function get_total_referral_deposits(user_id) {
    const { users_col, transactions_col } = getCollections();
    const invitedUsers = await users_col.find({ referred_by: user_id }, { projection: { user_id: 1 } }).toArray();
    const invited_ids = invitedUsers.map(u => u.user_id);
    const pipeline = [
        { $match: { user_id: { $in: invited_ids }, type: "deposit", status: "completed" } },
        { $group: { _id: null, total: { $sum: "$amount" } } }
    ];
    const result = await transactions_col.aggregate(pipeline).toArray();
    return result.length > 0 ? result[0].total : 0;
}


// ==========================================
// TRANSACTION FUNCTIONS
// ==========================================

async function add_transaction(user_id, tx_type, amount, method = "System", tx_id = null, status = 'completed') {
    const { transactions_col } = getCollections();
    if (tx_id === null && (tx_type === 'deposit' || tx_type === 'withdraw')) {
        tx_id = `${tx_type.toUpperCase()}_${user_id}_${Date.now()}`;
    }
    const now = getDateTimeNow();
    const row_id = await get_next_id("transactions");
    await transactions_col.insertOne({
        id: row_id, user_id: user_id, type: tx_type, amount: amount,
        method: method, tx_id: tx_id, status: status, time: now
    });
    return row_id;
}

async function update_transaction_status(tx_id_or_id, new_status) {
    const { transactions_col } = getCollections();
    let result;
    if (typeof tx_id_or_id === 'number') {
        result = await transactions_col.updateOne({ id: tx_id_or_id }, { $set: { status: new_status } });
    } else {
        result = await transactions_col.updateOne({ tx_id: tx_id_or_id }, { $set: { status: new_status } });
    }
    return result.modifiedCount > 0;
}

async function get_transaction_by_id(tx_id) {
    const { transactions_col } = getCollections();
    if (typeof tx_id === 'number') {
        return await transactions_col.findOne({ id: tx_id });
    } else {
        return await transactions_col.findOne({ tx_id: tx_id });
    }
}

async function get_last_5_transactions(user_id) {
    const { transactions_col } = getCollections();
    const txs = await transactions_col.find({ user_id: user_id, status: "completed" }).sort({ id: -1 }).limit(5).toArray();
    return txs.map(t => [t.type, t.amount, t.time]);
}

async function get_all_transactions(user_id, limit = 20) {
    const { transactions_col } = getCollections();
    const txs = await transactions_col.find({ user_id: user_id }).sort({ id: -1 }).limit(limit).toArray();
    return txs.map(t => [t.type, t.amount, t.status, t.time]);
}

async function get_total_deposits(user_id) {
    const { transactions_col } = getCollections();
    const pipeline = [
        { $match: { user_id: user_id, type: "deposit", status: "completed" } },
        { $group: { _id: null, total: { $sum: "$amount" } } }
    ];
    const result = await transactions_col.aggregate(pipeline).toArray();
    return result.length > 0 ? result[0].total : 0;
}

async function transaction_exists(tx_id) {
    const { transactions_col } = getCollections();
    if (!tx_id) return false;
    const doc = await transactions_col.findOne({ tx_id: tx_id });
    return doc !== null;
}


// ==========================================
// DEPOSIT FUNCTIONS (Admin)
// ==========================================

async function add_pending_deposit(user_id, amount, method = 'Telebirr', tx_id = null, phone = null) {
    const { users_col } = getCollections();
    if (phone) {
        await users_col.updateOne({ user_id: user_id, $or: [{ phone: null }, { phone: "" }] }, { $set: { phone: phone } });
    }
    return await add_transaction(user_id, 'deposit', amount, method, tx_id, 'pending');
}

async function approve_deposit(transaction_id) {
    const { transactions_col, users_col } = getCollections();
    const t = await transactions_col.findOne({ id: transaction_id });
    if (!t) return [false, null, 0];
    if (t.status !== 'pending') return [false, t.user_id, t.amount];
    await transactions_col.updateOne({ id: transaction_id }, { $set: { status: "completed" } });
    await users_col.updateOne({ user_id: t.user_id }, { $inc: { play_balance: t.amount } });
    return [true, t.user_id, t.amount];
}

async function reject_deposit(transaction_id) {
    const { transactions_col } = getCollections();
    const t = await transactions_col.findOne({ id: transaction_id });
    if (!t) return [false, null];
    if (t.status !== 'pending') return [false, t.user_id];
    await transactions_col.updateOne({ id: transaction_id }, { $set: { status: "rejected" } });
    return [true, t.user_id];
}

async function get_all_deposits(limit = 200) {
    const { transactions_col } = getCollections();
    const pipeline = [
        { $match: { type: "deposit" } },
        { $sort: { id: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "user_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: { path: "$user_info", preserveNullAndEmptyArrays: true } }
    ];
    const results = await transactions_col.aggregate(pipeline).toArray();
    const deposits = results.map(t => {
        const u = t.user_info || {};
        return {
            id: t.id, user_id: t.user_id, username: u.first_name || '—',
            phone: u.phone || '—', amount: t.amount, method: t.method || 'Telebirr',
            tx_id: t.tx_id || '—', status: t.status || 'pending', time: t.time || ''
        };
    });
    return deposits;
}

async function get_pending_deposits_count() {
    const { transactions_col } = getCollections();
    return await transactions_col.countDocuments({ type: "deposit", status: "pending" });
}


// ==========================================
// WITHDRAWAL FUNCTIONS (Admin)
// ==========================================

async function add_pending_withdrawal(user_id, amount, method = 'Telebirr', phone = null) {
    const main_bal = await get_main_balance(user_id);
    if (main_bal < amount) return null;
    await update_main_balance(user_id, -amount);
    return await add_transaction(user_id, 'withdraw', amount, method, null, 'pending');
}

async function approve_withdrawal(transaction_id) {
    const { transactions_col } = getCollections();
    const t = await transactions_col.findOne({ id: transaction_id });
    if (!t) return [false, null, 0];
    if (t.status !== 'pending') return [false, t.user_id, t.amount];
    await transactions_col.updateOne({ id: transaction_id }, { $set: { status: "completed" } });
    return [true, t.user_id, t.amount];
}

async function reject_withdrawal(transaction_id) {
    const { transactions_col, users_col } = getCollections();
    const t = await transactions_col.findOne({ id: transaction_id });
    if (!t) return [false, null, 0];
    if (t.status !== 'pending') return [false, t.user_id, t.amount];
    await transactions_col.updateOne({ id: transaction_id }, { $set: { status: "rejected" } });
    await users_col.updateOne({ user_id: t.user_id }, { $inc: { main_balance: t.amount } });
    return [true, t.user_id, t.amount];
}

async function get_all_withdrawals(limit = 100) {
    const { transactions_col } = getCollections();
    const pipeline = [
        { $match: { type: "withdraw" } },
        { $sort: { id: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "user_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: { path: "$user_info", preserveNullAndEmptyArrays: true } }
    ];
    const results = await transactions_col.aggregate(pipeline).toArray();
    const withdrawals = results.map(t => {
        const u = t.user_info || {};
        return {
            id: t.id, user_id: t.user_id, username: u.first_name || '—',
            phone: u.phone || '—', amount: t.amount, method: t.method || 'Telebirr',
            status: t.status || 'pending', time: t.time || ''
        };
    });
    return withdrawals;
}

async function get_pending_withdrawals_count() {
    const { transactions_col } = getCollections();
    return await transactions_col.countDocuments({ type: "withdraw", status: "pending" });
}


// ==========================================
// GAME SESSION FUNCTIONS
// ==========================================

async function add_game_session(user_id, game_id, cards, entry_amount = 10) {
    const { game_sessions_col } = getCollections();
    const now = getDateTimeNow();
    if (Array.isArray(cards) && cards.length > 0) {
        for (const card of cards) {
            await game_sessions_col.insertOne({
                user_id: user_id, game_id: game_id, cards: String(card),
                entry_amount: entry_amount, status: "playing", result: "-",
                prize: 0, time: now
            });
        }
    } else {
        await game_sessions_col.insertOne({
            user_id: user_id, game_id: game_id, cards: String(cards),
            entry_amount: entry_amount, status: "playing", result: "-",
            prize: 0, time: now
        });
    }
}

async function complete_game_session(user_id, game_id, result = '-', prize = 0) {
    const { game_sessions_col } = getCollections();
    const status = prize > 0 ? 'Won' : 'Completed';
    const result_str = prize > 0 ? `+${prize} Br` : '-';
    await game_sessions_col.updateMany(
        { user_id: user_id, game_id: game_id, status: "playing" },
        { $set: { status: status, result: result_str } }
    );
    await game_sessions_col.updateOne(
        { user_id: user_id, game_id: game_id, status: status },
        { $set: { prize: prize } }
    );
}

async function get_game_history(user_id, limit = 20) {
    const { game_sessions_col } = getCollections();
    const sessions = await game_sessions_col.find({ user_id: user_id }).sort({ time: -1 }).limit(limit).toArray();
    return sessions.map(s => [s.game_id, s.entry_amount, s.status, s.result, s.time]);
}

async function get_games_played_count(user_id) {
    const { game_sessions_col } = getCollections();
    return await game_sessions_col.countDocuments({ user_id: user_id });
}

async function get_games_won_count(user_id) {
    const { game_sessions_col } = getCollections();
    return await game_sessions_col.countDocuments({ user_id: user_id, status: "Won" });
}

async function get_total_won(user_id) {
    const { game_sessions_col } = getCollections();
    const pipeline = [
        { $match: { user_id: user_id, status: "Won" } },
        { $group: { _id: null, total: { $sum: "$prize" } } }
    ];
    const result = await game_sessions_col.aggregate(pipeline).toArray();
    return result.length > 0 ? result[0].total : 0;
}


// ==========================================
// PROFILE STATS
// ==========================================

async function get_profile_stats(user_id) {
    return {
        games_played: await get_games_played_count(user_id),
        games_won: await get_games_won_count(user_id),
        total_won: await get_total_won(user_id),
        invited: await get_referral_count(user_id),
    };
}


// ==========================================
// LEADERBOARD FUNCTIONS
// ==========================================

function get_period_start(period) {
    const now = new Date();
    let start;
    if (period === 'week') {
        const day = now.getDay(); // Sunday is 0, Monday is 1
        const diff = now.getDate() - day + (day === 0 ? -6 : 1); // adjust to Monday
        start = new Date(now.setDate(diff));
        start.setHours(0, 0, 0, 0);
    } else if (period === 'month') {
        start = new Date(now.getFullYear(), now.getMonth(), 1);
    } else {
        start = new Date();
        start.setDate(start.getDate() - 7);
    }
    return start.toISOString().replace('T', ' ').split('.')[0];
}

async function get_top_by_deposit(period = 'week', limit = 30) {
    const { transactions_col } = getCollections();
    const since = get_period_start(period);
    const pipeline = [
        { $match: { type: "deposit", status: "completed", time: { $gte: since } } },
        { $group: { _id: "$user_id", total: { $sum: 1 } } },
        { $sort: { total: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: "$user_info" }
    ];
    const results = await transactions_col.aggregate(pipeline).toArray();
    return results.map(r => [r._id, r.user_info.first_name || "User", r.total]);
}

async function get_top_by_invitations(period = 'week', limit = 30) {
    const { users_col } = getCollections();
    const since = get_period_start(period);
    const pipeline = [
        { $match: { created_at: { $gte: since } } },
        { $group: { _id: "$referred_by", total: { $sum: 1 } } },
        { $match: { _id: { $ne: null }, total: { $gt: 0 } } },
        { $sort: { total: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: "$user_info" }
    ];
    const results = await users_col.aggregate(pipeline).toArray();
    return results.map(r => [r._id, r.user_info.first_name || "User", r.total]);
}

async function get_top_by_games(period = 'week', limit = 30) {
    const { game_sessions_col } = getCollections();
    const since = get_period_start(period);
    const pipeline = [
        { $match: { time: { $gte: since } } },
        { $group: { _id: "$user_id", total: { $sum: 1 } } },
        { $sort: { total: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: "$user_info" }
    ];
    const results = await game_sessions_col.aggregate(pipeline).toArray();
    return results.map(r => [r._id, r.user_info.first_name || "User", r.total]);
}

async function get_top_by_wins(period = 'week', limit = 30) {
    const { game_sessions_col } = getCollections();
    const since = get_period_start(period);
    const pipeline = [
        { $match: { status: "Won", time: { $gte: since } } },
        { $group: { _id: "$user_id", total: { $sum: 1 } } },
        { $sort: { total: -1 } },
        { $limit: limit },
        { $lookup: { from: "users", localField: "_id", foreignField: "user_id", as: "user_info" } },
        { $unwind: "$user_info" }
    ];
    const results = await game_sessions_col.aggregate(pipeline).toArray();
    return results.map(r => [r._id, r.user_info.first_name || "User", r.total]);
}

async function get_user_rank(user_id, period = 'week', category = 'deposit') {
    let rows;
    if (category === 'deposit') rows = await get_top_by_deposit(period, 1000);
    else if (category === 'invite') rows = await get_top_by_invitations(period, 1000);
    else if (category === 'wins') rows = await get_top_by_wins(period, 1000);
    else rows = await get_top_by_games(period, 1000);
    
    for (let i = 0; i < rows.length; i++) {
        if (rows[i][0] === user_id) return [i + 1, rows[i][2]];
    }
    return [null, 0];
}


// ==========================================
// ADMIN: USER MANAGEMENT
// ==========================================

async function get_all_users_with_stats(limit = 500) {
    const { users_col, game_sessions_col } = getCollections();
    const users = await users_col.find().sort({ user_id: -1 }).limit(limit).toArray();
    const result = [];
    for (const u of users) {
        result.push({
            user_id: u.user_id,
            first_name: u.first_name || '—',
            phone: u.phone || '—',
            main_balance: u.main_balance || 0,
            play_balance: u.play_balance || 0,
            is_agent: u.is_agent || 0,
            is_vip: u.is_vip || 0,
            language: u.language || 'am',
            status: u.status || 'active',
            games_played: await game_sessions_col.countDocuments({ user_id: u.user_id }),
            games_won: await game_sessions_col.countDocuments({ user_id: u.user_id, status: "Won" }),
            referral_count: await users_col.countDocuments({ referred_by: u.user_id }),
        });
    }
    return result;
}

async function ban_user(user_id) {
    const { users_col } = getCollections();
    const result = await users_col.updateOne({ user_id: user_id }, { $set: { status: "banned" } });
    return result.modifiedCount > 0;
}

async function unban_user(user_id) {
    const { users_col } = getCollections();
    const result = await users_col.updateOne({ user_id: user_id }, { $set: { status: "active" } });
    return result.modifiedCount > 0;
}

async function mark_vip(user_id, vip = true) {
    const { users_col } = getCollections();
    const result = await users_col.updateOne({ user_id: user_id }, { $set: { is_vip: vip ? 1 : 0 } });
    return result.modifiedCount > 0;
}

async function is_user_banned(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u && u.status === "banned";
}

async function freeze_user(user_id) {
    const { users_col } = getCollections();
    const result = await users_col.updateOne({ user_id: user_id }, { $set: { status: "frozen" } });
    return result.modifiedCount > 0;
}

async function unfreeze_user(user_id) {
    const { users_col } = getCollections();
    const result = await users_col.updateOne({ user_id: user_id }, { $set: { status: "active" } });
    return result.modifiedCount > 0;
}


// ==========================================
// ADMIN: DASHBOARD STATS
// ==========================================

async function get_dashboard_stats() {
    const { users_col, transactions_col, game_sessions_col } = getCollections();
    const today = new Date().toISOString().replace('T', ' ').split(' ')[0];
    const total_users = await users_col.countDocuments({});
    
    async function sum_transactions(tx_type, status = 'completed', date_prefix = null) {
        const match = { type: tx_type, status: status };
        if (date_prefix) match.time = { $regex: `^${date_prefix}` };
        const pipeline = [{ $match: match }, { $group: { _id: null, total: { $sum: "$amount" } } }];
        const res = await transactions_col.aggregate(pipeline).toArray();
        return res.length > 0 ? res[0].total : 0;
    }

    const today_deposits = await sum_transactions('deposit', 'completed', today);
    const today_withdrawals = await sum_transactions('withdraw', 'completed', today);
    const today_payout = await sum_transactions('bingo_win', 'completed', today);
    const games_today = await game_sessions_col.countDocuments({ time: { $regex: `^${today}` } });

    return {
        total_users: total_users,
        today_deposits: today_deposits,
        today_withdrawals: today_withdrawals,
        today_profit: today_deposits - today_payout,
        today_payout: today_payout,
        games_today: games_today,
        pending_deposits: await transactions_col.countDocuments({ type: "deposit", status: "pending" }),
        pending_withdrawals: await transactions_col.countDocuments({ type: "withdraw", status: "pending" }),
    };
}


// ==========================================
// ADMIN: GAME HISTORY
// ==========================================

async function get_admin_game_history(limit = 100) {
    const { game_sessions_col } = getCollections();
    const pipeline = [
        { $group: {
            _id: "$game_id",
            total_cards: { $sum: 1 },
            total_income: { $sum: "$entry_amount" },
            payout: { $sum: "$prize" },
            winners: { $sum: { $cond: [{ $eq: ["$status", "Won"] }, 1, 0] } },
            date: { $max: "$time" }
        }},
        { $sort: { date: -1 } },
        { $limit: limit }
    ];
    const results = await game_sessions_col.aggregate(pipeline).toArray();
    const games = results.map(r => {
        const cards = r.total_cards || 0;
        const pot = r.total_income || 0;
        const payout = r.payout || 0;
        const winners = r.winners || 0;
        const bet = cards > 0 ? Math.round(pot / cards) : 10;
        const total_payout = winners > 0 ? payout * winners : payout;
        return {
            game_id: r._id, players: cards, bet: bet, winners: winners,
            total_income: pot, payout: total_payout, profit: pot - total_payout, date: r.date || ''
        };
    });
    return games;
}


// ==========================================
// ADMIN: REPORTS
// ==========================================

async function get_admin_reports(period = 'daily') {
    const { transactions_col, game_sessions_col } = getCollections();
    const rows = [];
    
    async function get_stats_for_date(d_start, d_end = null) {
        let match_time;
        if (d_end) {
            match_time = { $gte: d_start, $lt: d_end };
        } else {
            match_time = { $regex: `^${d_start}` };
        }
        
        const match_dep = { type: "deposit", status: "completed", time: match_time };
        const match_wit = { type: "withdraw", status: "completed", time: match_time };
        const match_win = { type: "bingo_win", status: "completed", time: match_time };
        
        async function get_sum(match) {
            const p = [{ $match: match }, { $group: { _id: null, t: { $sum: "$amount" } } }];
            const res = await transactions_col.aggregate(p).toArray();
            return res.length > 0 ? res[0].t : 0;
        }

        const dep = await get_sum(match_dep);
        const wit = await get_sum(match_wit);
        const pay = await get_sum(match_win);
        const games = await game_sessions_col.countDocuments({ time: match_time });
        return { dep, wit, pay, games };
    }

    if (period === 'daily') {
        for (let i = 7; i >= 0; i--) {
            const d = new Date();
            d.setDate(d.getDate() - i);
            const dateStr = d.toISOString().replace('T', ' ').split(' ')[0];
            const stats = await get_stats_for_date(dateStr);
            rows.push({ date: dateStr, deposits: stats.dep, withdrawals: stats.wit, payout: stats.pay, games: stats.games, profit: stats.dep - stats.wit - stats.pay });
        }
    } else if (period === 'weekly') {
        for (let i = 3; i >= 0; i--) {
            const ws = new Date();
            ws.setDate(ws.getDate() - (i * 7));
            ws.setDate(ws.getDate() - ws.getDay() + 1); // Monday
            ws.setHours(0, 0, 0, 0);
            const we = new Date(ws);
            we.setDate(we.getDate() + 7);
            
            const d_start = ws.toISOString().replace('T', ' ').split(' ')[0];
            const d_end = we.toISOString().replace('T', ' ').split(' ')[0];
            const stats = await get_stats_for_date(d_start, d_end);
            rows.push({ date: `${d_start} to ${d_end}`, deposits: stats.dep, withdrawals: stats.wit, payout: stats.pay, games: stats.games, profit: stats.dep - stats.wit - stats.pay });
        }
    } else if (period === 'monthly') {
        for (let i = 5; i >= 0; i--) {
            const dt = new Date();
            dt.setMonth(dt.getMonth() - i);
            const m = dt.toISOString().slice(0, 7); // YYYY-MM
            const stats = await get_stats_for_date(m);
            rows.push({ date: m, deposits: stats.dep, withdrawals: stats.wit, payout: stats.pay, games: stats.games, profit: stats.dep - stats.wit - stats.pay });
        }
    }
    return rows;
}


// ==========================================
// AGENT SYSTEM FUNCTIONS
// ==========================================

async function is_user_agent(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u && u.is_agent === 1;
}

async function check_and_upgrade_agent(user_id) {
    if (await is_user_agent(user_id)) return false;
    const invites = await get_referral_count(user_id);
    const depositors = await get_depositing_referrals_count(user_id);
    const total_deps = await get_total_referral_deposits(user_id);
    if (invites >= 30 && depositors >= 20 && total_deps >= 3000) {
        const { users_col } = getCollections();
        await users_col.updateOne({ user_id: user_id }, { $set: { is_agent: 1 } });
        return true;
    }
    return false;
}


// ==========================================
// LANGUAGE FUNCTIONS
// ==========================================

async function get_user_language(user_id) {
    const { users_col } = getCollections();
    const u = await users_col.findOne({ user_id: user_id });
    return u ? (u.language || 'am') : 'am';
}

async function set_user_language(user_id, lang) {
    const { users_col } = getCollections();
    await users_col.updateOne({ user_id: user_id }, { $set: { language: lang } });
}


// ==========================================
// PHONE LOOKUP
// ==========================================

async function get_user_by_phone(phone) {
    const { users_col } = getCollections();
    const clean = phone.replace(/ /g, "").replace(/\+/g, "").replace(/-/g, "").replace(/\(/g, "").replace(/\)/g, "");
    const variations = [clean];
    if (clean.startsWith("251")) {
        variations.push("0" + clean.slice(3));
        variations.push("+251" + clean.slice(3));
    } else if (clean.startsWith("0")) {
        variations.push("251" + clean.slice(1));
        variations.push("+251" + clean.slice(1));
    } else if (clean.length === 9 && !clean.startsWith("0")) {
        variations.push("0" + clean);
        variations.push("251" + clean);
        variations.push("+251" + clean);
    }
    const unique_variations = [...new Set(variations)];
    
    const u = await users_col.findOne({ phone: { $in: unique_variations } });
    if (!u) return null;
    return [u.user_id, u.phone, u.main_balance || 0, u.play_balance || 0, u.referred_by];
}


// Export all functions
module.exports = {
    get_next_id,
    isTransactionUsed,
    markTransactionUsed,
    add_user,
    update_user_name,
    user_exists,
    get_user,
    get_user_full,
    get_user_name,
    get_user_phone,
    get_main_balance,
    update_main_balance,
    get_play_balance,
    update_play_balance,
    deduct_bet_smart,
    set_referral,
    get_referral_count,
    get_depositing_referrals_count,
    get_total_referral_deposits,
    add_transaction,
    update_transaction_status,
    get_transaction_by_id,
    get_last_5_transactions,
    get_all_transactions,
    get_total_deposits,
    transaction_exists,
    add_pending_deposit,
    approve_deposit,
    reject_deposit,
    get_all_deposits,
    get_pending_deposits_count,
    add_pending_withdrawal,
    approve_withdrawal,
    reject_withdrawal,
    get_all_withdrawals,
    get_pending_withdrawals_count,
    add_game_session,
    complete_game_session,
    get_game_history,
    get_games_played_count,
    get_games_won_count,
    get_total_won,
    get_profile_stats,
    get_top_by_deposit,
    get_top_by_invitations,
    get_top_by_games,
    get_top_by_wins,
    get_user_rank,
    get_all_users_with_stats,
    ban_user,
    unban_user,
    mark_vip,
    is_user_banned,
    freeze_user,
    unfreeze_user,
    get_dashboard_stats,
    get_admin_game_history,
    get_admin_reports,
    is_user_agent,
    check_and_upgrade_agent,
    get_user_language,
    set_user_language,
    get_user_by_phone
};
