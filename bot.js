const { Telegraf, Markup, session } = require('telegraf');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const mongoose = require('mongoose');
const db = require('./db');

// --------------------------
// CONFIG
// --------------------------
const TOKEN = "8607291518:AAG1IFDDL4CrB8puYNkG8ZWbOTxOl8uK6xo";
const BOT_USERNAME = "adwabingiobot";
const ADMIN_IDS = [7627811244, 1119881250];
const MINI_APP_URL = "https://sebez733-png.github.io/bingio-mini-app/";

const ADMIN_CREDENTIALS = {
    'superadmin': { password: 'admin123', role: 'super' },
    'admin1': { password: 'pass123', role: 'regular' },
};

// --------------------------
// TELEBIRR SMS VERIFICATION
// --------------------------
const MERCHANT_PHONE = "0998480054";

function getMerchantPhonePartials() {
    const p = MERCHANT_PHONE;
    const local_partial = p.slice(0, 4) + "****" + p.slice(-2);
    const intl = "251" + p.slice(1);
    const intl_partial = intl.slice(0, 4) + "****" + intl.slice(-4);
    return [local_partial, intl_partial];
}

async function _isTransactionUsed(transaction_id) {
    return await db.isTransactionUsed(transaction_id);
}

async function _markTransactionUsed(transaction_id, user_id, amount) {
    await db.markTransactionUsed(transaction_id, user_id, amount);
}

function verifyTelebirrSms(sms_text, expected_amount) {
    sms_text = sms_text.trim();
    if (!sms_text.includes("transferred ETB")) {
        return {
            valid: false,
            reason: "❌ SMS format not recognized.\n\nPlease paste the *exact* SMS you received from Telebirr after sending money.\n\nExample:\n_Dear Habtamu You have transferred ETB 100.00 to ..._"
        };
    }
    const amount_match = sms_text.match(/transferred ETB\s*([\d,]+\.?\d*)/);
    if (!amount_match) {
        return { valid: false, reason: "❌ Could not read amount from SMS. Please paste the full SMS." };
    }
    const amount = parseFloat(amount_match[1].replace(',', ''));
    const txn_match = sms_text.match(/transaction number is\s*([A-Z0-9]+)/);
    if (!txn_match) {
        return { valid: false, reason: "❌ Could not find transaction number in SMS. Please paste the full SMS." };
    }
    const transaction_id = txn_match[1].trim();
    const phone_match = sms_text.match(/\((\d{4}\*+\d{2,4})\)/);
    if (phone_match) {
        const receiver_partial = phone_match[1];
        const allowed_partials = getMerchantPhonePartials();
        if (!allowed_partials.includes(receiver_partial)) {
            return {
                valid: false,
                reason: `❌ Wrong recipient!\n\nMoney was not sent to our account.\nPlease send to: \`${MERCHANT_PHONE}\``
            };
        }
    }
    const date_match = sms_text.match(/on\s*(\d{2}\/\d{2}\/\d{4})\s*(\d{2}:\d{2}:\d{2})/);
    const date_str = date_match ? date_match[1] : '';
    const time_str = date_match ? date_match[2] : '';
    if (Math.abs(amount - expected_amount) > 1) {
        return {
            valid: false,
            reason: `❌ Amount mismatch!\n\nYou said you'd send *${expected_amount} ETB* but SMS shows *${amount.toFixed(2)} ETB*.\n\nPlease make sure you send the exact amount.`
        };
    }
    return {
        valid: true,
        reason: 'OK',
        transaction_id: transaction_id,
        amount: amount,
        date: date_str,
        time: time_str,
    };
}

// --------------------------
// STATE & COUNTERS
// --------------------------
let user_state = {};
let request_counter = 0;
let withdraw_requests = {};

// --------------------------
// SHARED GAME STATE (MULTI-ROOM)
// --------------------------
function default_game_state() {
    return {
        running: false,
        game_id: null,
        called: [],
        started_at: null,
        time_left: 35,
        timer_started_at: null,
        total_players: 0,
        total_pot: 0,
        ready_players: {},
        winner_declared: false,
        max_winners: 1,
        winner_count: 0,
        paused: false,
        current: null
    };
}

function get_game_state(room) {
    if (!game_states[room]) {
        game_states[room] = default_game_state();
    }
    return game_states[room];
}

let game_states = {
    '10': default_game_state(),
    '20': default_game_state()
};

function count_total_cards(game) {
    return Object.values(game.ready_players || {}).reduce((sum, p) => sum + (p.cards || []).length, 0);
}

// --------------------------
// TRANSLATION DICTIONARY
// --------------------------
const TEXTS = {
    'select_language': {
        'am': "👇 ቋንቋ ይምረጡ / Please select your language",
        'en': "👇 Please select your language"
    },
    'welcome_new': {
        'am': "🎉 እንኳን ወደ አድዋ Bingo በደህና መጡ!\n\n1️⃣ ከታች ያለውን \"📱 ስልክ ቁጥር ያጋሩ\" ይጫኑ\n2️⃣ ስልክ ቁጥርዎን ያረጋግጡ\n3️⃣ ከዚያ በኋላ መጫወት ይጀምሩ! 🚀\n\n👇 ለመጀመር ስልክ ቁጥርዎን ያጋሩ",
        'en': "🎉 Welcome to our Adwa Bingo Game!\n\n1️⃣ Click the button below to share your phone number\n2️⃣ Verify your number\n3️⃣ Start playing! 🚀\n\n👇 Share your phone number to begin:"
    },
    'share_phone_btn': {
        'am': "📱 ስልክ ቁጥር ያጋሩ",
        'en': "📱 Share Phone Number"
    },
    'welcome_back': {
        'am': "👋 Welcome back!",
        'en': "👋 Welcome back!"
    },
    'already_registered': {
        'am': "⚠️ እርስዎ ቀድሞ ተመዝግበዋል!\n\n📱 ስልክ: {phone}\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB\n👥 Referrals: {ref_count}\n\n👇 Choose an option below:",
        'en': "⚠️ You are already registered!\n\n📱 Phone: {phone}\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB\n👥 Referrals: {ref_count}\n\n👇 Choose an option below:"
    },
    'register_success': {
        'am': "🎉 እንኳን ወደ አድዋ Bingo ቤተሰብ በደህና መጡ!\n\n✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል!\n\n📱 ስልክ ቁጥር: {phone}\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB\n\n🎯 አሁን መጫወት ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ!\n🍀 መልካም እድል!",
        'en': "🎉 Welcome to the Adwa Bingo Family!\n\n✅ Registration successful!\n\n📱 Phone: {phone}\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB\n\n🎯 Click the menu below to start playing!\n🍀 Good luck!"
    },
    'deposit_prompt': {
        'am': "💳 ምን ያህል ማስገባት ይፈልጋሉ?\n(Enter amount)\n\nMin / ዝቅተኛ: 10 ብር / Birr",
        'en': "💳 How much would you like to deposit?\n(Enter amount)\n\nMin: 10 Birr"
    },
    'withdraw_prompt': {
        'am': "🐝 ማውጣት የሚፈልጉትን መጠን ይፃፉ (ETB):\n\n🎮 Play Wallet: {play_bal} ETB\n💰 Main Wallet: {main_bal} ETB\n\nMin / ዝቅተኛ: 100 ብር",
        'en': "🐝 Enter withdrawal amount (ETB):\n\n🎮 Play Wallet: {play_bal} ETB\n💰 Main Wallet: {main_bal} ETB\n\nMin: 100 Birr"
    },
    'withdraw_locked': {
        'am': "❌ ማውጣት አይችሉም!\n\n⚠️ ገንዘብ ለማውጣት 50 ብር ማስገባት አለብዎት።\n\n❌ You cannot withdraw. You must deposit at least 50 ETB in total to unlock withdrawals.",
        'en': "❌ Withdrawal locked!\n\n⚠️ You must deposit at least 50 ETB in total to unlock withdrawals."
    },
    'balance_msg': {
        'am': "💰 WALLET BALANCE\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB",
        'en': "💰 WALLET BALANCE\n\n💰 Main Wallet: {main} ETB\n🎮 Play Wallet: {play} ETB"
    },
    'deposit_success': {
        'am': "✅ Deposit Successful\n\n💰 Method: {method}\n💰 Sent: {amount}\n🎁 Bonus: {bonus}\n📈 Total Added: {total}\n💰 New Balance: {new_balance} ETB",
        'en': "✅ Deposit Successful\n\n💰 Method: {method}\n💰 Sent: {amount}\n🎁 Bonus: {bonus}\n📈 Total Added: {total}\n💰 New Balance: {new_balance} ETB"
    },
    'lang_changed': {
        'am': "✅ ቋንቋ ወደ አማርኛ ተቀይሯል!",
        'en': "✅ Language changed to English!"
    }
};

