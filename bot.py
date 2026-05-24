from telegram import ReplyKeyboardMarkup, KeyboardButton, Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import time as time_module
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
import re
import db

from db import (
    add_user,
    update_user_name,
    user_exists,
    get_user,
    get_user_name,
    set_referral,
    get_main_balance,
    get_play_balance,
    update_main_balance,
    update_play_balance,
    deduct_bet_smart,
    add_transaction,
    get_last_5_transactions,
    get_all_transactions,
    get_total_deposits,
    get_referral_count,
    is_user_agent,
    check_and_upgrade_agent,
    get_depositing_referrals_count,
    get_total_referral_deposits,
    get_user_by_phone,
    transaction_exists,
    get_user_language,
    set_user_language,
    add_game_session,
    complete_game_session,
    get_game_history,
    get_games_played_count,
    get_games_won_count,
    get_total_won,
    get_top_by_deposit,
    get_top_by_invitations,
    get_top_by_games,
    get_top_by_wins,
    get_user_rank,
    get_user_phone,
    get_dashboard_stats,
    get_all_deposits,
    approve_deposit,
    reject_deposit,
    get_all_withdrawals,
    approve_withdrawal,
    reject_withdrawal,
    get_all_users_with_stats,
    ban_user,
    unban_user,
    mark_vip,
    get_admin_game_history,
    get_admin_reports,
    freeze_user,
    unfreeze_user,
)

# --------------------------
# CONFIG
# --------------------------
TOKEN = "8607291518:AAG1IFDDL4CrB8puYNkG8ZWbOTxOl8uK6xo"
BOT_USERNAME = "adwabingiobot"
ADMIN_IDS = [7627811244, 1119881250]
MINI_APP_URL = "https://sebez733-png.github.io/bingio-mini-app/"

ADMIN_CREDENTIALS = {
    'superadmin': {'password': 'admin123', 'role': 'super'},
    'admin1':     {'password': 'pass123',  'role': 'regular'},
}

# --------------------------
# TELEBIRR SMS VERIFICATION
# --------------------------
MERCHANT_PHONE = "0998480054"

def get_merchant_phone_partials():
    """
    Returns all possible masked formats Telebirr uses for 0998480054:
    - Local format:       0998****54
    - International fmt:  2519****0054
    """
    p = MERCHANT_PHONE  # 0998480054
    local_partial = p[:4] + "****" + p[-2:]           # 0998****54
    intl = "251" + p[1:]                               # 251998480054
    intl_partial = intl[:4] + "****" + intl[-4:]       # 2519****0054
    return [local_partial, intl_partial]

def _is_transaction_used(transaction_id: str) -> bool:
    """Check if telebirr transaction ID was already used — uses MongoDB."""
    from db import db as mongo_db
    return mongo_db["telebirr_transactions"].find_one({"transaction_id": transaction_id}) is not None

def _mark_transaction_used(transaction_id: str, user_id: int, amount: float):
    """Save telebirr transaction ID to prevent reuse — uses MongoDB."""
    from db import db as mongo_db
    from datetime import datetime
    mongo_db["telebirr_transactions"].update_one(
        {"transaction_id": transaction_id},
        {"$setOnInsert": {"transaction_id": transaction_id, "user_id": user_id, "amount": amount, "created_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}},
        upsert=True
    )

def verify_telebirr_sms(sms_text: str, expected_amount: int) -> dict:
    sms_text = sms_text.strip()

    # Must be a real Telebirr transfer SMS
    if "transferred ETB" not in sms_text:
        return {
            'valid': False,
            'reason': (
                "❌ SMS format not recognized.\n\n"
                "Please paste the *exact* SMS you received from Telebirr after sending money.\n\n"
                "Example:\n"
                "_Dear Habtamu You have transferred ETB 100.00 to ..._"
            )
        }

    # Extract amount
    amount_match = re.search(r'transferred ETB\s*([\d,]+\.?\d*)', sms_text)
    if not amount_match:
        return {'valid': False, 'reason': "❌ Could not read amount from SMS. Please paste the full SMS."}
    amount = float(amount_match.group(1).replace(',', ''))

    # Extract transaction ID
    txn_match = re.search(r'transaction number is\s*([A-Z0-9]+)', sms_text)
    if not txn_match:
        return {'valid': False, 'reason': "❌ Could not find transaction number in SMS. Please paste the full SMS."}
    transaction_id = txn_match.group(1).strip()

    # Extract receiver partial phone — handles both formats:
    # (0998****54) and (2519****0054)
    phone_match = re.search(r'\((\d{4}\*+\d{2,4})\)', sms_text)
    if phone_match:
        receiver_partial = phone_match.group(1)
        allowed_partials = get_merchant_phone_partials()
        if receiver_partial not in allowed_partials:
            return {
                'valid': False,
                'reason': (
                    f"❌ Wrong recipient!\n\n"
                    f"Money was not sent to our account.\n"
                    f"Please send to: `{MERCHANT_PHONE}`"
                )
            }

    # Extract date and time
    date_match = re.search(r'on\s*(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2}:\d{2})', sms_text)
    date_str = date_match.group(1) if date_match else ''
    time_str = date_match.group(2) if date_match else ''

    # Check amount matches (allow ±1 ETB tolerance)
    if abs(amount - expected_amount) > 1:
        return {
            'valid': False,
            'reason': (
                f"❌ Amount mismatch!\n\n"
                f"You said you'd send *{expected_amount} ETB* "
                f"but SMS shows *{amount:.2f} ETB*.\n\n"
                f"Please make sure you send the exact amount."
            )
        }

    # Check transaction not already used
    if _is_transaction_used(transaction_id):
        return {
            'valid': False,
            'reason': (
                f"❌ Transaction already used!\n\n"
                f"Transaction `{transaction_id}` was already submitted.\n"
                f"Each SMS can only be used once."
            )
        }

    return {
        'valid': True,
        'reason': 'OK',
        'transaction_id': transaction_id,
        'amount': amount,
        'date': date_str,
        'time': time_str,
    }

# --------------------------
# STATE & COUNTERS
# --------------------------
user_state = {}
request_counter = 0
withdraw_requests = {}

# --------------------------
# SHARED GAME STATE
# --------------------------
game_state = {
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
}

# --------------------------
# TRANSLATION DICTIONARY
# --------------------------
TEXTS = {
    'select_language': {
        'am': "👇 ቋንቋ ይምረጡ / Please select your language",
        'en': "👇 Please select your language"
    },
    'welcome_new': {
        'am': (
            "🎉 እንኳን ወደ አድዋ Bingo በደህና መጡ!\n\n"
            "1️⃣ ከታች ያለውን \"📱 ስልክ ቁጥር ያጋሩ\" ይጫኑ\n"
            "2️⃣ ስልክ ቁጥርዎን ያረጋግጡ\n"
            "3️⃣ ከዚያ በኋላ መጫወት ይጀምሩ! 🚀\n\n"
            "👇 ለመጀመር ስልክ ቁጥርዎን ያጋሩ"
        ),
        'en': (
            "🎉 Welcome to our Adwa Bingo Game!\n\n"
            "1️⃣ Click the button below to share your phone number\n"
            "2️⃣ Verify your number\n"
            "3️⃣ Start playing! 🚀\n\n"
            "👇 Share your phone number to begin:"
        )
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
        'am': (
            "⚠️ እርስዎ ቀድሞ ተመዝግበዋል!\n\n"
            "📱 ስልክ: {phone}\n\n"
            "💰 Main Wallet: {main} ETB\n"
            "🎮 Play Wallet: {play} ETB\n"
            "👥 Referrals: {ref_count}\n\n"
            "👇 Choose an option below:"
        ),
        'en': (
            "⚠️ You are already registered!\n\n"
            "📱 Phone: {phone}\n\n"
            "💰 Main Wallet: {main} ETB\n"
            "🎮 Play Wallet: {play} ETB\n"
            "👥 Referrals: {ref_count}\n\n"
            "👇 Choose an option below:"
        )
    },
    'register_success': {
        'am': (
            "🎉 እንኳን ወደ አድዋ Bingo ቤተሰብ በደህና መጡ!\n\n"
            "✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል!\n\n"
            "📱 ስልክ ቁጥር: {phone}\n\n"
            "💰 Main Wallet: {main} ETB\n"
            "🎮 Play Wallet: {play} ETB\n\n"
            "🎯 አሁን መጫወት ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ!\n"
            "🍀 መልካም እድል!"
        ),
        'en': (
            "🎉 Welcome to the Adwa Bingo Family!\n\n"
            "✅ Registration successful!\n\n"
            "📱 Phone: {phone}\n\n"
            "💰 Main Wallet: {main} ETB\n"
            "🎮 Play Wallet: {play} ETB\n\n"
            "🎯 Click the menu below to start playing!\n"
            "🍀 Good luck!"
        )
    },
    'deposit_prompt': {
        'am': "💳 ምን ያህል ማስገባት ይፈልጋሉ?\n(Enter amount)\n\nMin / ዝቅተኛ: 10 ብር / Birr",
        'en': "💳 How much would you like to deposit?\n(Enter amount)\n\nMin: 10 Birr"
    },
    'withdraw_prompt': {
        'am': (
            "🐝 ማውጣት የሚፈልጉትን መጠን ይፃፉ (ETB):\n\n"
            "🎮 Play Wallet: {play_bal} ETB\n"
            "💰 Main Wallet: {main_bal} ETB\n\n"
            "Min / ዝቅተኛ: 100 ብር"
        ),
        'en': (
            "🐝 Enter withdrawal amount (ETB):\n\n"
            "🎮 Play Wallet: {play_bal} ETB\n"
            "💰 Main Wallet: {main_bal} ETB\n\n"
            "Min: 100 Birr"
        )
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
        'am': (
            "✅ Deposit Successful\n\n"
            "💰 Method: {method}\n"
            "💰 Sent: {amount}\n"
            "🎁 Bonus: {bonus}\n"
            "📈 Total Added: {total}\n"
            "💰 New Balance: {new_balance} ETB"
        ),
        'en': (
            "✅ Deposit Successful\n\n"
            "💰 Method: {method}\n"
            "💰 Sent: {amount}\n"
            "🎁 Bonus: {bonus}\n"
            "📈 Total Added: {total}\n"
            "💰 New Balance: {new_balance} ETB"
        )
    },
    'lang_changed': {
        'am': "✅ ቋንቋ ወደ አማርኛ ተቀይሯል!",
        'en': "✅ Language changed to English!"
    }
}


def t(key, lang='am', **kwargs):
    text = TEXTS.get(key, {}).get(lang, TEXTS.get(key, {}).get('am', key))
    if kwargs:
        text = text.format(**kwargs)
    return text


# --------------------------
# HELPER: Normalize Phone
# --------------------------
def normalize_phone(phone):
    phone = phone.replace(" ", "").replace("+", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("251"):
        phone = "0" + phone[3:]
    if not phone.startswith("0") and len(phone) == 9:
        phone = "0" + phone
    return phone


# --------------------------
# HELPER: Get Main Menu
# --------------------------
def get_main_menu(lang='am'):
    if lang == 'en':
        return ReplyKeyboardMarkup([
            ["🎮 Open Game"],
            ["💳 Deposit", "💰 Balance"],
            ["🐝 Withdraw", "📜 History"],
            ["👤 Profile", "🏢 Support"],
            ["🎁 Invite Friends", "🤖 Agent Panel"],
            ["🔄 Transfer", "ℹ️ Info"]
        ], resize_keyboard=True)
    else:
        return ReplyKeyboardMarkup([
            ["🎮 Open Game / ይጫወቱ"],
            ["💳 Deposit / ያስገቡ", "💰 Balance / ሂሳብ"],
            ["🐝 Withdraw / ያውጡ", "📜 History / ታሪክ"],
            ["👤 Profile / መገለጫ", "🏢 Support / ድጋፍ"],
            ["🎁 Invite Friends / ጓደኛ ይጋብዙ", "🤖 Agent Panel"],
            ["🔄 Transfer / ይላኩ", "ℹ️ Info / መረጃ"]
        ], resize_keyboard=True)


# --------------------------
# HELPER: Get Inline Menu
# --------------------------
def get_inline_menu(lang='am'):
    if lang == 'en':
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Open Game", web_app=WebAppInfo(url=MINI_APP_URL))],
            [
                InlineKeyboardButton("💳 Deposit", callback_data="menu_deposit"),
                InlineKeyboardButton("💰 Balance", callback_data="menu_balance")
            ],
            [
                InlineKeyboardButton("🐝 Withdraw", callback_data="menu_withdraw"),
                InlineKeyboardButton("📜 History", callback_data="menu_history")
            ],
            [
                InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
                InlineKeyboardButton("🏢 Support", callback_data="menu_support")
            ],
            [
                InlineKeyboardButton("🎁 Invite Friends", callback_data="menu_invite"),
                InlineKeyboardButton("🤖 Agent Panel", callback_data="menu_agent")
            ],
            [
                InlineKeyboardButton("🔄 Transfer", callback_data="menu_transfer"),
                InlineKeyboardButton("ℹ️ Info", callback_data="menu_info")
            ]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Open Game / ይጫወቱ", web_app=WebAppInfo(url=MINI_APP_URL))],
            [
                InlineKeyboardButton("💳 Deposit / ያስገቡ", callback_data="menu_deposit"),
                InlineKeyboardButton("💰 Balance / ሂሳብ", callback_data="menu_balance")
            ],
            [
                InlineKeyboardButton("🐝 Withdraw / ያውጡ", callback_data="menu_withdraw"),
                InlineKeyboardButton("📜 History / ታሪክ", callback_data="menu_history")
            ],
            [
                InlineKeyboardButton("👤 Profile / መገለጫ", callback_data="menu_profile"),
                InlineKeyboardButton("🏢 Support / ድጋፍ", callback_data="menu_support")
            ],
            [
                InlineKeyboardButton("🎁 Invite Friends / ጓደኛ ይጋብዙ", callback_data="menu_invite"),
                InlineKeyboardButton("🤖 Agent Panel", callback_data="menu_agent")
            ],
            [
                InlineKeyboardButton("🔄 Transfer / ይላኩ", callback_data="menu_transfer"),
                InlineKeyboardButton("ℹ️ Info / መረጃ", callback_data="menu_info")
            ]
        ])


# --------------------------
# START
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or ''
    ref_id = context.args[0] if context.args else None
    context.user_data["ref_by"] = ref_id

    if user_exists(user_id):
        lang = get_user_language(user_id)
        update_user_name(user_id, first_name)
        menu = get_main_menu(lang)
        await update.message.reply_text(t('welcome_back', lang), reply_markup=menu)
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am"),
            InlineKeyboardButton("🇸🇸 English", callback_data="lang_en")
        ]
    ])
    await update.message.reply_text(t('select_language'), reply_markup=keyboard)


# --------------------------
# CONTACT REGISTER
# --------------------------
async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or ''
    phone = normalize_phone(update.message.contact.phone_number)
    lang = context.user_data.get("lang", 'am')

    if user_exists(user_id):
        lang = get_user_language(user_id)
        user = get_user(user_id)
        main = get_main_balance(user_id)
        play = get_play_balance(user_id)
        ref_count = get_referral_count(user_id)
        text = t('already_registered', lang, phone=user[1], main=main, play=play, ref_count=ref_count)
        await update.message.reply_text(text, reply_markup=get_inline_menu(lang))
        await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))
        return

    ref_by = context.user_data.get("ref_by")
    add_user(user_id, phone, first_name)
    set_user_language(user_id, lang)

    if ref_by:
        set_referral(user_id, ref_by)

    main = get_main_balance(user_id)
    play = get_play_balance(user_id)
    text = t('register_success', lang, phone=phone, main=main, play=play)

    await update.message.reply_text(text, reply_markup=get_inline_menu(lang))
    await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))


# --------------------------
# TEXT HANDLER
# --------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_text=None):
    global request_counter
    user_id = update.effective_user.id
    text = custom_text if custom_text is not None else update.message.text

    first_name = update.effective_user.first_name or ''
    if first_name and user_exists(user_id):
        update_user_name(user_id, first_name)

    if user_exists(user_id):
        lang = get_user_language(user_id)
    else:
        lang = context.user_data.get("lang", 'am')

    main_menu_buttons_am = [
        "🎮 Open Game / ይጫወቱ",
        "💳 Deposit / ያስገቡ", "💰 Balance / ሂሳብ",
        "🐝 Withdraw / ያውጡ", "📜 History / ታሪክ",
        "👤 Profile / መገለጫ", "🏢 Support / ድጋፍ",
        "🎁 Invite Friends / ጓደኛ ይጋብዙ", "🤖 Agent Panel",
        "🔄 Transfer / ይላኩ", "ℹ️ Info / መረጃ"
    ]
    main_menu_buttons_en = [
        "🎮 Open Game",
        "💳 Deposit", "💰 Balance",
        "🐝 Withdraw", "📜 History",
        "👤 Profile", "🏢 Support",
        "🎁 Invite Friends", "🤖 Agent Panel",
        "🔄 Transfer", "ℹ️ Info"
    ]

    if text in main_menu_buttons_am or text in main_menu_buttons_en:
        user_state.pop(user_id, None)
        user_state.pop(f"{user_id}_amount", None)
        user_state.pop(f"{user_id}_withdraw_amount", None)
        user_state.pop(f"{user_id}_method", None)
        user_state.pop(f"{user_id}_transfer_wallet", None)
        user_state.pop(f"{user_id}_transfer_target", None)

    if text in ["🎮 Open Game / ይጫወቱ", "🎮 Open Game"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Play Bingo Now", web_app=WebAppInfo(url=MINI_APP_URL))]
        ])
        game_msg = "🎮 Tap the button below to open the Bingo Game:" if lang == 'en' else "🎮 የቢንጎ ጨዋታውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ:"
        await update.message.reply_text(game_msg, reply_markup=keyboard)
        return

    if text in ["💰 Balance / ሂሳብ", "💰 Balance"]:
        main = get_main_balance(user_id)
        play = get_play_balance(user_id)
        await update.message.reply_text(t('balance_msg', lang, main=main, play=play))
        return

    if text in ["🏢 Support / ድጋፍ", "🏢 Support"]:
        if lang == 'en':
            support_msg = (
                "☎️ Support\n\n"
                "For any comments or questions, contact support:\n"
                "@thelastking12312345678\n"
                "@Silencedoeir\n"
                "@one_day_82"
            )
        else:
            support_msg = (
                "☎️ Support (ድጋፍ)\n\n"
                "For any comment and question, contact support:\n"
                "@thelastking12312345678\n"
                "@Silencedoeir\n"
                "@one_day_82"
            )
        await update.message.reply_text(support_msg)
        return

    if text in ["📜 History / ታሪክ", "📜 History"]:
        history = get_last_5_transactions(user_id)
        if not history:
            no_hist = "📜 ግብይት አልተደረገም / No transactions yet." if lang == 'am' else "📜 No transactions yet."
            await update.message.reply_text(no_hist)
            return
        msg = "📜 LAST 5 TRANSACTIONS\n\n"
        for tx in history:
            tx_type, amount, time_str = tx
            icon = "🟢 Deposit" if tx_type == "deposit" else "🔴 Withdraw"
            clean_time = time_str.split('.')[0]
            msg += f"{icon}\n💰 Amount: {amount} ETB\n⏰ Date: {clean_time}\n\n"
        await update.message.reply_text(msg)
        return

    if text in ["👤 Profile / መገለጫ", "👤 Profile"]:
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("❌ User not found")
            return
        link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ref_count = get_referral_count(user_id)
        played = get_games_played_count(user_id)
        won = get_games_won_count(user_id)
        total_won = get_total_won(user_id)
        profile_msg = (
            "👤 PROFILE\n\n"
            f"🆔 ID: {user[0]}\n"
            f"📱 Phone: {user[1]}\n\n"
            f"💰 Main Wallet: {user[2]} ETB\n"
            f"🎮 Play Wallet: {user[3]} ETB\n\n"
            f"🎯 Games Played: {played}\n"
            f"🏆 Games Won: {won}\n"
            f"💵 Total Won: {total_won} ETB\n\n"
            f"👥 Referrals: {ref_count}\n"
            f"🎯 Invited By: {user[4] if len(user) > 4 and user[4] else 'No inviter'}\n\n"
            f"🎁 Invite Link:\n{link}"
        )
        await update.message.reply_text(profile_msg)
        return

    if text in ["🎁 Invite Friends / ጓደኛ ይጋብዙ", "🎁 Invite Friends"]:
        link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ref_count = get_referral_count(user_id)
        invite_msg = (
            "🎁 Invite Friends System\n\n"
            f"👥 Your Invites: {ref_count}\n\n"
            f"🔗 Your Referral Link:\n{link}\n\n"
            "💰 Earn 10% commission from every deposit made by your referrals!"
        )
        await update.message.reply_text(invite_msg)
        return

    if text == "🤖 Agent Panel":
        invites = get_referral_count(user_id)
        depositors = get_depositing_referrals_count(user_id)
        total_deposits = get_total_referral_deposits(user_id)
        if is_user_agent(user_id):
            agent_msg = (
                "🤖 AGENT DASHBOARD\n\n"
                "⭐ Status: Official Agent\n\n"
                f"👥 Total Invites: {invites}\n"
                f"💳 Depositing Referrals: {depositors}\n"
                f"💰 Total Referral Deposits: {total_deposits} ETB\n\n"
                "🎁 Commission Rate: 10% CASH (Main Wallet)\n\n"
                "🚀 Keep inviting more friends to earn more real cash!"
            )
        else:
            agent_msg = (
                "🤖 AGENT UPGRADE PROGRAM\n\n"
                "⭐ Status: Normal User (10% Play Wallet)\n\n"
                "🎯 To become an Agent and earn 10% CASH (Main Wallet), you must achieve:\n\n"
                f"1️⃣ 30+ Invites\nProgress: {invites}/30\n\n"
                f"2️⃣ 20+ Depositing Referrals\nProgress: {depositors}/20\n\n"
                f"3️⃣ 3000+ ETB Total Referral Deposits\nProgress: {total_deposits}/3000 ETB\n\n"
                "💪 Keep sharing your referral link to hit these goals!"
            )
        await update.message.reply_text(agent_msg)
        return

    if text in ["ℹ️ Info / መረጃ", "ℹ️ Info"]:
        await info(update, context, lang=lang)
        return

    if text in ["💳 Deposit / ያስገቡ", "💳 Deposit"]:
        user_state[user_id] = "deposit_amount"
        await update.message.reply_text(t('deposit_prompt', lang))
        return

    if text in ["🐝 Withdraw / ያውጡ", "🐝 Withdraw"]:
        total_lifetime_deposits = get_total_deposits(user_id)
        if total_lifetime_deposits < 50:
            await update.message.reply_text(t('withdraw_locked', lang))
            return
        user_state[user_id] = "withdraw_amount"
        play_bal = get_play_balance(user_id)
        main_bal = get_main_balance(user_id)
        await update.message.reply_text(t('withdraw_prompt', lang, play_bal=play_bal, main_bal=main_bal))
        return

    if user_state.get(user_id) == "deposit_amount":
        if not text.isdigit():
            err_msg = "❌ ቁጥር ብቻ ያስገቡ" if lang == 'am' else "❌ Please enter a valid number"
            await update.message.reply_text(err_msg)
            return
        amount = int(text)
        if amount < 10:
            err_msg = "❌ ዝቅተኛ መጠን 10 ብር ነው" if lang == 'am' else "❌ Minimum amount is 10 Birr"
            await update.message.reply_text(err_msg)
            return
        user_state[user_id] = "deposit_method"
        user_state[f"{user_id}_amount"] = amount
        keyboard = ReplyKeyboardMarkup(
            [["Telebirr"], ["🔙 Back"]],
            resize_keyboard=True
        )
        method_msg = "💳 Select Payment Method:" if lang == 'en' else "💳 የክፍያ ዘዴ ይምረጡ:"
        await update.message.reply_text(method_msg, reply_markup=keyboard)
        return

    if user_state.get(user_id) == "withdraw_amount":
        if not text.isdigit():
            err_msg = "❌ ቁጥር ብቻ ያስገቡ" if lang == 'am' else "❌ Please enter a valid number"
            await update.message.reply_text(err_msg)
            return
        amount = int(text)
        balance = get_main_balance(user_id)
        if amount > balance:
            bal_msg = f"❌ በቂ ሂሳብ የለም (Main Wallet)\n💰 ያለዎት: {balance} ETB" if lang == 'am' else f"❌ Insufficient balance (Main Wallet)\n💰 You have: {balance} ETB"
            await update.message.reply_text(bal_msg)
            return
        if amount < 100:
            err_msg = "❌ ዝቅተኛ መጠን 100 ብር ነው" if lang == 'am' else "❌ Minimum amount is 100 Birr"
            await update.message.reply_text(err_msg)
            return
        user_state[user_id] = "withdraw_method"
        user_state[f"{user_id}_withdraw_amount"] = amount
        keyboard = ReplyKeyboardMarkup(
            [["Telebirr"], ["🔙 Back"]],
            resize_keyboard=True
        )
        w_method_msg = "🏦 Select Withdraw Method:" if lang == 'en' else "🏦 የመውጣት ዘዴ ይምረጡ:"
        await update.message.reply_text(w_method_msg, reply_markup=keyboard)
        return

    if user_state.get(user_id) == "deposit_method":
        if text == "🔙 Back":
            await update.message.reply_text("👇 Main Menu", reply_markup=get_inline_menu(lang))
            await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))
            user_state.pop(user_id, None)
            user_state.pop(f"{user_id}_amount", None)
            return
        if text == "Telebirr":
            method = "Telebirr"
            phone = "0998480054"
            app_name_am = "ቴሌብር"
        else:
            err_msg = "❌ Please choose Telebirr" if lang == 'en' else "❌ ቴሌብር ይምረጡ"
            await update.message.reply_text(err_msg)
            return
        amount = user_state.get(f"{user_id}_amount", 0)
        user_state[user_id] = "deposit_confirm"
        user_state[f"{user_id}_method"] = method
        if lang == 'en':
            pay_msg = (
                f"💳 Payment Instructions\n\n"
                f"Send *{amount} Birr* to:\n\n"
                f"🏦 Method: {method}\n"
                f"📱 Phone:\n`{phone}`\n\n"
                f"ℹ️ After sending the money, copy the entire confirmation SMS from Telebirr and paste it here 👇"
            )
        else:
            pay_msg = (
                f"💳 የክፍያ መመሪያ\n\n"
                f"ወደዚህ *{amount} ብር* ይላኩ\n\n"
                f"🏦 የክፍያ መንገድ: {method}\n"
                f"📱 ስልክ ቁጥር:\n`{phone}`\n\n"
                f"ℹ️ ገንዘቡን ከላኩ በኋላ ከ{app_name_am} የተላከልዎትን ሙሉውን የማረጋገጫ SMS ኮፒ አድርገው እዚህ ላይ ፔስት አድርገው ይላኩ 👇"
            )
        await update.message.reply_text(pay_msg, parse_mode="Markdown")
        return

    if user_state.get(user_id) == "withdraw_method":
        if text == "🔙 Back":
            await update.message.reply_text("👇 Main Menu", reply_markup=get_inline_menu(lang))
            await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))
            user_state.pop(user_id, None)
            user_state.pop(f"{user_id}_withdraw_amount", None)
            return
        if text == "Telebirr":
            method = "Telebirr"
        else:
            await update.message.reply_text("❌ Please choose Telebirr")
            return
        amount = user_state.get(f"{user_id}_withdraw_amount", 0)
        user = get_user(user_id)
        user_phone = user[1] if user else "N/A"
        user_state.pop(user_id, None)
        user_state.pop(f"{user_id}_withdraw_amount", None)
        await update.message.reply_text("⏳ Withdraw request sent to admin", reply_markup=get_main_menu(lang))
        request_counter += 1
        req_num = request_counter
        withdraw_requests[req_num] = {
            "user_id": user_id,
            "amount": amount,
            "method": method,
            "phone": user_phone
        }
        admin_msg = (
            f"🚨 WITHDRAW REQUEST #{req_num}\n\n"
            f"👤 User ID: {user_id}\n"
            f"📱 Phone: {user_phone}\n\n"
            f"💰 Amount: {amount} ETB\n"
            f"🏦 Method: {method}\n\n"
            f"✅ To Approve send:\n/ap {req_num}\n\n"
            f"❌ To Reject send:\n/re {req_num}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_msg)
            except:
                pass
        return

    # ══════════════════════════════════════════
    # ✅ DEPOSIT CONFIRM — SMS VERIFICATION
    # ══════════════════════════════════════════
    if user_state.get(user_id) == "deposit_confirm":
        amount = user_state.get(f"{user_id}_amount", 0)
        method = user_state.get(f"{user_id}_method", "Unknown")

        # ── Back button ──
        if text == "🔙 Back":
            user_state[user_id] = "deposit_method"
            keyboard = ReplyKeyboardMarkup(
                [["Telebirr"], ["🔙 Back"]],
                resize_keyboard=True
            )
            method_msg = "💳 Select Payment Method:" if lang == 'en' else "💳 የክፍያ ዘዴ ይምረጡ:"
            await update.message.reply_text(method_msg, reply_markup=keyboard)
            return

        # Verify the SMS
        result = verify_telebirr_sms(sms_text=text, expected_amount=amount)

        if not result['valid']:
            # Keep state so user can try again
            await update.message.reply_text(result['reason'], parse_mode="Markdown")
            return

        # SMS is valid — credit the wallet
        transaction_id = result['transaction_id']
        confirmed_amount = int(result['amount'])
        bonus = int(confirmed_amount * 0.10)
        total = confirmed_amount + bonus

        # Save transaction ID to prevent reuse
        _mark_transaction_used(transaction_id, user_id, confirmed_amount)

        # Credit play wallet
        update_play_balance(user_id, total)
        add_transaction(user_id, "deposit", total)
        new_balance = get_play_balance(user_id)

        # Referral bonus
        user = get_user(user_id)
        ref_by = user[4] if user and len(user) > 4 else None
        if ref_by:
            if is_user_agent(int(ref_by)):
                ref_bonus = int(confirmed_amount * 0.10)
                update_main_balance(int(ref_by), ref_bonus)
                try:
                    await context.bot.send_message(
                        chat_id=int(ref_by),
                        text=(
                            "🤝 Agent Cash Commission!\n\n"
                            f"👤 Your referral deposited: {confirmed_amount} ETB\n"
                            f"💰 You earned: {ref_bonus} ETB (10% Cash)\n\n"
                            "💸 Added to your Main Wallet!"
                        )
                    )
                except:
                    pass
            else:
                ref_bonus = int(confirmed_amount * 0.10)
                update_play_balance(int(ref_by), ref_bonus)
                try:
                    await context.bot.send_message(
                        chat_id=int(ref_by),
                        text=(
                            "🎉 Referral Deposit Bonus!\n\n"
                            f"👤 Your referral deposited: {confirmed_amount} ETB\n"
                            f"💰 You earned: {ref_bonus} ETB (10%)\n\n"
                            "🙏 Keep inviting more friends!"
                        )
                    )
                except:
                    pass
            if check_and_upgrade_agent(int(ref_by)):
                try:
                    await context.bot.send_message(
                        chat_id=int(ref_by),
                        text=(
                            "🎉 Congratulations! You are now an Official Agent! 🤝\n\n"
                            "✅ 30+ Invites\n✅ 20+ Referral Deposits\n✅ 3000+ ETB Total\n\n"
                            "🎁 From now on you earn 10% CASH to Main Wallet!"
                        )
                    )
                except:
                    pass

        # Clear state
        user_state.pop(user_id, None)
        user_state.pop(f"{user_id}_amount", None)
        user_state.pop(f"{user_id}_method", None)

        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"✅ DEPOSIT VERIFIED\n\n"
                        f"👤 User ID: {user_id}\n"
                        f"💰 Amount: {confirmed_amount} ETB\n"
                        f"🎁 Bonus: {bonus} ETB\n"
                        f"📈 Total: {total} ETB\n"
                        f"🔖 TXN: {transaction_id}\n"
                        f"📅 {result.get('date', '')} {result.get('time', '')}"
                    )
                )
            except:
                pass

        # Success message to user
        await update.message.reply_text(
            t('deposit_success', lang,
              method=method,
              amount=confirmed_amount,
              bonus=bonus,
              total=total,
              new_balance=new_balance),
            reply_markup=get_main_menu(lang)
        )
        return

    # TRANSFER FEATURE
    if text in ["🔄 Transfer / ይላኩ", "🔄 Transfer"]:
        total_lifetime_deposits = get_total_deposits(user_id)
        if total_lifetime_deposits < 50:
            err_msg = (
                "❌ ማዞር (መላክ) አይችሉም!\n\n"
                "⚠️ ገንዘብ ለማዞር (ለመላክ) 50 ብር ማስገባት አለብዎት።ፔ\n\n"
                "❌ You cannot transfer. You must deposit at least 50 ETB in total to unlock transfers."
            ) if lang == 'am' else "❌ Transfer locked!\n\n⚠️ You must deposit at least 50 ETB in total to unlock transfers."
            await update.message.reply_text(err_msg)
            return
        user_state[user_id] = "transfer_select_wallet"
        keyboard = ReplyKeyboardMarkup([["Main Wallet", "Play Wallet"], ["🔙 Back"]], resize_keyboard=True)
        tr_msg = "🔄 Select the wallet you want to send from:" if lang == 'en' else "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?"
        await update.message.reply_text(tr_msg, reply_markup=keyboard)
        return

    if user_state.get(user_id) == "transfer_select_wallet":
        if text == "🔙 Back":
            await update.message.reply_text("👇 Main Menu", reply_markup=get_inline_menu(lang))
            await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))
            user_state.pop(user_id, None)
            return
        if text not in ["Main Wallet", "Play Wallet"]:
            err_msg = "❌ Please choose Main Wallet or Play Wallet" if lang == 'en' else "❌ እባክዎ Main Wallet ወይም Play Wallet ይምረጡ"
            await update.message.reply_text(err_msg)
            return
        user_state[f"{user_id}_transfer_wallet"] = text
        user_state[user_id] = "transfer_phone"
        keyboard = ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True)
        phone_msg = (
            "📱 Enter the registered phone number of the person you want to send to:\n\n(Example: 0912345678)"
        ) if lang == 'en' else (
            "📱 ለመላክ የሚፈልጉትን ስልክ ቁጥር ያስገቡ:\n\n(ምሳሌ: 0912345678)"
        )
        await update.message.reply_text(phone_msg, reply_markup=keyboard)
        return

    if user_state.get(user_id) == "transfer_phone":
        if text == "🔙 Back":
            user_state[user_id] = "transfer_select_wallet"
            keyboard = ReplyKeyboardMarkup([["Main Wallet", "Play Wallet"], ["🔙 Back"]], resize_keyboard=True)
            tr_msg = "🔄 Select the wallet you want to send from:" if lang == 'en' else "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?"
            await update.message.reply_text(tr_msg, reply_markup=keyboard)
            return
        clean_phone = normalize_phone(text)
        receiver_user = get_user_by_phone(clean_phone)
        if not receiver_user:
            err_msg = "❌ This phone number is not registered in our bot." if lang == 'en' else "❌ ይህ ስልክ ቁጥር በቦቱ ውስጥ አልተመዘገበም"
            await update.message.reply_text(err_msg)
            return
        if receiver_user[0] == user_id:
            err_msg = "❌ You cannot transfer money to yourself!" if lang == 'en' else "❌ ለራስዎ ገንዘብ ማዞር (መላክ) አይችሉም!"
            await update.message.reply_text(err_msg)
            return
        user_state[f"{user_id}_transfer_target"] = receiver_user[0]
        user_state[user_id] = "transfer_amount"
        keyboard = ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True)
        amt_msg = "💰 Enter the amount you want to transfer (ETB):\n\nMin: 10 ETB" if lang == 'en' else "💰 ለመላክ የሚፈልጉትን መጠን ያስገቡ (ETB):\n\nዝቅተኛ: 10 ETB"
        await update.message.reply_text(amt_msg, reply_markup=keyboard)
        return

    if user_state.get(user_id) == "transfer_amount":
        if text == "🔙 Back":
            user_state[user_id] = "transfer_phone"
            keyboard = ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True)
            phone_msg = (
                "📱 Enter the registered phone number of the person you want to send to:\n\n(Example: 0912345678)"
            ) if lang == 'en' else (
                "📱 ለመላክ የሚፈልጉትን ስልክ ቁጥር ያስገቡ:\n\n(ምሳሌ: 0912345678)"
            )
            await update.message.reply_text(phone_msg, reply_markup=keyboard)
            return
        if not text.isdigit():
            err_msg = "❌ ቁጥር ብቻ ያስገባ" if lang == 'am' else "❌ Please enter a valid number"
            await update.message.reply_text(err_msg)
            return
        amount = int(text)
        wallet_type = user_state.get(f"{user_id}_transfer_wallet")
        target_id = user_state.get(f"{user_id}_transfer_target")
        if amount < 10:
            err_msg = "❌ ዝቅተኛ መጠን 10 ብር ነው" if lang == 'am' else "❌ Minimum amount is 10 ETB"
            await update.message.reply_text(err_msg)
            return
        if wallet_type == "Main Wallet":
            balance = get_main_balance(user_id)
        else:
            balance = get_play_balance(user_id)
        if amount > balance:
            err_msg = f"❌ በቂ ሂሳብ የለም ({wallet_type})\n💰 ያለዎት: {balance} ETB" if lang == 'am' else f"❌ Insufficient balance ({wallet_type})\n💰 Balance: {balance} ETB"
            await update.message.reply_text(err_msg)
            return
        if wallet_type == "Main Wallet":
            update_main_balance(user_id, -amount)
            update_main_balance(target_id, amount)
        else:
            update_play_balance(user_id, -amount)
            update_play_balance(target_id, amount)
        add_transaction(user_id, "transfer_out", amount)
        sender_name = update.effective_user.first_name
        try:
            receiver_chat = await context.bot.get_chat(target_id)
            receiver_name = receiver_chat.first_name
        except:
            receiver_name = "User"
        user_state.pop(user_id, None)
        user_state.pop(f"{user_id}_transfer_wallet", None)
        user_state.pop(f"{user_id}_transfer_target", None)
        sender_success_msg = (
            f"✅ Transfer Successful!\n\n"
            f"💸 Sent: {amount} ETB\n"
            f"👤 To: {receiver_name}\n"
            f"🏦 Wallet: {wallet_type}\n"
            f"✅ Money added to the user's {wallet_type}."
        )
        await update.message.reply_text(sender_success_msg, reply_markup=get_inline_menu(lang))
        await update.message.reply_text("⬇️ Menu:", reply_markup=get_main_menu(lang))
        receiver_msg = (
            f"💰 Money Received!\n\n"
            f"💸 Amount: {amount} ETB\n"
            f"👤 From: {sender_name}\n"
            f"🏦 Wallet: {wallet_type}\n"
            f"✅ The money has been added to your {wallet_type}."
        )
        try:
            await context.bot.send_message(chat_id=target_id, text=receiver_msg)
        except:
            pass
        return

    await update.message.reply_text("👇 Please use the menu buttons" if lang == 'en' else "👇 የሜኑ ቁልፎችን ይጠቀሙ")