function t(key, lang = 'am', kwargs = {}) {
    let text = TEXTS[key] ? (TEXTS[key][lang] || TEXTS[key]['am'] || key) : key;
    for (const [k, v] of Object.entries(kwargs)) {
        text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
    return text;
}

// --------------------------
// HELPER: Normalize Phone
// --------------------------
function normalizePhone(phone) {
    phone = phone.replace(/ /g, "").replace(/\+/g, "").replace(/-/g, "").replace(/\(/g, "").replace(/\)/g, "");
    if (phone.startsWith("251")) {
        phone = "0" + phone.slice(3);
    }
    if (!phone.startsWith("0") && phone.length === 9) {
        phone = "0" + phone;
    }
    return phone;
}

// --------------------------
// HELPER: Get Main Menu
// --------------------------
function getMainMenu(lang = 'am') {
    if (lang === 'en') {
        return Markup.keyboard([
            ["🎮 Open Game"],
            ["💳 Deposit", "💰 Balance"],
            ["🐝 Withdraw", "📜 History"],
            ["👤 Profile", "🏢 Support"],
            ["🎁 Invite Friends", "🤖 Agent Panel"],
            ["🔄 Transfer", "ℹ️ Info"]
        ]).resize();
    } else {
        return Markup.keyboard([
            ["🎮 Open Game / ይጫወቱ"],
            ["💳 Deposit / ያስገቡ", "💰 Balance / ሂሳብ"],
            ["🐝 Withdraw / ያውጡ", "📜 History / ታሪክ"],
            ["👤 Profile / መገለጫ", "🏢 Support / ድጋፍ"],
            ["🎁 Invite Friends / ጓደኛ ይጋብዙ", "🤖 Agent Panel"],
            ["🔄 Transfer / ይላኩ", "ℹ️ Info / መረጃ"]
        ]).resize();
    }
}

// --------------------------
// HELPER: Get Inline Menu
// --------------------------
function getInlineMenu(lang = 'am') {
    if (lang === 'en') {
        return Markup.inlineKeyboard([
            [Markup.button.webApp("🎮 Open Game", MINI_APP_URL)],
            [
                Markup.button.callback("💳 Deposit", "menu_deposit"),
                Markup.button.callback("💰 Balance", "menu_balance")
            ],
            [
                Markup.button.callback("🐝 Withdraw", "menu_withdraw"),
                Markup.button.callback("📜 History", "menu_history")
            ],
            [
                Markup.button.callback("👤 Profile", "menu_profile"),
                Markup.button.callback("🏢 Support", "menu_support")
            ],
            [
                Markup.button.callback("🎁 Invite Friends", "menu_invite"),
                Markup.button.callback("🤖 Agent Panel", "menu_agent")
            ],
            [
                Markup.button.callback("🔄 Transfer", "menu_transfer"),
                Markup.button.callback("ℹ️ Info", "menu_info")
            ]
        ]);
    } else {
        return Markup.inlineKeyboard([
            [Markup.button.webApp("🎮 Open Game / ይጫወቱ", MINI_APP_URL)],
            [
                Markup.button.callback("💳 Deposit / ያስገቡ", "menu_deposit"),
                Markup.button.callback("💰 Balance / ሂሳብ", "menu_balance")
            ],
            [
                Markup.button.callback("🐝 Withdraw / ያውጡ", "menu_withdraw"),
                Markup.button.callback("📜 History / ታሪክ", "menu_history")
            ],
            [
                Markup.button.callback("👤 Profile / መገለጫ", "menu_profile"),
                Markup.button.callback("🏢 Support / ድጋፍ", "menu_support")
            ],
            [
                Markup.button.callback("🎁 Invite Friends / ጓደኛ ይጋብዙ", "menu_invite"),
                Markup.button.callback("🤖 Agent Panel", "menu_agent")
            ],
            [
                Markup.button.callback("🔄 Transfer / ይላኩ", "menu_transfer"),
                Markup.button.callback("ℹ️ Info / መረጃ", "menu_info")
            ]
        ]);
    }
}

// --------------------------
// APP SETUP (Telegraf)
// --------------------------
const bot = new Telegraf(TOKEN);
bot.use(session());


// --------------------------
// START
// --------------------------
bot.start(async (ctx) => {
    const user_id = ctx.from.id;
    const first_name = ctx.from.first_name || '';
    const ref_id = ctx.message.text.split(' ')[1] || null;
    ctx.session = ctx.session || {};
    ctx.session.ref_by = ref_id;

    if (await db.user_exists(user_id)) {
        const lang = await db.get_user_language(user_id);
        await db.update_user_name(user_id, first_name);
        const menu = getMainMenu(lang);
        await ctx.reply(t('welcome_back', lang), menu);
        return;
    }

    const keyboard = Markup.inlineKeyboard([
        [
            Markup.button.callback("🇪🇹 አማርኛ", "lang_am"),
            Markup.button.callback("🇸🇸 English", "lang_en")
        ]
    ]);
    await ctx.reply(t('select_language'), keyboard);
});

// --------------------------
// CONTACT REGISTER
// --------------------------
bot.on('contact', async (ctx) => {
    const user_id = ctx.from.id;
    const first_name = ctx.from.first_name || '';
    const phone = normalizePhone(ctx.message.contact.phone_number);
    ctx.session = ctx.session || {};
    const lang = ctx.session.lang || 'am';

    if (await db.user_exists(user_id)) {
        const user_lang = await db.get_user_language(user_id);
        const user = await db.get_user(user_id);
        const main = await db.get_main_balance(user_id);
        const play = await db.get_play_balance(user_id);
        const ref_count = await db.get_referral_count(user_id);
        const text = t('already_registered', user_lang, { phone: user[1], main, play, ref_count });
        await ctx.reply(text, getInlineMenu(user_lang));
        await ctx.reply("⬇️ Menu:", getMainMenu(user_lang));
        return;
    }

    const ref_by = ctx.session.ref_by;
    await db.add_user(user_id, phone, first_name);
    await db.set_user_language(user_id, lang);

    if (ref_by) {
        await db.set_referral(user_id, ref_by);
    }

    const main = await db.get_main_balance(user_id);
    const play = await db.get_play_balance(user_id);
    const text = t('register_success', lang, { phone, main, play });

    await ctx.reply(text, getInlineMenu(lang));
    await ctx.reply("⬇️ Menu:", getMainMenu(lang));
});

// --------------------------
// TEXT HANDLER
// --------------------------
bot.on('text', async (ctx) => {
    if (ctx.message.web_app_data) return;
    const user_id = ctx.from.id;
    let text = ctx.message.text;
    const first_name = ctx.from.first_name || '';
    
    ctx.session = ctx.session || {};

    if (first_name && await db.user_exists(user_id)) {
        await db.update_user_name(user_id, first_name);
    }

    let lang = 'am';
    if (await db.user_exists(user_id)) {
        lang = await db.get_user_language(user_id);
    } else {
        lang = ctx.session.lang || 'am';
    }

    const main_menu_buttons_am = [
        "🎮 Open Game / ይጫወቱ",
        "💳 Deposit / ያስገቡ", "💰 Balance / ሂሳብ",
        "🐝 Withdraw / ያውጡ", "📜 History / ታሪክ",
        "👤 Profile / መገለጫ", "🏢 Support / ድጋፍ",
        "🎁 Invite Friends / ጓደኛ ይጋብዙ", "🤖 Agent Panel",
        "🔄 Transfer / ይላኩ", "ℹ️ Info / መረጃ"
    ];
    const main_menu_buttons_en = [
        "🎮 Open Game",
        "💳 Deposit", "💰 Balance",
        "🐝 Withdraw", "📜 History",
        "👤 Profile", "🏢 Support",
        "🎁 Invite Friends", "🤖 Agent Panel",
        "🔄 Transfer", "ℹ️ Info"
    ];

    if (main_menu_buttons_am.includes(text) || main_menu_buttons_en.includes(text)) {
        delete user_state[user_id];
        delete user_state[`${user_id}_amount`];
        delete user_state[`${user_id}_withdraw_amount`];
        delete user_state[`${user_id}_method`];
        delete user_state[`${user_id}_transfer_wallet`];
        delete user_state[`${user_id}_transfer_target`];
    }

    if (text === "🎮 Open Game / ይጫወቱ" || text === "🎮 Open Game") {
        const keyboard = Markup.inlineKeyboard([
            [Markup.button.webApp("🎲 Play Bingo Now", MINI_APP_URL)]
        ]);
        const game_msg = lang === 'en' ? "🎮 Tap the button below to open the Bingo Game:" : "🎮 የቢንጎ ጨዋታውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ:";
        await ctx.reply(game_msg, keyboard);
        return;
    }

    if (text === "💰 Balance / ሂሳብ" || text === "💰 Balance") {
        const main = await db.get_main_balance(user_id);
        const play = await db.get_play_balance(user_id);
        await ctx.reply(t('balance_msg', lang, { main, play }));
        return;
    }

    if (text === "🏢 Support / ድጋፍ" || text === "🏢 Support") {
        const support_msg = lang === 'en' ? 
            "☎️ Support\n\nFor any comments or questions, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82" :
            "☎️ Support (ድጋፍ)\n\nFor any comment and question, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82";
        await ctx.reply(support_msg);
        return;
    }

    if (text === "📜 History / ታሪክ" || text === "📜 History") {
        const history = await db.get_last_5_transactions(user_id);
        if (!history.length) {
            const no_hist = lang === 'am' ? "📜 ግብይት አልተደረገም / No transactions yet." : "📜 No transactions yet.";
            await ctx.reply(no_hist);
            return;
        }
        let msg = "📜 LAST 5 TRANSACTIONS\n\n";
        for (const tx of history) {
            const icon = tx[0] === "deposit" ? "🟢 Deposit" : "🔴 Withdraw";
            const clean_time = tx[2].split('.')[0];
            msg += `${icon}\n💰 Amount: ${tx[1]} ETB\n⏰ Date: ${clean_time}\n\n`;
        }
        await ctx.reply(msg);
        return;
    }

    if (text === "👤 Profile / መገለጫ" || text === "👤 Profile") {
        const user = await db.get_user(user_id);
        if (!user) {
            await ctx.reply("❌ User not found");
            return;
        }
        const link = `https://t.me/${BOT_USERNAME}?start=${user_id}`;
        const ref_count = await db.get_referral_count(user_id);
        const played = await db.get_games_played_count(user_id);
        const won = await db.get_games_won_count(user_id);
        const total_won = await db.get_total_won(user_id);
        const profile_msg = 
            "👤 PROFILE\n\n" +
            `🆔 ID: ${user[0]}\n` +
            `📱 Phone: ${user[1]}\n\n` +
            `💰 Main Wallet: ${user[2]} ETB\n` +
            `🎮 Play Wallet: ${user[3]} ETB\n\n` +
            `🎯 Games Played: ${played}\n` +
            `🏆 Games Won: ${won}\n` +
            `💵 Total Won: ${total_won} ETB\n\n` +
            `👥 Referrals: ${ref_count}\n` +
            `🎯 Invited By: ${user.length > 4 && user[4] ? user[4] : 'No inviter'}\n\n` +
            `🎁 Invite Link:\n${link}`;
        await ctx.reply(profile_msg);
        return;
    }

    if (text === "🎁 Invite Friends / ጓደኛ ይጋብዙ" || text === "🎁 Invite Friends") {
        const link = `https://t.me/${BOT_USERNAME}?start=${user_id}`;
        const ref_count = await db.get_referral_count(user_id);
        const invite_msg = 
            "🎁 Invite Friends System\n\n" +
            `👥 Your Invites: ${ref_count}\n\n` +
            `🔗 Your Referral Link:\n${link}\n\n` +
            "💰 Earn 10% commission from every deposit made by your referrals!";
        await ctx.reply(invite_msg);
        return;
    }

    if (text === "🤖 Agent Panel") {
        const invites = await db.get_referral_count(user_id);
        const depositors = await db.get_depositing_referrals_count(user_id);
        const total_deposits = await db.get_total_referral_deposits(user_id);
        let agent_msg = "";
        if (await db.is_user_agent(user_id)) {
            agent_msg = 
                "🤖 AGENT DASHBOARD\n\n" +
                "⭐ Status: Official Agent\n\n" +
                `👥 Total Invites: ${invites}\n` +
                `💳 Depositing Referrals: ${depositors}\n` +
                `💰 Total Referral Deposits: ${total_deposits} ETB\n\n` +
                "🎁 Commission Rate: 10% CASH (Main Wallet)\n\n" +
                "🚀 Keep inviting more friends to earn more real cash!";
        } else {
            agent_msg = 
                "🤖 AGENT UPGRADE PROGRAM\n\n" +
                "⭐ Status: Normal User (10% Play Wallet)\n\n" +
                "🎯 To become an Agent and earn 10% CASH (Main Wallet), you must achieve:\n\n" +
                `1️⃣ 30+ Invites\nProgress: ${invites}/30\n\n` +
                `2️⃣ 20+ Depositing Referrals\nProgress: ${depositors}/20\n\n` +
                `3️⃣ 3000+ ETB Total Referral Deposits\nProgress: ${total_deposits}/3000 ETB\n\n` +
                "💪 Keep sharing your referral link to hit these goals!";
        }
        await ctx.reply(agent_msg);
        return;
    }

    if (text === "ℹ️ Info / መረጃ" || text === "ℹ️ Info") {
        await infoCommand(ctx, lang);
        return;
    }

    if (text === "💳 Deposit / ያስገቡ" || text === "💳 Deposit") {
        user_state[user_id] = "deposit_amount";
        await ctx.reply(t('deposit_prompt', lang));
        return;
    }

    if (text === "🐝 Withdraw / ያውጡ" || text === "🐝 Withdraw") {
        const total_lifetime_deposits = await db.get_total_deposits(user_id);
        if (total_lifetime_deposits < 50) {
            await ctx.reply(t('withdraw_locked', lang));
            return;
        }
        user_state[user_id] = "withdraw_amount";
        const play_bal = await db.get_play_balance(user_id);
        const main_bal = await db.get_main_balance(user_id);
        await ctx.reply(t('withdraw_prompt', lang, { play_bal, main_bal }));
        return;
    }

    if (user_state[user_id] === "deposit_amount") {
        if (!/^\d+$/.test(text)) {
            const err_msg = lang === 'am' ? "❌ ቁጥር ብቻ ያስገቡ" : "❌ Please enter a valid number";
            await ctx.reply(err_msg);
            return;
        }
        let amount = parseInt(text);
        if (amount < 10) {
            const err_msg = lang === 'am' ? "❌ ዝቅተኛ መጠን 10 ብር ነው" : "❌ Minimum amount is 10 Birr";
            await ctx.reply(err_msg);
            return;
        }
        user_state[user_id] = "deposit_method";
        user_state[`${user_id}_amount`] = amount;
        const keyboard = Markup.keyboard([["Telebirr"], ["🔙 Back"]]).resize();
        const method_msg = lang === 'en' ? "💳 Select Payment Method:" : "💳 የክፍያ ዘዴ ይምረጡ:";
        await ctx.reply(method_msg, keyboard);
        return;
    }

    if (user_state[user_id] === "withdraw_amount") {
        if (!/^\d+$/.test(text)) {
            const err_msg = lang === 'am' ? "❌ ቁጥር ብቻ ያስገባ" : "❌ Please enter a valid number";
            await ctx.reply(err_msg);
            return;
        }
        const amount = parseInt(text);
        const balance = await db.get_main_balance(user_id);
        if (amount > balance) {
            const bal_msg = lang === 'am' ? `❌ በቂ ሂሳብ የለም (Main Wallet)\n💰 ያለዎት: ${balance} ETB` : `❌ Insufficient balance (Main Wallet)\n💰 You have: ${balance} ETB`;
            await ctx.reply(bal_msg);
            return;
        }
        if (amount < 100) {
            const err_msg = lang === 'am' ? "❌ ዝቅተኛ መጠን 100 ብር ነው" : "❌ Minimum amount is 100 Birr";
            await ctx.reply(err_msg);
            return;
        }
        user_state[user_id] = "withdraw_method";
        user_state[`${user_id}_withdraw_amount`] = amount;
        const keyboard = Markup.keyboard([["Telebirr"], ["🔙 Back"]]).resize();
        const w_method_msg = lang === 'en' ? "🏦 Select Withdraw Method:" : "🏦 የመውጣት ዘዴ ይምረጡ:";
        await ctx.reply(w_method_msg, keyboard);
        return;
    }

    if (user_state[user_id] === "deposit_method") {
        if (text === "🔙 Back") {
            await ctx.reply("👇 Main Menu", getInlineMenu(lang));
            await ctx.reply("⬇️ Menu:", getMainMenu(lang));
            delete user_state[user_id];
            delete user_state[`${user_id}_amount`];
            return;
        }
        let method, phone, app_name_am;
        if (text === "Telebirr") {
            method = "Telebirr";
            phone = "0998480054";
            app_name_am = "ቴሌብር";
        } else {
            const err_msg = lang === 'en' ? "❌ Please choose Telebirr" : "❌ ቴሌብር ይምረጡ";
            await ctx.reply(err_msg);
            return;
        }
        const amount = user_state[`${user_id}_amount`] || 0;
        user_state[user_id] = "deposit_confirm";
        user_state[`${user_id}_method`] = method;
        let pay_msg;
        if (lang === 'en') {
            pay_msg = 
                `💳 Payment Instructions\n\n` +
                `Send *${amount} Birr* to:\n\n` +
                `🏦 Method: ${method}\n` +
                `📱 Phone:\n\`${phone}\`\n\n` +
                `ℹ️ After sending the money, copy the entire confirmation SMS from Telebirr and paste it here 👇`;
        } else {
            pay_msg = 
                `💳 የክፍያ መመሪያ\n\n` +
                `ወደዚህ *${amount} ብር* ይላኩ\n\n` +
                `🏦 የክፍያ መንገድ: ${method}\n` +
                `📱 ስልክ ቁጥር:\n\`${phone}\`\n\n` +
                `ℹ️ ገንዘቡን ከላኩ በኋላ ከ${app_name_am} የተላከልዎትን ሙሉውን የማረጋገጫ SMS ኮፒ አድርገው እዚህ ላይ ፔስት አድርገው ይላኩ 👇`;
        }
        await ctx.reply(pay_msg, { parse_mode: "Markdown" });
        return;
    }

    if (user_state[user_id] === "withdraw_method") {
        if (text === "🔙 Back") {
            await ctx.reply("👇 Main Menu", getInlineMenu(lang));
            await ctx.reply("⬇️ Menu:", getMainMenu(lang));
            delete user_state[user_id];
            delete user_state[`${user_id}_withdraw_amount`];
            return;
        }
        let method;
        if (text === "Telebirr") {
            method = "Telebirr";
        } else {
            await ctx.reply("❌ Please choose Telebirr");
            return;
        }
        const amount = user_state[`${user_id}_withdraw_amount`] || 0;
        const user = await db.get_user(user_id);
        const user_phone = user ? user[1] : "N/A";
        delete user_state[user_id];
        delete user_state[`${user_id}_withdraw_amount`];
        
        await ctx.reply("⏳ Withdraw request sent to admin", getMainMenu(lang));
        request_counter += 1;
        const req_num = request_counter;
        withdraw_requests[req_num] = {
            user_id: user_id,
            amount: amount,
            method: method,
            phone: user_phone
        };
        const admin_msg = 
            `🚨 WITHDRAW REQUEST #${req_num}\n\n` +
            `👤 User ID: ${user_id}\n` +
            `📱 Phone: ${user_phone}\n\n` +
            `💰 Amount: ${amount} ETB\n` +
            `🏦 Method: ${method}\n\n` +
            `✅ To Approve send:\n/ap ${req_num}\n\n` +
            `❌ To Reject send:\n/re ${req_num}`;
        for (const admin_id of ADMIN_IDS) {
            try {
                await bot.telegram.sendMessage(admin_id, admin_msg);
            } catch (e) {}
        }
        return;
    }

    if (user_state[user_id] === "deposit_confirm") {
        const amount = user_state[`${user_id}_amount`] || 0;
        const method = user_state[`${user_id}_method`] || "Unknown";

        if (text === "🔙 Back") {
            user_state[user_id] = "deposit_method";
            const keyboard = Markup.keyboard([["Telebirr"], ["🔙 Back"]]).resize();
            const method_msg = lang === 'en' ? "💳 Select Payment Method:" : "💳 የክፍያ ዘዴ ይምረጡ:";
            await ctx.reply(method_msg, keyboard);
            return;
        }

        const result = verifyTelebirrSms(text, amount);

        if (!result.valid) {
            await ctx.reply(result.reason, { parse_mode: "Markdown" });
            return;
        }

        const transaction_id = result.transaction_id;
        const confirmed_amount = parseInt(result.amount);
        const bonus = parseInt(confirmed_amount * 0.10);
        const total = confirmed_amount + bonus;

        await _markTransactionUsed(transaction_id, user_id, confirmed_amount);

        await db.update_play_balance(user_id, total);
        await db.add_transaction(user_id, "deposit", total);
        const new_balance = await db.get_play_balance(user_id);

        const user = await db.get_user(user_id);
        const ref_by = user && user.length > 4 ? user[4] : null;
        
        if (ref_by) {
            if (await db.is_user_agent(parseInt(ref_by))) {
                const ref_bonus = parseInt(confirmed_amount * 0.10);
                await db.update_main_balance(parseInt(ref_by), ref_bonus);
                try {
                    await bot.telegram.sendMessage(
                        parseInt(ref_by),
                        "🤝 Agent Cash Commission!\n\n" +
                        `👤 Your referral deposited: ${confirmed_amount} ETB\n` +
                        `💰 You earned: ${ref_bonus} ETB (10% Cash)\n\n` +
                        "💸 Added to your Main Wallet!"
                    );
                } catch (e) {}
            } else {
                const ref_bonus = parseInt(confirmed_amount * 0.10);
                await db.update_play_balance(parseInt(ref_by), ref_bonus);
                try {
                    await bot.telegram.sendMessage(
                        parseInt(ref_by),
                        "🎉 Referral Deposit Bonus!\n\n" +
                        `👤 Your referral deposited: ${confirmed_amount} ETB\n` +
                        `💰 You earned: ${ref_bonus} ETB (10%)\n\n` +
                        "🙏 Keep inviting more friends!"
                    );
                } catch (e) {}
            }
            if (await db.check_and_upgrade_agent(parseInt(ref_by))) {
                try {
                    await bot.telegram.sendMessage(
                        parseInt(ref_by),
                        "🎉 Congratulations! You are now an Official Agent! 🤝\n\n" +
                        "✅ 30+ Invites\n✅ 20+ Referral Deposits\n✅ 3000+ ETB Total\n\n" +
                        "🎁 From now on you earn 10% CASH to Main Wallet!"
                    );
                } catch (e) {}
            }
        }

        delete user_state[user_id];
        delete user_state[`${user_id}_amount`];
        delete user_state[`${user_id}_method`];

        for (const admin_id of ADMIN_IDS) {
            try {
                await bot.telegram.sendMessage(
                    admin_id,
                    "✅ DEPOSIT VERIFIED\n\n" +
                    `👤 User ID: ${user_id}\n` +
                    `💰 Amount: ${confirmed_amount} ETB\n` +
                    `🎁 Bonus: ${bonus} ETB\n` +
                    `📈 Total: ${total} ETB\n` +
                    `🔖 TXN: ${transaction_id}\n` +
                    `📅 ${result.date || ''} ${result.time || ''}`
                );
            } catch (e) {}
        }

        await ctx.reply(
            t('deposit_success', lang, { method, amount: confirmed_amount, bonus, total, new_balance }),
            getMainMenu(lang)
        );
        return;
    }

    if (text === "🔄 Transfer / ይላኩ" || text === "🔄 Transfer") {
        const total_lifetime_deposits = await db.get_total_deposits(user_id);
        if (total_lifetime_deposits < 50) {
            const err_msg = lang === 'am' ? 
                "❌ ማዞር (መላክ) አይችሉም!\n\n⚠️ ገንዘብ ለማዞር (ለመላክ) 50 ብር ማስገባት አለብዎት።ፔ\n\n❌ You cannot transfer. You must deposit at least 50 ETB in total to unlock transfers." :
                "❌ Transfer locked!\n\n⚠️ You must deposit at least 50 ETB in total to unlock transfers.";
            await ctx.reply(err_msg);
            return;
        }
        user_state[user_id] = "transfer_select_wallet";
        const keyboard = Markup.keyboard([["Main Wallet", "Play Wallet"], ["🔙 Back"]]).resize();
        const tr_msg = lang === 'en' ? "🔄 Select the wallet you want to send from:" : "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?";
        await ctx.reply(tr_msg, keyboard);
        return;
    }

    if (user_state[user_id] === "transfer_select_wallet") {
        if (text === "🔙 Back") {
            await ctx.reply("👇 Main Menu", getInlineMenu(lang));
            await ctx.reply("⬇️ Menu:", getMainMenu(lang));
            delete user_state[user_id];
            return;
        }
        if (text !== "Main Wallet" && text !== "Play Wallet") {
            const err_msg = lang === 'en' ? "❌ Please choose Main Wallet or Play Wallet" : "❌ እባክዎ Main Wallet ወይም Play Wallet ይምረጡ";
            await ctx.reply(err_msg);
            return;
        }
        user_state[`${user_id}_transfer_wallet`] = text;
        user_state[user_id] = "transfer_phone";
        const keyboard = Markup.keyboard([["🔙 Back"]]).resize();
        const phone_msg = lang === 'en' ? 
            "📱 Enter the registered phone number of the person you want to send to:\n\n(Example: 0912345678)" :
            "📱 ለመላክ የሚፈልጉትን ስልክ ቁጥር ያስገቡ:\n\n(ምሳሌ: 0912345678)";
        await ctx.reply(phone_msg, keyboard);
        return;
    }

    if (user_state[user_id] === "transfer_phone") {
        if (text === "🔙 Back") {
            user_state[user_id] = "transfer_select_wallet";
            const keyboard = Markup.keyboard([["Main Wallet", "Play Wallet"], ["🔙 Back"]]).resize();
            const tr_msg = lang === 'en' ? "🔄 Select the wallet you want to send from:" : "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?";
            await ctx.reply(tr_msg, keyboard);
            return;
        }
        const clean_phone = normalizePhone(text);
        const receiver_user = await db.get_user_by_phone(clean_phone);
        if (!receiver_user) {
            const err_msg = lang === 'en' ? "❌ This phone number is not registered in our bot." : "❌ ይህ ስልክ ቁጥር በቦቱ ውስጥ አልተመዘገበም";
            await ctx.reply(err_msg);
            return;
        }
        if (receiver_user[0] === user_id) {
            const err_msg = lang === 'en' ? "❌ You cannot transfer money to yourself!" : "❌ ለራስዎ ገንዘብ ማዞር (መላክ) አይችሉም!";
            await ctx.reply(err_msg);
            return;
        }
        user_state[`${user_id}_transfer_target`] = receiver_user[0];
        user_state[user_id] = "transfer_amount";
        const keyboard = Markup.keyboard([["🔙 Back"]]).resize();
        const amt_msg = lang === 'en' ? "💰 Enter the amount you want to transfer (ETB):\n\nMin: 10 ETB" : "💰 ለመላክ የሚፈልጉትን መጠን ያስገቡ (ETB):\n\nዝቅተኛ: 10 ETB";
        await ctx.reply(amt_msg, keyboard);
        return;
    }

    if (user_state[user_id] === "transfer_amount") {
        if (text === "🔙 Back") {
            user_state[user_id] = "transfer_phone";
            const keyboard = Markup.keyboard([["🔙 Back"]]).resize();
            const phone_msg = lang === 'en' ? 
                "📱 Enter the registered phone number of the person you want to send to:\n\n(Example: 0912345678)" :
                "📱 ለመላክ የሚፈልጉትን ስልክ ቁጥር ያስገቡ:\n\n(ምሳሌ: 0912345678)";
            await ctx.reply(phone_msg, keyboard);
            return;
        }
        if (!/^\d+$/.test(text)) {
            const err_msg = lang === 'am' ? "❌ ቁጥር ብቻ ያስገባ" : "❌ Please enter a valid number";
            await ctx.reply(err_msg);
            return;
        }
        const amount = parseInt(text);
        const wallet_type = user_state[`${user_id}_transfer_wallet`];
        const target_id = user_state[`${user_id}_transfer_target`];
        if (amount < 10) {
            const err_msg = lang === 'am' ? "❌ ዝቅተኛ መጠን 10 ብር ነው" : "❌ Minimum amount is 10 ETB";
            await ctx.reply(err_msg);
            return;
        }
        let balance;
        if (wallet_type === "Main Wallet") {
            balance = await db.get_main_balance(user_id);
        } else {
            balance = await db.get_play_balance(user_id);
        }
        if (amount > balance) {
            const err_msg = lang === 'am' ? `❌ በቂ ሂሳብ የለም (${wallet_type})\n💰 ያለዎት: ${balance} ETB` : `❌ Insufficient balance (${wallet_type})\n💰 Balance: ${balance} ETB`;
            await ctx.reply(err_msg);
            return;
        }
        if (wallet_type === "Main Wallet") {
            await db.update_main_balance(user_id, -amount);
            await db.update_main_balance(target_id, amount);
        } else {
            await db.update_play_balance(user_id, -amount);
            await db.update_play_balance(target_id, amount);
        }
        await db.add_transaction(user_id, "transfer_out", amount);
        const sender_name = ctx.from.first_name;
        let receiver_name = "User";
        try {
            const receiver_chat = await bot.telegram.getChat(target_id);
            receiver_name = receiver_chat.first_name || "User";
        } catch (e) {}

        delete user_state[user_id];
        delete user_state[`${user_id}_transfer_wallet`];
        delete user_state[`${user_id}_transfer_target`];

        const sender_success_msg = 
            `✅ Transfer Successful!\n\n` +
            `💸 Sent: {amount} ETB\n` +
            `👤 To: ${receiver_name}\n` +
            `🏦 Wallet: ${wallet_type}\n` +
            `✅ Money added to the user's ${wallet_type}.`;
        await ctx.reply(sender_success_msg, getInlineMenu(lang));
        await ctx.reply("⬇️ Menu:", getMainMenu(lang));
        
        const receiver_msg = 
            `💰 Money Received!\n\n` +
            `💸 Amount: ${amount} ETB\n` +
            `👤 From: ${sender_name}\n` +
            `🏦 Wallet: ${wallet_type}\n` +
            `✅ The money has been added to your ${wallet_type}.`;
        try {
            await bot.telegram.sendMessage(target_id, receiver_msg);
        } catch (e) {}
        return;
    }

    const fallback_msg = lang === 'en' ? "👇 Please use the menu buttons" : "👇 የሜኑ ቁልፎችን ይጠቀሙ";
    await ctx.reply(fallback_msg);
});

// --------------------------
// WEB APP DATA HANDLER
// --------------------------
bot.on('web_app_data', async (ctx) => {
    const user_id = ctx.from.id;
    const user_name = ctx.from.first_name;
    const data = ctx.message.web_app_data.data;
    console.log(`🎮 Bingo win received from ${user_name} (${user_id})! Data: ${data}`);
    await ctx.reply(`🎉 Congratulations! Your bingo result has been recorded!\n\nData: ${data}`);
    for (const admin_id of ADMIN_IDS) {
        try {
            await bot.telegram.sendMessage(admin_id, `🎮 User ${user_name} just won a Bingo game!\nData: ${data}`);
        } catch (e) {
            console.log(`Could not notify admin ${admin_id}: ${e.message}`);
        }
    }
});

// --------------------------
// CALLBACK QUERY HANDLER
// --------------------------
bot.on('callback_query', async (ctx) => {
    await ctx.answerCbQuery();
    const user_id = ctx.from.id;
    const data = ctx.callbackQuery.data;
    const first_name = ctx.from.first_name || '';
    
    ctx.session = ctx.session || {};

    if (first_name && await db.user_exists(user_id)) {
        await db.update_user_name(user_id, first_name);
    }

    if (data === "lang_am" || data === "lang_en") {
        const lang = data === "lang_am" ? 'am' : 'en';
        ctx.session.lang = lang;
        if (await db.user_exists(user_id)) {
            await db.set_user_language(user_id, lang);
            await ctx.editMessageText(t('lang_changed', lang));
            await bot.telegram.sendMessage(user_id, t('welcome_back', lang), getMainMenu(lang));
        } else {
            const button_text = t('share_phone_btn', lang);
            const keyboard = Markup.keyboard([[Markup.button.contactRequest(button_text)]]).resize().oneTime();
            await ctx.editMessageText(t('select_language'));
            await bot.telegram.sendMessage(user_id, t('welcome_new', lang), keyboard);
        }
        return;
    }

    let lang = 'am';
    if (await db.user_exists(user_id)) {
        lang = await db.get_user_language(user_id);
    } else {
        lang = ctx.session.lang || 'am';
    }

    if (data.startsWith("menu_")) {
        delete user_state[user_id];
        delete user_state[`${user_id}_amount`];
        delete user_state[`${user_id}_withdraw_amount`];
        delete user_state[`${user_id}_method`];
        delete user_state[`${user_id}_transfer_wallet`];
        delete user_state[`${user_id}_transfer_target`];
    }

    if (data === "menu_open_game") {
        const keyboard = Markup.inlineKeyboard([[Markup.button.webApp("🎲 Play Bingo Now", MINI_APP_URL)]]);
        const game_msg = lang === 'en' ? "🎮 Tap the button below to open the Bingo Game:" : "🎮 የቢንጎ ጨዋታውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ:";
        await ctx.reply(game_msg, keyboard);
    } else if (data === "menu_balance") {
        const main = await db.get_main_balance(user_id);
        const play = await db.get_play_balance(user_id);
        await ctx.reply(t('balance_msg', lang, { main, play }));
    } else if (data === "menu_deposit") {
        user_state[user_id] = "deposit_amount";
        await ctx.reply(t('deposit_prompt', lang));
    } else if (data === "menu_withdraw") {
        const total_lifetime_deposits = await db.get_total_deposits(user_id);
        if (total_lifetime_deposits < 50) {
            await ctx.reply(t('withdraw_locked', lang));
        } else {
            user_state[user_id] = "withdraw_amount";
            const play_bal = await db.get_play_balance(user_id);
            const main_bal = await db.get_main_balance(user_id);
            await ctx.reply(t('withdraw_prompt', lang, { play_bal, main_bal }));
        }
    } else if (data === "menu_history") {
        const history = await db.get_last_5_transactions(user_id);
        if (!history.length) {
            const no_hist = lang === 'am' ? "📜 ግብይት አልተደረገም / No transactions yet." : "📜 No transactions yet.";
            await ctx.reply(no_hist);
        } else {
            let msg = "📜 LAST 5 TRANSACTIONS\n\n";
            for (const tx of history) {
                const icon = tx[0] === "deposit" ? "🟢 Deposit" : "🔴 Withdraw";
                const clean_time = tx[2].split('.')[0];
                msg += `${icon}\n💰 Amount: ${tx[1]} ETB\n⏰ Date: ${clean_time}\n\n`;
            }
            await ctx.reply(msg);
        }
    } else if (data === "menu_profile") {
        const user = await db.get_user(user_id);
        if (user) {
            const link = `https://t.me/${BOT_USERNAME}?start=${user_id}`;
            const ref_count = await db.get_referral_count(user_id);
            const played = await db.get_games_played_count(user_id);
            const won = await db.get_games_won_count(user_id);
            const total_won_amt = await db.get_total_won(user_id);
            const profile_msg = 
                "👤 PROFILE\n\n" +
                `🆔 ID: ${user[0]}\n` +
                `📱 Phone: ${user[1]}\n\n` +
                `💰 Main Wallet: ${user[2]} ETB\n` +
                `🎮 Play Wallet: ${user[3]} ETB\n\n` +
                `🎯 Games Played: ${played}\n` +
                `🏆 Games Won: ${won}\n` +
                `💵 Total Won: ${total_won_amt} ETB\n\n` +
                `👥 Referrals: ${ref_count}\n` +
                `🎯 Invited By: ${user.length > 4 && user[4] ? user[4] : 'No inviter'}\n\n` +
                `🎁 Invite Link:\n${link}`;
            await ctx.reply(profile_msg);
        } else {
            await ctx.reply("❌ User not found");
        }
    } else if (data === "menu_support") {
        const support_msg = lang === 'en' ? 
            "☎️ Support\n\nFor any comments or questions, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82" :
            "☎️ Support (ድጋፍ)\n\nFor any comment and question, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82";
        await ctx.reply(support_msg);
    } else if (data === "menu_invite") {
        const link = `https://t.me/${BOT_USERNAME}?start=${user_id}`;
        const ref_count = await db.get_referral_count(user_id);
        const invite_msg = 
            "🎁 Invite Friends System\n\n" +
            `👥 Your Invites: ${ref_count}\n\n` +
            `🔗 Your Referral Link:\n${link}\n\n` +
            "💰 Earn 10% commission from every deposit made by your referrals!";
        await ctx.reply(invite_msg);
    } else if (data === "menu_agent") {
        const invites = await db.get_referral_count(user_id);
        const depositors = await db.get_depositing_referrals_count(user_id);
        const total_deposits = await db.get_total_referral_deposits(user_id);
        let agent_msg;
        if (await db.is_user_agent(user_id)) {
            agent_msg = 
                "🤖 AGENT DASHBOARD\n\n⭐ Status: Official Agent\n\n" +
                `👥 Total Invites: ${invites}\n` +
                `💳 Depositing Referrals: ${depositors}\n` +
                `💰 Total Referral Deposits: ${total_deposits} ETB\n\n` +
                "🎁 Commission Rate: 10% CASH (Main Wallet)\n\n" +
                "🚀 Keep inviting more friends to earn more real cash!";
        } else {
            agent_msg = 
                "🤖 AGENT UPGRADE PROGRAM\n\n⭐ Status: Normal User (10% Play Wallet)\n\n" +
                `1️⃣ 30+ Invites\nProgress: ${invites}/30\n\n` +
                `2️⃣ 20+ Depositing Referrals\nProgress: ${depositors}/20\n\n` +
                `3️⃣ 3000+ ETB Total Referral Deposits\nProgress: ${total_deposits}/3000 ETB\n\n` +
                "💪 Keep sharing your referral link to hit these goals!";
        }
        await ctx.reply(agent_msg);
    } else if (data === "menu_transfer") {
        const total_lifetime_deposits = await db.get_total_deposits(user_id);
        if (total_lifetime_deposits < 50) {
            const err_msg = lang === 'am' ? 
                "❌ ማዞር (መላክ) አይችሉም!\n\n⚠️ ገንዘብ ለማዞር (ለመላክ) 50 ብር ማስገባት አለብዎት።ፔ\n\n❌ You cannot transfer. You must deposit at least 50 ETB in total to unlock transfers." :
                "❌ Transfer locked!\n\n⚠️ You must deposit at least 50 ETB in total to unlock transfers.";
            await ctx.reply(err_msg);
        } else {
            user_state[user_id] = "transfer_select_wallet";
            const keyboard = Markup.keyboard([["Main Wallet", "Play Wallet"], ["🔙 Back"]]).resize();
            const tr_msg = lang === 'en' ? "🔄 Select the wallet you want to send from:" : "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?";
            await ctx.reply(tr_msg, keyboard);
        }
    } else if (data === "menu_info") {
        await infoCommand(ctx, lang);
    }
});

// --------------------------
// INFO COMMAND
// --------------------------
async function infoCommand(ctx, lang = null) {
    const user_id = ctx.from.id;
    if (!lang) {
        if (await db.user_exists(user_id)) {
            lang = await db.get_user_language(user_id);
        } else {
            lang = ctx.session.lang || 'am';
        }
    }
    if (lang === 'en') {
        await ctx.reply(
            "☎️ Support\n\nIf you have any problems, contact @one_day_82\n\n" +
            "ℹ️ Information\n\n🎮 How to play\n" +
            "1. Click \"Open Game\"\n2. Select your Bingo cards\n" +
            "3. Follow along as numbers are called\n4. Complete a winning pattern to win!\n\n" +
            "Good luck! 🍀"
        );
    } else {
        await ctx.reply(
            "☎️ Support(ድጋፍ)\n\nችግር ካጋጠመዎት @one_day_82 ን ያግኙ\n\n" +
            "ℹ️ Information(መረጃ)\n\n🎮 እንዴት እንደሚጫወቱ\n" +
            "1. \"Play Now/ይጫወቱ\" የሚለውን ይጫኑ\n" +
            "2. የቢንጎ ካርዶችዎን ይምረጡ\n" +
            "3. ቁጥሮች ሲጠሩ እየተተኩ ካርዶችዎ ውስጥ ካሉ ያጥቁሩ\n" +
            "4. ቢያንስ አንድ የማሸነፊያ ንድፍ ሲያጠናቅቁ \"BINGO\" ይበሉ\n\n" +
            "መልካም ዕድል ይገጥምዎ! 🍀"
        );
    }
}

// --------------------------
// APPROVE / REJECT
// --------------------------
bot.command('ap', async (ctx) => {
    if (!ADMIN_IDS.includes(ctx.from.id)) return;
    const args = ctx.message.text.split(' ');
    if (!args[1]) {
        await ctx.reply("❌ Please provide the request number. Example: /ap 1");
        return;
    }
    let req_num;
    try {
        req_num = parseInt(args[1]);
    } catch (e) {
        await ctx.reply("❌ Invalid number. Example: /ap 1");
        return;
    }
    if (!withdraw_requests[req_num]) {
        await ctx.reply(`❌ Request #${req_num} not found.`);
        return;
    }
    const req_data = withdraw_requests[req_num];
    const user_id = req_data.user_id;
    const amount = req_data.amount;
    const balance = await db.get_main_balance(user_id);
    if (amount > balance) {
        await ctx.reply(`❌ Insufficient user balance. User only has ${balance} ETB.`);
        return;
    }
    await db.update_main_balance(user_id, -amount);
    await db.add_transaction(user_id, "withdraw", amount);
    await bot.telegram.sendMessage(user_id, `✅ Withdraw Approved\n💰 Amount: ${amount} ETB`);
    await ctx.reply(`✅ Request #${req_num} Approved successfully`);
    delete withdraw_requests[req_num];
});

bot.command('re', async (ctx) => {
    if (!ADMIN_IDS.includes(ctx.from.id)) return;
    const args = ctx.message.text.split(' ');
    if (!args[1]) {
        await ctx.reply("❌ Please provide the request number. Example: /re 1");
        return;
    }
    let req_num;
    try {
        req_num = parseInt(args[1]);
    } catch (e) {
        await ctx.reply("❌ Invalid number. Example: /re 1");
        return;
    }
    if (!withdraw_requests[req_num]) {
        await ctx.reply(`❌ Request #${req_num} not found.`);
        return;
    }
    const req_data = withdraw_requests[req_num];
    const user_id = req_data.user_id;
    await bot.telegram.sendMessage(user_id, "❌ Withdraw Request Rejected");
    await ctx.reply(`❌ Request #${req_num} Rejected successfully`);
    delete withdraw_requests[req_num];
});

// --------------------------
// COMMAND SHORTCUTS
// --------------------------
bot.command('play', async (ctx) => { ctx.message.text = "🎮 Open Game"; await bot.handleUpdate(ctx.update); });
bot.command('deposit', async (ctx) => { ctx.message.text = "💳 Deposit"; await bot.handleUpdate(ctx.update); });
bot.command('balance', async (ctx) => { ctx.message.text = "💰 Balance"; await bot.handleUpdate(ctx.update); });
bot.command('withdraw', async (ctx) => { ctx.message.text = "🐝 Withdraw"; await bot.handleUpdate(ctx.update); });
bot.command('profile', async (ctx) => { ctx.message.text = "👤 Profile"; await bot.handleUpdate(ctx.update); });
bot.command('support', async (ctx) => { ctx.message.text = "🏢 Support"; await bot.handleUpdate(ctx.update); });
bot.command('invite', async (ctx) => { ctx.message.text = "🎁 Invite Friends"; await bot.handleUpdate(ctx.update); });
bot.command('transfer', async (ctx) => { ctx.message.text = "🔄 Transfer"; await bot.handleUpdate(ctx.update); });
bot.command('history', async (ctx) => { ctx.message.text = "📜 History"; await bot.handleUpdate(ctx.update); });
bot.command('agent', async (ctx) => { ctx.message.text = "🤖 Agent Panel"; await bot.handleUpdate(ctx.update); });
bot.command('lang', async (ctx) => {
    const keyboard = Markup.inlineKeyboard([
        [
            Markup.button.callback("🇪🇹 አማርኛ", "lang_am"),
            Markup.button.callback("🇸🇸 English", "lang_en")
        ]
    ]);
    await ctx.reply(t('select_language', 'en'), keyboard);
});
bot.command('info', async (ctx) => await infoCommand(ctx));


// ==========================
// EXPRESS API SERVER + SOCKETIO
// ==========================
const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, {
    cors: {
        origin: "*",
        methods: ["GET", "POST", "OPTIONS"]
    }
});