# --------------------------
# WEB APP DATA HANDLER
# --------------------------
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    data = update.message.web_app_data.data
    print(f"🎮 Bingo win received from {user_name} ({user_id})! Data: {data}")
    await update.message.reply_text(f"🎉 Congratulations! Your bingo result has been recorded!\n\nData: {data}")
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=f"🎮 User {user_name} just won a Bingo game!\nData: {data}")
        except Exception as e:
            print(f"Could not notify admin {admin_id}: {e}")


# --------------------------
# INLINE MENU & LANGUAGE HANDLER
# --------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    first_name = query.from_user.first_name or ''
    if first_name and user_exists(user_id):
        update_user_name(user_id, first_name)

    if data in ["lang_am", "lang_en"]:
        lang = 'am' if data == "lang_am" else 'en'
        context.user_data["lang"] = lang
        if user_exists(user_id):
            set_user_language(user_id, lang)
            await query.message.edit_text(t('lang_changed', lang))
            await context.bot.send_message(chat_id=user_id, text=t('welcome_back', lang), reply_markup=get_main_menu(lang))
        else:
            button_text = t('share_phone_btn', lang)
            button = KeyboardButton(button_text, request_contact=True)
            keyboard = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
            await query.message.edit_text(t('select_language'))
            await context.bot.send_message(chat_id=user_id, text=t('welcome_new', lang), reply_markup=keyboard)
        return

    lang = get_user_language(user_id) if user_exists(user_id) else context.user_data.get("lang", 'am')

    if data.startswith("menu_"):
        user_state.pop(user_id, None)
        user_state.pop(f"{user_id}_amount", None)
        user_state.pop(f"{user_id}_withdraw_amount", None)
        user_state.pop(f"{user_id}_method", None)
        user_state.pop(f"{user_id}_transfer_wallet", None)
        user_state.pop(f"{user_id}_transfer_target", None)

    if data == "menu_open_game":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Play Bingo Now", web_app=WebAppInfo(url=MINI_APP_URL))]])
        game_msg = "🎮 Tap the button below to open the Bingo Game:" if lang == 'en' else "🎮 የቢንጎ ጨዋታውን ለመክፈት ከታች ያለውን ቁልፍ ይጫኑ:"
        await query.message.reply_text(game_msg, reply_markup=keyboard)
    elif data == "menu_balance":
        main = get_main_balance(user_id)
        play = get_play_balance(user_id)
        await query.message.reply_text(t('balance_msg', lang, main=main, play=play))
    elif data == "menu_deposit":
        user_state[user_id] = "deposit_amount"
        await query.message.reply_text(t('deposit_prompt', lang))
    elif data == "menu_withdraw":
        total_lifetime_deposits = get_total_deposits(user_id)
        if total_lifetime_deposits < 50:
            await query.message.reply_text(t('withdraw_locked', lang))
        else:
            user_state[user_id] = "withdraw_amount"
            play_bal = get_play_balance(user_id)
            main_bal = get_main_balance(user_id)
            await query.message.reply_text(t('withdraw_prompt', lang, play_bal=play_bal, main_bal=main_bal))
    elif data == "menu_history":
        history = get_last_5_transactions(user_id)
        if not history:
            no_hist = "📜 ግብይት አልተደረገም / No transactions yet." if lang == 'am' else "📜 No transactions yet."
            await query.message.reply_text(no_hist)
        else:
            msg = "📜 LAST 5 TRANSACTIONS\n\n"
            for tx in history:
                tx_type, amount, time_str = tx
                icon = "🟢 Deposit" if tx_type == "deposit" else "🔴 Withdraw"
                clean_time = time_str.split('.')[0]
                msg += f"{icon}\n💰 Amount: {amount} ETB\n⏰ Date: {clean_time}\n\n"
            await query.message.reply_text(msg)
    elif data == "menu_profile":
        user = get_user(user_id)
        if user:
            link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
            ref_count = get_referral_count(user_id)
            played = get_games_played_count(user_id)
            won = get_games_won_count(user_id)
            total_won_amt = get_total_won(user_id)
            profile_msg = (
                "👤 PROFILE\n\n"
                f"🆔 ID: {user[0]}\n"
                f"📱 Phone: {user[1]}\n\n"
                f"💰 Main Wallet: {user[2]} ETB\n"
                f"🎮 Play Wallet: {user[3]} ETB\n\n"
                f"🎯 Games Played: {played}\n"
                f"🏆 Games Won: {won}\n"
                f"💵 Total Won: {total_won_amt} ETB\n\n"
                f"👥 Referrals: {ref_count}\n"
                f"🎯 Invited By: {user[4] if len(user) > 4 and user[4] else 'No inviter'}\n\n"
                f"🎁 Invite Link:\n{link}"
            )
            await query.message.reply_text(profile_msg)
        else:
            await query.message.reply_text("❌ User not found")
    elif data == "menu_support":
        support_msg = (
            "☎️ Support\n\nFor any comments or questions, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82"
        ) if lang == 'en' else (
            "☎️ Support (ድጋፍ)\n\nFor any comment and question, contact support:\n@thelastking12312345678\n@Silencedoeir\n@one_day_82"
        )
        await query.message.reply_text(support_msg)
    elif data == "menu_invite":
        link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ref_count = get_referral_count(user_id)
        invite_msg = (
            "🎁 Invite Friends System\n\n"
            f"👥 Your Invites: {ref_count}\n\n"
            f"🔗 Your Referral Link:\n{link}\n\n"
            "💰 Earn 10% commission from every deposit made by your referrals!"
        )
        await query.message.reply_text(invite_msg)
    elif data == "menu_agent":
        invites = get_referral_count(user_id)
        depositors = get_depositing_referrals_count(user_id)
        total_deposits = get_total_referral_deposits(user_id)
        if is_user_agent(user_id):
            agent_msg = (
                "🤖 AGENT DASHBOARD\n\n⭐ Status: Official Agent\n\n"
                f"👥 Total Invites: {invites}\n"
                f"💳 Depositing Referrals: {depositors}\n"
                f"💰 Total Referral Deposits: {total_deposits} ETB\n\n"
                "🎁 Commission Rate: 10% CASH (Main Wallet)\n\n"
                "🚀 Keep inviting more friends to earn more real cash!"
            )
        else:
            agent_msg = (
                "🤖 AGENT UPGRADE PROGRAM\n\n⭐ Status: Normal User (10% Play Wallet)\n\n"
                f"1️⃣ 30+ Invites\nProgress: {invites}/30\n\n"
                f"2️⃣ 20+ Depositing Referrals\nProgress: {depositors}/20\n\n"
                f"3️⃣ 3000+ ETB Total Referral Deposits\nProgress: {total_deposits}/3000 ETB\n\n"
                "💪 Keep sharing your referral link to hit these goals!"
            )
        await query.message.reply_text(agent_msg)
    elif data == "menu_transfer":
        total_lifetime_deposits = get_total_deposits(user_id)
        if total_lifetime_deposits < 50:
            err_msg = (
                "❌ ማዞር (መላክ) አይችሉም!\n\n⚠️ ገንዘብ ለማዞር (ለመላክ) 50 ብር ማስገባት አለብዎት።ፔ\n\n❌ You cannot transfer. You must deposit at least 50 ETB in total to unlock transfers."
            ) if lang == 'am' else "❌ Transfer locked!\n\n⚠️ You must deposit at least 50 ETB in total to unlock transfers."
            await query.message.reply_text(err_msg)
        else:
            user_state[user_id] = "transfer_select_wallet"
            keyboard = ReplyKeyboardMarkup([["Main Wallet", "Play Wallet"], ["🔙 Back"]], resize_keyboard=True)
            tr_msg = "🔄 Select the wallet you want to send from:" if lang == 'en' else "🔄 ከየትኛው ዋሌት መላክ ይፈልጋሉ?"
            await query.message.reply_text(tr_msg, reply_markup=keyboard)
    elif data == "menu_info":
        await info(update, context, lang=lang)


# --------------------------
# INFO
# --------------------------
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE, lang=None):
    if lang is None:
        user_id = update.effective_user.id
        if user_exists(user_id):
            lang = get_user_language(user_id)
        else:
            lang = context.user_data.get("lang", 'am')
    if lang == 'en':
        await update.effective_message.reply_text(
            "☎️ Support\n\nIf you have any problems, contact @one_day_82\n\n"
            "ℹ️ Information\n\n🎮 How to play\n"
            "1. Click \"Open Game\"\n2. Select your Bingo cards\n"
            "3. Follow along as numbers are called\n4. Complete a winning pattern to win!\n\n"
            "Good luck! 🍀"
        )
    else:
        await update.effective_message.reply_text(
            "☎️ Support(ድጋፍ)\n\nችግር ካጋጠመዎት @one_day_82 ን ያግኙ\n\n"
            "ℹ️ Information(መረጃ)\n\n🎮 እንዴት እንደሚጫወቱ\n"
            "1. \"Play Now/ይጫወቱ\" የሚለውን ይጫኑ\n"
            "2. የቢንጎ ካርዶችዎን ይምረጡ\n"
            "3. ቁጥሮች ሲጠሩ እየተከታተሉ ካርዶችዎ ውስጥ ካሉ ያጥቁሩ\n"
            "4. ቢያንስ አንድ የማሸነፊያ ንድፍ ሲያጠናቅቁ \"BINGO\" ይበሉ\n\n"
            "መልካም ዕድል ይገጥምዎ! 🍀"
        )