app.use((req, res, next) => {
    res.setHeader('ngrok-skip-browser-warning', 'true');
    next();
});

io.on('connect', (socket) => {
    console.log(`🔌 Client connected: ${socket.id}`);
    for (const [room_id, game] of Object.entries(game_states)) {
        let time_left = 0;
        if (game.timer_started_at && !game.running) {
            time_left = Math.max(0, 35 - Math.floor(Date.now() / 1000 - game.timer_started_at));
        }
        socket.emit('game_state_update', {
            room: room_id,
            game_running: game.running,
            game_id: game.game_id,
            time_left: time_left,
            total_players: count_total_cards(game),
            called_numbers: [...(game.called || [])],
            current_number: game.current || null,
            // ✅ FIX: send full player list to late joiners so they see who already picked cards
            players: Object.entries(game.ready_players || {}).map(([uid, p]) => ({
                user_id: uid,
                name: p.name,
                cards: p.cards,
            }))
        });
    }

    socket.on('disconnect', () => {
        console.log(`🔌 Client disconnected: ${socket.id}`);
    });

    socket.on('join_room', (data) => {
        const room = data.room || '10';
        const socket_room = `bingo_room_${room}`;
        socket.join(socket_room);
        console.log(`👤 Player joined room: ${socket_room}`);
    });

    socket.on('leave_room', (data) => {
        const room = data.room || '10';
        const socket_room = `bingo_room_${room}`;
        socket.leave(socket_room);
    });

    socket.on('request_countdown', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);
        if (!game.running && !game.timer_started_at) {
            game.timer_started_at = Math.floor(Date.now() / 1000);
            game.game_id = data.game_id || generateGameId();
            io.to(`bingo_room_${room}`).emit('countdown_update', {
                room: room,
                game_id: game.game_id,
                time_left: 35
            });
        }
    });

    // ✅ FIXED: player_ready now broadcasts full player list so all clients see card selections in real time
    socket.on('player_ready', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);

        const user_id = data.user_id;
        const name = data.name || 'Player';
        const cards = data.cards || [];
        const game_id = data.game_id;

        if (game_id === game.game_id && !game.winner_declared) {
            game.ready_players[user_id] = {
                name: name,
                cards: cards,
                card_num: cards.length > 0 ? cards[0] : '—',
            };
            const total = count_total_cards(game);
            game.total_players = total;
        }

        // ✅ Broadcast to entire room with user_id + selected_cards
        // so every client can show who picked which card in the lobby
        io.to(`bingo_room_${room}`).emit('player_joined', {
            room: room,
            total_players: count_total_cards(game),
            player_name: name,
            user_id: user_id,
            selected_cards: cards,
        });
    });

    socket.on('declare_winner', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);

        let stake = 10;
        const parsedRoom = parseInt(room);
        if (!isNaN(parsedRoom)) stake = parsedRoom;

        const user_id = data.user_id;
        const winner_name = data.name || 'Player';
        const card_num = data.card_num || '—';
        const card_index = data.card_index || 0;
        const game_id = data.game_id || game.game_id;

        if (game.winner_declared) return;
        game.winner_declared = true;

        if (!game.ready_players[user_id]) {
            game.ready_players[user_id] = {
                name: winner_name,
                cards: [],
                card_num: card_num
            };
        }

        const total_players = count_total_cards(game);
        const prize = Math.round(total_players * stake * 0.8);

        io.to(`bingo_room_${room}`).emit('winner_found', {
            room: room,
            user_id: user_id,
            winner_name: winner_name,
            card_num: card_num,
            card_index: card_index,
            prize: prize,
            total_players: total_players,
            game_id: game_id,
        });
    });

    socket.on('admin_manual_call', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);
        const number = data.number;
        const admin = data.admin || 'admin';
        
        if (!number || typeof number !== 'number' || number < 1 || number > 75) return;
        if (game.called.includes(number)) return;
        
        game.called.push(number);
        game.current = number;
        io.to(`bingo_room_${room}`).emit('ball_called', { room, number, manual: true, admin });
    });

    socket.on('set_max_winners', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);
        const mx = data.max || 1;
        game.max_winners = Math.max(1, Math.min(4, parseInt(mx)));
        io.to(`bingo_room_${room}`).emit('max_winners_updated', { room, max: game.max_winners });
    });

    socket.on('admin_pause_game', (data) => {
        const room = data.room || '10';
        const game = get_game_state(room);
        game.paused = !game.paused;
        io.to(`bingo_room_${room}`).emit('game_paused', { room, paused: game.paused });
    });

    socket.on('admin_cancel_game', (data) => {
        const room = data.room || '10';
        game_states[room] = default_game_state();
        game_states[room].timer_started_at = Math.floor(Date.now() / 1000);
        io.to(`bingo_room_${room}`).emit('game_cancelled', { room, reason: 'admin_cancelled' });
    });
});