# --------------------------
# APPROVE / REJECT
# --------------------------
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("❌ Please provide the request number. Example: /ap 1")
        return
    try:
        req_num = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid number. Example: /ap 1")
        return
    if req_num not in withdraw_requests:
        await update.message.reply_text(f"❌ Request #{req_num} not found.")
        return
    req_data = withdraw_requests[req_num]
    user_id = req_data["user_id"]
    amount = req_data["amount"]
    balance = get_main_balance(user_id)
    if amount > balance:
        await update.message.reply_text(f"❌ Insufficient user balance. User only has {balance} ETB.")
        return
    update_main_balance(user_id, -amount)
    add_transaction(user_id, "withdraw", amount)
    await context.bot.send_message(chat_id=user_id, text=f"✅ Withdraw Approved\n💰 Amount: {amount} ETB")
    await update.message.reply_text(f"✅ Request #{req_num} Approved successfully")
    del withdraw_requests[req_num]


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("❌ Please provide the request number. Example: /re 1")
        return
    try:
        req_num = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid number. Example: /re 1")
        return
    if req_num not in withdraw_requests:
        await update.message.reply_text(f"❌ Request #{req_num} not found.")
        return
    req_data = withdraw_requests[req_num]
    user_id = req_data["user_id"]
    await context.bot.send_message(chat_id=user_id, text="❌ Withdraw Request Rejected")
    await update.message.reply_text(f"❌ Request #{req_num} Rejected successfully")
    del withdraw_requests[req_num]


# --------------------------
# COMMAND SHORTCUTS
# --------------------------
async def cmd_play(update, context): await handle_text(update, context, custom_text="🎮 Open Game")
async def cmd_deposit(update, context): await handle_text(update, context, custom_text="💳 Deposit")
async def cmd_balance(update, context): await handle_text(update, context, custom_text="💰 Balance")
async def cmd_withdraw(update, context): await handle_text(update, context, custom_text="🐝 Withdraw")
async def cmd_profile(update, context): await handle_text(update, context, custom_text="👤 Profile")
async def cmd_support(update, context): await handle_text(update, context, custom_text="🏢 Support")
async def cmd_invite(update, context): await handle_text(update, context, custom_text="🎁 Invite Friends")
async def cmd_transfer(update, context): await handle_text(update, context, custom_text="🔄 Transfer")
async def cmd_history(update, context): await handle_text(update, context, custom_text="📜 History")
async def cmd_agent(update, context): await handle_text(update, context, custom_text="🤖 Agent Panel")


# ==========================
# FLASK API SERVER + SOCKETIO
# ==========================
flask_app = Flask(__name__)
CORS(flask_app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "ngrok-skip-browser-warning"]
    }
})

socketio = SocketIO(flask_app, cors_allowed_origins="*", async_mode='threading')


@flask_app.after_request
def add_headers(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response


@socketio.on('connect')
def on_connect():
    print(f'🔌 Client connected: {request.sid}')
    time_left = 0
    if game_state['timer_started_at'] and not game_state['running']:
        time_left = max(0, 35 - int(time_module.time() - game_state['timer_started_at']))
    emit('game_state_update', {
        'game_running': game_state['running'],
        'game_id': game_state['game_id'],
        'time_left': time_left,
        'total_players': game_state.get('total_players', 0),
        'called_numbers': list(game_state.get('called', [])),
        'current_number': game_state.get('current'),
    })


@socketio.on('disconnect')
def on_disconnect():
    print(f'🔌 Client disconnected: {request.sid}')


@socketio.on('join_room')
def on_join_room(data):
    from flask_socketio import join_room
    room = data.get('room', 'bingo_main')
    join_room(room)
    print(f'👤 Player joined room: {room}')


@socketio.on('leave_room')
def on_leave_room(data):
    from flask_socketio import leave_room
    room = data.get('room', 'bingo_main')
    leave_room(room)


@socketio.on('request_countdown')
def on_request_countdown(data):
    if not game_state['running']:
        game_state['timer_started_at'] = time_module.time()
        game_state['game_id'] = data.get('game_id', generate_game_id())
        emit('countdown_update', {
            'game_id': game_state['game_id'],
            'time_left': 35
        }, room='bingo_main')


@socketio.on('player_ready')
def on_player_ready(data):
    user_id = data.get('user_id')
    name = data.get('name', 'Player')
    cards = data.get('cards', [])
    game_id = data.get('game_id')

    if game_id == game_state.get('game_id') and not game_state.get('winner_declared', False):
        game_state['ready_players'][user_id] = {
            'name': name,
            'cards': cards,
            'card_num': cards[0] if cards else '—',
        }
        total = len(game_state['ready_players'])
        game_state['total_players'] = total
    else:
        total = len(game_state['ready_players'])

    emit('player_joined', {
        'total_players': total,
        'player_name': name,
    }, room='bingo_main')


@socketio.on('declare_winner')
def on_declare_winner(data):
    user_id = data.get('user_id')
    winner_name = data.get('name', 'Player')
    card_num = data.get('card_num', '—')
    card_index = data.get('card_index', 0)
    game_id = data.get('game_id', game_state.get('game_id'))

    if game_state.get('winner_declared', False):
        return
    game_state['winner_declared'] = True

    if user_id not in game_state['ready_players']:
        game_state['ready_players'][user_id] = {
            'name': winner_name,
            'cards': [],
            'card_num': card_num
        }

    total_players = len(game_state['ready_players'])
    prize = round(total_players * 10 * 0.8)

    emit('winner_found', {
        'user_id': user_id,
        'winner_name': winner_name,
        'card_num': card_num,
        'card_index': card_index,
        'prize': prize,
        'total_players': total_players,
        'game_id': game_id,
    }, room='bingo_main')


@socketio.on('admin_manual_call')
def on_admin_manual_call(data):
    number = data.get('number')
    admin  = data.get('admin', 'admin')
    if not number or not isinstance(number, int) or number < 1 or number > 75:
        return
    if number in game_state.get('called', []):
        return
    game_state.setdefault('called', []).append(number)
    game_state['current'] = number
    emit('ball_called', {'number': number, 'manual': True, 'admin': admin}, room='bingo_main')


@socketio.on('set_max_winners')
def on_set_max_winners(data):
    mx = data.get('max', 1)
    game_state['max_winners'] = max(1, min(4, int(mx)))
    emit('max_winners_updated', {'max': game_state['max_winners']}, room='bingo_main')


@socketio.on('admin_pause_game')
def on_admin_pause_game(data):
    game_state['paused'] = not game_state.get('paused', False)
    emit('game_paused', {'paused': game_state['paused']}, room='bingo_main')


@socketio.on('admin_cancel_game')
def on_admin_cancel_game(data):
    game_state['running'] = False
    game_state['called']  = []
    game_state['current'] = None
    game_state['ready_players'] = {}
    game_state['winner_declared'] = False
    game_state['winner_count'] = 0
    game_state['timer_started_at'] = time_module.time()
    emit('game_cancelled', {'reason': 'admin_cancelled'}, room='bingo_main')


def generate_game_id():
    d = time_module.localtime()
    return f"{d.tm_year}{d.tm_mon:02d}{d.tm_mday:02d}_{int(time_module.time()%10000)}"


# ==========================================
# FLASK API ROUTES
# ==========================================

@flask_app.route('/api/ping', methods=['GET', 'OPTIONS'])
def api_ping():
    return jsonify({'success': True, 'message': 'API is running', 'time': time_module.time()})


@flask_app.route('/api/update_name', methods=['POST', 'OPTIONS'])
def api_update_name():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    first_name = data.get('first_name', '')
    if not user_id or not first_name:
        return jsonify({'success': False, 'error': 'user_id and first_name required'}), 400
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'error': 'invalid user_id'}), 400
    if user_exists(user_id):
        update_user_name(user_id, first_name)
    return jsonify({'success': True})