function generateGameId() {
    const d = new Date();
    return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}_${Math.floor(Date.now()/1000)%10000}`;
}

// ==========================================
// FLASK API ROUTES -> EXPRESS
// ==========================================

app.get('/api/ping', (req, res) => {
    res.json({ success: true, message: 'API is running', time: Math.floor(Date.now()/1000) });
});

app.post('/api/update_name', async (req, res) => {
    const { user_id, first_name } = req.body;
    if (!user_id || !first_name) return res.status(400).json({ success: false, error: 'user_id and first_name required' });
    try {
        const uid = parseInt(user_id);
        if (isNaN(uid)) return res.status(400).json({ success: false, error: 'invalid user_id' });
        if (await db.user_exists(uid)) await db.update_user_name(uid, first_name);
        res.json({ success: true });
    } catch (e) {
        res.status(400).json({ success: false, error: 'invalid user_id' });
    }
});

app.get('/api/balance', async (req, res) => {
    const user_id = parseInt(req.query.user_id);
    if (!user_id) return res.status(400).json({ success: false, error: 'user_id required' });
    if (!await db.user_exists(user_id)) return res.status(404).json({ success: false, error: 'User not found. Please register in bot first.' });

    const user_data = await db.get_user_full(user_id);
    const status = user_data ? (user_data.status || 'active') : 'active';
    const is_vip = user_data ? (user_data.is_vip || 0) : 0;

    res.json({
        success: true,
        main_balance: await db.get_main_balance(user_id),
        play_balance: await db.get_play_balance(user_id),
        is_banned: status === 'banned',
        is_frozen: status === 'frozen',
        is_vip: is_vip === 1
    });
});

app.post('/api/bet', async (req, res) => {
    const { user_id, amount } = req.body;
    if (!user_id) return res.status(400).json({ success: false, error: 'user_id required' });
    let uid;
    try { uid = parseInt(user_id); } catch { return res.status(400).json({ success: false, error: 'invalid user_id' }); }
    if (!await db.user_exists(uid)) return res.status(404).json({ success: false, error: 'User not found' });

    const user_data = await db.get_user_full(uid);
    const status = user_data ? (user_data.status || 'active') : 'active';
    if (status === 'banned') return res.status(403).json({ success: false, error: 'Account banned. Contact support.' });
    if (status === 'frozen') return res.status(403).json({ success: false, error: 'Account frozen. Contact support.' });

    const success = await db.deduct_bet_smart(uid, amount || 0);
    if (!success) return res.status(400).json({ success: false, error: 'Insufficient balance', play_balance: await db.get_play_balance(uid), main_balance: await db.get_main_balance(uid) });

    await db.add_transaction(uid, 'bingo_bet', amount);
    res.json({ success: true, main_balance: await db.get_main_balance(uid), play_balance: await db.get_play_balance(uid) });
});

app.post('/api/win', async (req, res) => {
    const { user_id, amount, game_id } = req.body;
    if (!user_id) return res.status(400).json({ success: false, error: 'user_id required' });
    let uid;
    try { uid = parseInt(user_id); } catch { return res.status(400).json({ success: false, error: 'invalid user_id' }); }
    if (!await db.user_exists(uid)) return res.status(404).json({ success: false, error: 'User not found' });

    const user_data = await db.get_user_full(uid);
    const status = user_data ? (user_data.status || 'active') : 'active';
    if (status === 'banned') return res.status(403).json({ success: false, error: 'Account banned' });
    if (status === 'frozen') return res.status(403).json({ success: false, error: 'Account frozen' });

    await db.update_main_balance(uid, amount || 0);
    await db.add_transaction(uid, 'bingo_win', amount);
    await db.complete_game_session(uid, game_id || '', `+${amount} Br`, amount);
    res.json({ success: true, main_balance: await db.get_main_balance(uid), play_balance: await db.get_play_balance(uid) });
});

app.post('/api/game_played', async (req, res) => {
    const { user_id, game_id, cards, stake } = req.body;
    if (!user_id) return res.status(400).json({ success: false, error: 'user_id required' });
    let uid;
    try { uid = parseInt(user_id); } catch { return res.status(400).json({ success: false, error: 'invalid user_id' }); }
    if (!await db.user_exists(uid)) return res.status(404).json({ success: false, error: 'User not found' });
    await db.add_game_session(uid, game_id, cards, stake || 10);
    res.json({ success: true });
});

app.get('/api/game_state', (req, res) => {
    const room = req.query.room || '10';
    const game = get_game_state(room);
    const now = Math.floor(Date.now() / 1000);
    let time_left = 35;

    if (!game.running) {
        if (game.timer_started_at) {
            const elapsed = Math.floor(now - game.timer_started_at);
            time_left = Math.max(0, 35 - elapsed);
        } else {
            game.timer_started_at = now;
            time_left = 35;
        }
    }

    res.json({
        room: room,
        game_running: game.running,
        game_id: game.game_id,
        time_left: time_left,
        total_players: count_total_cards(game),
        called_numbers: [...game.called],
        current_number: game.current || null,
        call_count: game.called.length,
        // ✅ FIX: include players so frontend can show card selections on page load
        players: Object.entries(game.ready_players || {}).map(([uid, p]) => ({
            user_id: uid,
            name: p.name,
            cards: p.cards,
        }))
    });
});

app.post('/api/start_game', (req, res) => {
    const { room, game_id } = req.body;
    const game = get_game_state(room || '10');
    game.running = true;
    game.game_id = game_id || '';
    game.started_at = Math.floor(Date.now() / 1000);
    game.timer_started_at = null;
    game.total_players = 0;
    game.ready_players = {};
    game.winner_declared = false;
    res.json({ success: true });
});

app.post('/api/end_game', (req, res) => {
    const room = req.body.room || '10';
    game_states[room] = default_game_state();
    game_states[room].timer_started_at = Math.floor(Date.now() / 1000);
    io.to(`bingo_room_${room}`).emit('game_cancelled', { room, reason: 'game_ended' });
    res.json({ success: true });
});

app.get('/api/profile_stats', async (req, res) => {
    const user_id = parseInt(req.query.user_id);
    if (!user_id || !await db.user_exists(user_id)) return res.status(404).json({ success: false, error: 'User not found' });

    const user_data = await db.get_user_full(user_id);
    const is_vip = user_data ? (user_data.is_vip || 0) : 0;

    res.json({
        success: true,
        games_played: await db.get_games_played_count(user_id),
        games_won: await db.get_games_won_count(user_id),
        total_won: await db.get_total_won(user_id),
        invited: await db.get_referral_count(user_id),
        is_vip: is_vip === 1
    });
});

app.get('/api/game_history', async (req, res) => {
    const user_id = parseInt(req.query.user_id);
    if (!user_id || !await db.user_exists(user_id)) return res.status(404).json({ success: false, error: 'User not found' });
    const rows = await db.get_game_history(user_id, 20);
    const history = rows.map(r => ({ game_id: r[0], entry: r[1], status: r[2], result: r[3], time: r[4] }));
    res.json({ success: true, history });
});

app.get('/api/transactions', async (req, res) => {
    const user_id = parseInt(req.query.user_id);
    if (!user_id || !await db.user_exists(user_id)) return res.status(404).json({ success: false, error: 'User not found' });
    const rows = await db.get_all_transactions(user_id, 20);
    const txs = rows.map(r => ({ type: r[0], amount: r[1], status: r[2], time: r[3] }));
    res.json({ success: true, transactions: txs });
});

app.get('/api/top_winners', async (req, res) => {
    const period = req.query.period || 'week';
    const category = req.query.category || 'deposit';
    let rows;
    if (category === 'deposit') rows = await db.get_top_by_deposit(period, 30);
    else if (category === 'invite') rows = await db.get_top_by_invitations(period, 30);
    else if (category === 'wins') rows = await db.get_top_by_wins(period, 30);
    else rows = await db.get_top_by_games(period, 30);
    
    const winners = rows.map(r => ({ name: r[1] && r[1].trim() ? r[1] : 'User', value: r[2] }));
    res.json({ success: true, winners });
});

app.get('/api/my_rank', async (req, res) => {
    const user_id = parseInt(req.query.user_id);
    const period = req.query.period || 'week';
    const category = req.query.category || 'deposit';
    if (!user_id || !await db.user_exists(user_id)) return res.status(404).json({ success: false, error: 'User not found' });
    const [rank, value] = await db.get_user_rank(user_id, period, category);
    res.json({ success: true, rank, value });
});

// ══════════════════════════════════════════════════════════
// ADMIN EXPRESS ROUTES
// ══════════════════════════════════════════════════════════

app.get('/api/admin/dashboard', async (req, res) => {
    try {
        const stats = await db.get_dashboard_stats();
        stats.active_online = Object.values(game_states).reduce((s, g) => s + count_total_cards(g), 0);
        stats.running_games = Object.values(game_states).filter(g => g.running).length;
        stats.success = true;
        res.json(stats);
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.get('/api/admin/deposits', async (req, res) => {
    try {
        const deposits = await db.get_all_deposits();
        res.json({ success: true, deposits });
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post('/api/admin/approve_deposit', async (req, res) => {
    const { deposit_id } = req.body;
    const [success, user_id, amount] = await db.approve_deposit(deposit_id);
    res.json({ success });
});

app.post('/api/admin/reject_deposit', async (req, res) => {
    const { deposit_id } = req.body;
    const [success, user_id] = await db.reject_deposit(deposit_id);
    res.json({ success });
});

app.get('/api/admin/withdrawals', async (req, res) => {
    try {
        let withdrawals = await db.get_all_withdrawals();
        for (const [req_num, req] of Object.entries(withdraw_requests)) {
            withdrawals.push({
                id: req_num,
                user_id: req.user_id,
                username: '—',
                phone: req.phone || '—',
                amount: req.amount,
                method: req.method || 'Telebirr',
                status: 'pending',
                time: new Date().toISOString().replace('T', ' ').split('.')[0],
            });
        }
        res.json({ success: true, withdrawals });
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post('/api/admin/approve_withdrawal', async (req, res) => {
    const { withdrawal_id, user_id, amount } = req.body;
    await db.update_main_balance(user_id, -amount);
    await db.add_transaction(user_id, 'withdraw', amount);
    try {
        await bot.telegram.sendMessage(user_id, `✅ Withdrawal Approved!\n\n💰 Amount: ${amount} ETB\n🏦 The money has been sent to your account.`);
    } catch (e) {
        console.log(`Failed to send approval message to user ${user_id}: ${e.message}`);
    }
    if (withdraw_requests[withdrawal_id]) {
        delete withdraw_requests[withdrawal_id];
    } else {
        await db.approve_withdrawal(withdrawal_id);
    }
    res.json({ success: true });
});

app.post('/api/admin/reject_withdrawal', async (req, res) => {
    const { withdrawal_id, user_id, amount } = req.body;
    try {
        await bot.telegram.sendMessage(user_id, `❌ Withdrawal Rejected\n\n💰 Amount: ${amount} ETB\n⚠️ Your request was rejected by admin. The money remains in your Main Wallet.`);
    } catch (e) {
        console.log(`Failed to send rejection message to user ${user_id}: ${e.message}`);
    }
    if (withdraw_requests[withdrawal_id]) {
        delete withdraw_requests[withdrawal_id];
    } else {
        await db.reject_withdrawal(withdrawal_id);
    }
    res.json({ success: true });
});

app.get('/api/admin/users', async (req, res) => {
    try {
        const users = await db.get_all_users_with_stats();
        res.json({ success: true, users });
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post('/api/admin/add_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_main_balance(user_id, amount || 0);
    await db.add_transaction(user_id, 'admin_add', amount);
    res.json({ success: true, main_balance: new_bal, play_balance: await db.get_play_balance(user_id) });
});

app.post('/api/admin/remove_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_main_balance(user_id, -(amount || 0));
    await db.add_transaction(user_id, 'admin_remove', amount);
    res.json({ success: true, main_balance: new_bal, play_balance: await db.get_play_balance(user_id) });
});

app.post('/api/admin/add_main_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_main_balance(user_id, amount || 0);
    await db.add_transaction(user_id, 'admin_add_main', amount);
    res.json({ success: true, main_balance: new_bal, play_balance: await db.get_play_balance(user_id) });
});

app.post('/api/admin/add_play_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_play_balance(user_id, amount || 0);
    await db.add_transaction(user_id, 'admin_add_play', amount);
    res.json({ success: true, main_balance: await db.get_main_balance(user_id), play_balance: new_bal });
});

app.post('/api/admin/remove_main_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_main_balance(user_id, -(amount || 0));
    await db.add_transaction(user_id, 'admin_remove_main', amount);
    res.json({ success: true, main_balance: new_bal, play_balance: await db.get_play_balance(user_id) });
});

app.post('/api/admin/remove_play_balance', async (req, res) => {
    const { user_id, amount } = req.body;
    const new_bal = await db.update_play_balance(user_id, -(amount || 0));
    await db.add_transaction(user_id, 'admin_remove_play', amount);
    res.json({ success: true, main_balance: await db.get_main_balance(user_id), play_balance: new_bal });
});

app.post('/api/admin/ban_user', async (req, res) => {
    await db.ban_user(req.body.user_id);
    res.json({ success: true });
});

app.post('/api/admin/unban_user', async (req, res) => {
    await db.unban_user(req.body.user_id);
    res.json({ success: true });
});

app.post('/api/admin/freeze_user', async (req, res) => {
    await db.freeze_user(req.body.user_id);
    res.json({ success: true });
});

app.post('/api/admin/unfreeze_user', async (req, res) => {
    await db.unfreeze_user(req.body.user_id);
    res.json({ success: true });
});

app.post('/api/admin/mark_vip', async (req, res) => {
    await db.mark_vip(req.body.user_id, req.body.vip !== undefined ? req.body.vip : true);
    res.json({ success: true });
});

app.post('/api/admin/manual_call', (req, res) => {
    const { room, number } = req.body;
    const game = get_game_state(room || '10');
    if (!number || number < 1 || number > 75) return res.status(400).json({ success: false, error: 'Invalid number' });
    if (game.called.includes(number)) return res.status(400).json({ success: false, error: 'Already called' });
    game.called.push(number);
    game.current = number;
    io.to(`bingo_room_${room}`).emit('ball_called', { room, number, manual: true });
    res.json({ success: true, number, room });
});

app.post('/api/admin/set_max_winners', (req, res) => {
    const { room, max_winners } = req.body;
    const game = get_game_state(room || '10');
    const mx = Math.max(1, Math.min(4, parseInt(max_winners || 1)));
    game.max_winners = mx;
    io.to(`bingo_room_${room}`).emit('max_winners_updated', { room, max: mx });
    res.json({ success: true, max_winners: mx, room });
});

app.post('/api/admin/pause_game', (req, res) => {
    const { room } = req.body;
    const game = get_game_state(room || '10');
    game.paused = !game.paused;
    io.to(`bingo_room_${room}`).emit('game_paused', { room, paused: game.paused });
    res.json({ success: true, paused: game.paused, room });
});

app.post('/api/admin/cancel_game', (req, res) => {
    const { room } = req.body;
    game_states[room || '10'] = default_game_state();
    game_states[room || '10'].timer_started_at = Math.floor(Date.now() / 1000);
    io.to(`bingo_room_${room}`).emit('game_cancelled', { room, reason: 'admin_cancelled' });
    res.json({ success: true, room });
});

app.get('/api/admin/rankings', async (req, res) => {
    const category = req.query.category || 'deposit';
    const period = req.query.period || 'week';
    const limit = parseInt(req.query.limit || 30);
    let rows;
    if (category === 'deposit') rows = await db.get_top_by_deposit(period, limit);
    else if (category === 'invite') rows = await db.get_top_by_invitations(period, limit);
    else if (category === 'wins') rows = await db.get_top_by_wins(period, limit);
    else rows = await db.get_top_by_games(period, limit);
    
    const rankings = [];
    for (const r of rows) {
        const phone = await db.get_user_phone(r[0]) || '—';
        rankings.push({ user_id: r[0], name: r[1] || 'User', phone, value: r[2] });
    }
    res.json({ success: true, rankings });
});

app.get('/api/admin/game_history', async (req, res) => {
    try {
        const games = await db.get_admin_game_history();
        res.json({ success: true, games });
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.get('/api/admin/reports', async (req, res) => {
    const period = req.query.period || 'daily';
    try {
        const rows = await db.get_admin_reports(period);
        res.json({ success: true, rows });
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

app.post('/api/admin/settings', (req, res) => {
    const data = req.body;
    console.log(`⚙️ Settings updated by ${data.admin || 'admin'}:`, data);
    res.json({ success: true });
});


function autoCallLoop() {
    const CALL_INTERVAL = 2000;
    setInterval(() => {
        const roomIds = Object.keys(game_states);
        for (const room_id of roomIds) {
            const game = game_states[room_id];
            if (!game) continue;

            if (!game.running && game.timer_started_at && !game.winner_declared) {
                const elapsed = Math.floor(Date.now() / 1000 - game.timer_started_at);
                if (elapsed >= 35) {
                    game.running = true;
                    game.started_at = Math.floor(Date.now() / 1000);
                    game.timer_started_at = null;
                    game.winner_declared = false;
                    game.winner_count = 0;
                    io.to(`bingo_room_${room_id}`).emit('game_started', {
                        room: room_id,
                        game_id: game.game_id || '',
                        total_players: count_total_cards(game)
                    });
                }
            }

            if (game.running && !game.paused && !game.winner_declared) {
                if (game.called.length >= 75) continue;

                const available = [];
                for (let n = 1; n <= 75; n++) {
                    if (!game.called.includes(n)) available.push(n);
                }
                if (available.length === 0) continue;

                const number = available[Math.floor(Math.random() * available.length)];

                const current_game = game_states[room_id];
                if (!current_game || !current_game.running) continue;

                current_game.called.push(number);
                current_game.current = number;

                io.to(`bingo_room_${room_id}`).emit('ball_called', {
                    room: room_id,
                    number: number
                });
            }
        }
    }, CALL_INTERVAL);
}

// ==========================
// START EVERYTHING
// ==========================
async function startServer() {
    try {
        await mongoose.connect(process.env.MONGO_URI || "mongodb+srv://placeholder:placeholder@cluster.mongodb.net/adwa_bingo?retryWrites=true&w=majority");
        console.log("✅ Connected to MongoDB Cloud Database!");

        server.listen(5000, '0.0.0.0', () => {
            console.log('✅ API & SocketIO running on port 5000');
        });

        autoCallLoop();

        console.log("✅ Bot is running with Multi-Room SocketIO + Auto-Caller + MongoDB Cloud...");
        bot.launch();

    } catch (err) {
        console.error("Failed to start server:", err);
    }
}

startServer();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