@flask_app.route('/api/balance', methods=['GET', 'OPTIONS'])
def api_balance():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    if not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found. Please register in bot first.'}), 404

    status = 'active'
    is_vip = 0
    try:
        cur = get_cursor()
        cur.execute("SELECT status, is_vip FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            status = row[0] or 'active'
            is_vip = row[1] or 0
    except Exception:
        pass

    return jsonify({
        'success': True,
        'main_balance': get_main_balance(user_id),
        'play_balance': get_play_balance(user_id),
        'is_banned': status == 'banned',
        'is_frozen': status == 'frozen',
        'is_vip': is_vip == 1
    })


@flask_app.route('/api/bet', methods=['POST', 'OPTIONS'])
def api_bet():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'error': 'invalid user_id'}), 400
    if not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404

    try:
        cur = get_cursor()
        cur.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and row[0] == 'banned':
            return jsonify({'success': False, 'error': 'Account banned. Contact support.'}), 403
        if row and row[0] == 'frozen':
            return jsonify({'success': False, 'error': 'Account frozen. Contact support.'}), 403
    except Exception:
        pass

    success = deduct_bet_smart(user_id, amount)
    if not success:
        return jsonify({'success': False, 'error': 'Insufficient balance', 'play_balance': get_play_balance(user_id), 'main_balance': get_main_balance(user_id)}), 400

    add_transaction(user_id, 'bingo_bet', amount)
    return jsonify({
        'success': True,
        'main_balance': get_main_balance(user_id),
        'play_balance': get_play_balance(user_id)
    })


@flask_app.route('/api/win', methods=['POST', 'OPTIONS'])
def api_win():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    game_id = data.get('game_id', '')
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'error': 'invalid user_id'}), 400
    if not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404

    try:
        cur = get_cursor()
        cur.execute("SELECT status FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row and row[0] == 'banned':
            return jsonify({'success': False, 'error': 'Account banned'}), 403
        if row and row[0] == 'frozen':
            return jsonify({'success': False, 'error': 'Account frozen'}), 403
    except Exception:
        pass

    update_main_balance(user_id, amount)
    add_transaction(user_id, 'bingo_win', amount)
    complete_game_session(user_id, game_id, result=f'+{amount} Br', prize=amount)
    return jsonify({
        'success': True,
        'main_balance': get_main_balance(user_id),
        'play_balance': get_play_balance(user_id)
    })


@flask_app.route('/api/game_played', methods=['POST', 'OPTIONS'])
def api_game_played():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    game_id = data.get('game_id', '')
    cards = data.get('cards', [])
    entry = data.get('stake', 10)
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        user_id = int(user_id)
    except:
        return jsonify({'success': False, 'error': 'invalid user_id'}), 400
    if not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404
    add_game_session(user_id, game_id, cards, entry)
    return jsonify({'success': True})


@flask_app.route('/api/game_state', methods=['GET', 'OPTIONS'])
def api_game_state():
    now = time_module.time()
    time_left = 35

    if not game_state['running']:
        if game_state['timer_started_at']:
            elapsed = int(now - game_state['timer_started_at'])
            time_left = max(0, 35 - elapsed)
            if time_left == 0:
                game_state['running'] = True
                game_state['started_at'] = now
        else:
            game_state['timer_started_at'] = now
            time_left = 35

    return jsonify({
        'game_running': game_state['running'],
        'game_id': game_state['game_id'],
        'time_left': time_left,
        'total_players': len(game_state.get('ready_players', {})),
    })


@flask_app.route('/api/start_game', methods=['POST', 'OPTIONS'])
def api_start_game():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    game_state['running'] = True
    game_state['game_id'] = data.get('game_id', '')
    game_state['started_at'] = time_module.time()
    game_state['timer_started_at'] = None
    game_state['total_players'] = 0
    game_state['ready_players'] = {}
    game_state['winner_declared'] = False
    return jsonify({'success': True})


@flask_app.route('/api/end_game', methods=['POST', 'OPTIONS'])
def api_end_game():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    game_state['running'] = False
    game_state['game_id'] = None
    game_state['started_at'] = None
    game_state['timer_started_at'] = time_module.time()
    game_state['total_players'] = 0
    game_state['ready_players'] = {}
    game_state['winner_declared'] = False
    return jsonify({'success': True})


@flask_app.route('/api/profile_stats', methods=['GET', 'OPTIONS'])
def api_profile_stats():
    user_id = request.args.get('user_id', type=int)
    if not user_id or not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404

    is_vip = 0
    try:
        cur = get_cursor()
        cur.execute("SELECT is_vip FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row: is_vip = row[0] or 0
    except Exception:
        pass

    return jsonify({
        'success': True,
        'games_played': get_games_played_count(user_id),
        'games_won': get_games_won_count(user_id),
        'total_won': get_total_won(user_id),
        'invited': get_referral_count(user_id),
        'is_vip': is_vip == 1
    })


@flask_app.route('/api/game_history', methods=['GET', 'OPTIONS'])
def api_game_history():
    user_id = request.args.get('user_id', type=int)
    if not user_id or not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404
    rows = get_game_history(user_id, limit=20)
    history = []
    for row in rows:
        game_id, entry, status, result, ts = row
        history.append({'game_id': game_id, 'entry': entry, 'status': status, 'result': result, 'time': ts})
    return jsonify({'success': True, 'history': history})


@flask_app.route('/api/transactions', methods=['GET', 'OPTIONS'])
def api_transactions():
    user_id = request.args.get('user_id', type=int)
    if not user_id or not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404
    rows = get_all_transactions(user_id, limit=20)
    txs = []
    for row in rows:
        tx_type, amount, status, ts = row
        txs.append({'type': tx_type, 'amount': amount, 'status': status, 'time': ts})
    return jsonify({'success': True, 'transactions': txs})


@flask_app.route('/api/top_winners', methods=['GET', 'OPTIONS'])
def api_top_winners():
    period = request.args.get('period', 'week')
    category = request.args.get('category', 'deposit')
    if category == 'deposit':
        rows = get_top_by_deposit(period, 30)
    elif category == 'invite':
        rows = get_top_by_invitations(period, 30)
    elif category == 'wins':
        rows = get_top_by_wins(period, 30)
    else:
        rows = get_top_by_games(period, 30)
    winners = []
    for row in rows:
        uid, first_name, value = row
        name = first_name if first_name and first_name.strip() else 'User'
        winners.append({'name': name, 'value': value})
    return jsonify({'success': True, 'winners': winners})


@flask_app.route('/api/my_rank', methods=['GET', 'OPTIONS'])
def api_my_rank():
    user_id = request.args.get('user_id', type=int)
    period = request.args.get('period', 'week')
    category = request.args.get('category', 'deposit')
    if not user_id or not user_exists(user_id):
        return jsonify({'success': False, 'error': 'User not found'}), 404
    rank, value = get_user_rank(user_id, period, category)
    return jsonify({'success': True, 'rank': rank, 'value': value})


# ══════════════════════════════════════════════════════════
# ADMIN FLASK ROUTES
# ══════════════════════════════════════════════════════════

@flask_app.route('/api/admin/dashboard', methods=['GET', 'OPTIONS'])
def api_admin_dashboard():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        stats = db.get_dashboard_stats()
        stats['active_online'] = len(game_state.get('ready_players', {}))
        stats['running_games'] = 1 if game_state.get('running') else 0
        stats['success'] = True
        return jsonify(stats)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/deposits', methods=['GET', 'OPTIONS'])
def api_admin_deposits():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        deposits = db.get_all_deposits()
        return jsonify({'success': True, 'deposits': deposits})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/approve_deposit', methods=['POST', 'OPTIONS'])
def api_approve_deposit():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    deposit_id = data.get('deposit_id')
    success, user_id, amount = db.approve_deposit(deposit_id)
    return jsonify({'success': success})


@flask_app.route('/api/admin/reject_deposit', methods=['POST', 'OPTIONS'])
def api_reject_deposit():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    deposit_id = data.get('deposit_id')
    success, user_id = db.reject_deposit(deposit_id)
    return jsonify({'success': success})


@flask_app.route('/api/admin/withdrawals', methods=['GET', 'OPTIONS'])
def api_admin_withdrawals():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        withdrawals = db.get_all_withdrawals()
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
        return jsonify({'success': True, 'withdrawals': withdrawals})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/approve_withdrawal', methods=['POST', 'OPTIONS'])
def api_approve_withdrawal():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    withdrawal_id = data.get('withdrawal_id')
    user_id       = data.get('user_id')
    amount        = data.get('amount', 0)
    db.update_main_balance(user_id, -amount)
    db.add_transaction(user_id, 'withdraw', amount)
    try:
        import asyncio
        async def send_approval():
            await app.bot.send_message(chat_id=user_id, text=f"✅ Withdrawal Approved!\n\n💰 Amount: {amount} ETB\n🏦 The money has been sent to your account.")
        asyncio.run(send_approval())
    except Exception as e:
        print(f"Failed to send approval message to user {user_id}: {e}")
    if withdrawal_id in withdraw_requests:
        del withdraw_requests[withdrawal_id]
    else:
        db.approve_withdrawal(withdrawal_id)
    return jsonify({'success': True})


@flask_app.route('/api/admin/reject_withdrawal', methods=['POST', 'OPTIONS'])
def api_reject_withdrawal():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    withdrawal_id = data.get('withdrawal_id')
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    try:
        import asyncio
        async def send_rejection():
            await app.bot.send_message(chat_id=user_id, text=f"❌ Withdrawal Rejected\n\n💰 Amount: {amount} ETB\n⚠️ Your request was rejected by admin. The money remains in your Main Wallet.")
        asyncio.run(send_rejection())
    except Exception as e:
        print(f"Failed to send rejection message to user {user_id}: {e}")
    if withdrawal_id in withdraw_requests:
        del withdraw_requests[withdrawal_id]
    else:
        db.reject_withdrawal(withdrawal_id)
    return jsonify({'success': True})


@flask_app.route('/api/admin/users', methods=['GET', 'OPTIONS'])
def api_admin_users():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        users = db.get_all_users_with_stats()
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/add_balance', methods=['POST', 'OPTIONS'])
def api_add_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_main_balance(user_id, amount)
    db.add_transaction(user_id, 'admin_add', amount)
    return jsonify({'success': True, 'main_balance': new_bal, 'play_balance': db.get_play_balance(user_id)})


@flask_app.route('/api/admin/remove_balance', methods=['POST', 'OPTIONS'])
def api_remove_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_main_balance(user_id, -amount)
    db.add_transaction(user_id, 'admin_remove', amount)
    return jsonify({'success': True, 'main_balance': new_bal, 'play_balance': db.get_play_balance(user_id)})


@flask_app.route('/api/admin/add_main_balance', methods=['POST', 'OPTIONS'])
def api_add_main_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_main_balance(user_id, amount)
    db.add_transaction(user_id, 'admin_add_main', amount)
    return jsonify({'success': True, 'main_balance': new_bal, 'play_balance': db.get_play_balance(user_id)})


@flask_app.route('/api/admin/add_play_balance', methods=['POST', 'OPTIONS'])
def api_add_play_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_play_balance(user_id, amount)
    db.add_transaction(user_id, 'admin_add_play', amount)
    return jsonify({'success': True, 'main_balance': db.get_main_balance(user_id), 'play_balance': new_bal})


@flask_app.route('/api/admin/remove_main_balance', methods=['POST', 'OPTIONS'])
def api_remove_main_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_main_balance(user_id, -amount)
    db.add_transaction(user_id, 'admin_remove_main', amount)
    return jsonify({'success': True, 'main_balance': new_bal, 'play_balance': db.get_play_balance(user_id)})


@flask_app.route('/api/admin/remove_play_balance', methods=['POST', 'OPTIONS'])
def api_remove_play_balance():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    amount  = data.get('amount', 0)
    new_bal = db.update_play_balance(user_id, -amount)
    db.add_transaction(user_id, 'admin_remove_play', amount)
    return jsonify({'success': True, 'main_balance': db.get_main_balance(user_id), 'play_balance': new_bal})


@flask_app.route('/api/admin/ban_user', methods=['POST', 'OPTIONS'])
def api_ban_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    db.ban_user(data.get('user_id'))
    return jsonify({'success': True})


@flask_app.route('/api/admin/unban_user', methods=['POST', 'OPTIONS'])
def api_unban_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    db.unban_user(data.get('user_id'))
    return jsonify({'success': True})


@flask_app.route('/api/admin/freeze_user', methods=['POST', 'OPTIONS'])
def api_freeze_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    cur = db.get_cursor()
    cur.execute("UPDATE users SET status='frozen' WHERE user_id=?", (user_id,))
    db.conn.commit()
    return jsonify({'success': True})


@flask_app.route('/api/admin/unfreeze_user', methods=['POST', 'OPTIONS'])
def api_unfreeze_user():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    user_id = data.get('user_id')
    cur = db.get_cursor()
    cur.execute("UPDATE users SET status='active' WHERE user_id=?", (user_id,))
    db.conn.commit()
    return jsonify({'success': True})


@flask_app.route('/api/admin/mark_vip', methods=['POST', 'OPTIONS'])
def api_mark_vip():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    db.mark_vip(data.get('user_id'), data.get('vip', True))
    return jsonify({'success': True})


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


@flask_app.route('/api/admin/set_max_winners', methods=['POST', 'OPTIONS'])
def api_set_max_winners():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    mx = max(1, min(4, int(data.get('max_winners', 1))))
    game_state['max_winners'] = mx
    socketio.emit('max_winners_updated', {'max': mx}, room='bingo_main')
    return jsonify({'success': True, 'max_winners': mx})


@flask_app.route('/api/admin/pause_game', methods=['POST', 'OPTIONS'])
def api_pause_game():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    game_state['paused'] = not game_state.get('paused', False)
    socketio.emit('game_paused', {'paused': game_state['paused']}, room='bingo_main')
    return jsonify({'success': True, 'paused': game_state['paused']})


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
    elif category == 'wins':
        rows = get_top_by_wins(period, limit)
    else:
        rows = get_top_by_games(period, limit)
    rankings = []
    for r in rows:
        phone = get_user_phone(r[0]) or '—'
        rankings.append({'user_id': r[0], 'name': r[1] or 'User', 'phone': phone, 'value': r[2]})
    return jsonify({'success': True, 'rankings': rankings})


@flask_app.route('/api/admin/game_history', methods=['GET', 'OPTIONS'])
def api_admin_game_history():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    try:
        games = db.get_admin_game_history()
        return jsonify({'success': True, 'games': games})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/reports', methods=['GET', 'OPTIONS'])
def api_admin_reports():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    period = request.args.get('period', 'daily')
    try:
        rows = db.get_admin_reports(period)
        return jsonify({'success': True, 'rows': rows})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@flask_app.route('/api/admin/settings', methods=['POST', 'OPTIONS'])
def api_admin_settings():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    data = request.json or {}
    print(f"⚙️ Settings updated by {data.get('admin','admin')}: {data}")
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════
# FLASK SERVER RUNNER
# ══════════════════════════════════════════════════════════

def run_flask():
    socketio.run(flask_app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


# ==========================
# APP SETUP
# ==========================
PROXY_URL = None
builder = ApplicationBuilder().token(TOKEN)
if PROXY_URL:
    builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
builder = builder.connect_timeout(60.0).read_timeout(60.0).write_timeout(60.0).pool_timeout(60.0)
app = builder.build()


async def change_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am"),
            InlineKeyboardButton("🇸🇸 English", callback_data="lang_en")
        ]
    ])
    await update.message.reply_text(t('select_language', 'en'), reply_markup=keyboard)


app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("lang", change_lang))
app.add_handler(CommandHandler("info", info))
app.add_handler(CommandHandler("ap", approve))
app.add_handler(CommandHandler("re", reject))
app.add_handler(CommandHandler("play", cmd_play))
app.add_handler(CommandHandler("deposit", cmd_deposit))
app.add_handler(CommandHandler("balance", cmd_balance))
app.add_handler(CommandHandler("withdraw", cmd_withdraw))
app.add_handler(CommandHandler("profile", cmd_profile))
app.add_handler(CommandHandler("support", cmd_support))
app.add_handler(CommandHandler("invite", cmd_invite))
app.add_handler(CommandHandler("transfer", cmd_transfer))
app.add_handler(CommandHandler("history", cmd_history))
app.add_handler(CommandHandler("agent", cmd_agent))
app.add_handler(CallbackQueryHandler(handle_callback))
app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
app.add_handler(MessageHandler(filters.CONTACT, get_contact))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()
print("✅ Bot is running with Telebirr SMS verification + Full Mini App API + Admin Panel...")
app.run_polling()
