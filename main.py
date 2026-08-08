#!/usr/bin/env python3
"""
HACKERS DB - OSINT BOT v3.0
FORCE JOIN CHANNEL + AUTO BACKUP + ALL FEATURES
"""

import logging
import telebot
from telebot import types
import re
import time
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

# ============ SAFE IMPORTS ============
try:
    from config import (
        BOT_TOKEN, ADMIN_IDS, OWNER_IDS, MAX_QUERY_LENGTH,
        FORCE_CHANNEL, FORCE_CHANNEL_LINK, DATABASE_FILE
    )
except ImportError:
    from config import BOT_TOKEN, ADMIN_IDS, OWNER_IDS, MAX_QUERY_LENGTH
    FORCE_CHANNEL = ''
    FORCE_CHANNEL_LINK = ''
    DATABASE_FILE = 'osint_bot.db'

from database import db
from api import search_api, extract_records
from formatter import Formatter
from utils import detect_search_type

# Import admin functions
from admin import (
    admin_panel, stats_command, users_command,
    give_subscription_command, remove_subscription_command,
    add_tokens_command, ban_command, unban_command,
    delete_user_command, gen_code_command, broadcast_command,
    admin_logs_command, handle_admin_callbacks, get_admin_keyboard
)

# Import backup
from backup import BackupManager

logger = logging.getLogger(__name__)

# ============ GLOBALS ============
db_lock = threading.Lock()
DAILY_LIMIT = 5
FORCE_JOIN_ENABLED = True

# ============ HTML ESCAPE ============
def escape_html(text):
    if text is None:
        return ''
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&#39;')
    return text

# ============ RATE LIMITER ============
class RateLimiter:
    def __init__(self, max_requests: int = 10, time_window: int = 60, cooldown: int = 30):
        self.max_requests = max_requests
        self.time_window = time_window
        self.cooldown = cooldown
        self._requests = {}
        self._cooldowns = {}
        self._lock = threading.RLock()
    
    def is_limited(self, user_id: int):
        with self._lock:
            current_time = time.time()
            
            if user_id in self._cooldowns:
                if current_time < self._cooldowns[user_id]:
                    return True, int(self._cooldowns[user_id] - current_time)
                del self._cooldowns[user_id]
            
            if user_id not in self._requests:
                self._requests[user_id] = []
            
            cutoff = current_time - self.time_window
            self._requests[user_id] = [t for t in self._requests[user_id] if t > cutoff]
            
            if len(self._requests[user_id]) >= self.max_requests:
                self._cooldowns[user_id] = current_time + self.cooldown
                return True, self.cooldown
            
            self._requests[user_id].append(current_time)
            return False, 0

# ============ BOT INIT ============
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
rate_limiter = RateLimiter()
executor = ThreadPoolExecutor(max_workers=5)
user_mode = {}

# ============ FORCE JOIN CHECK FUNCTION ============

def is_user_joined_channel(user_id: int) -> bool:
    """Check if user has joined the force channel"""
    global FORCE_JOIN_ENABLED
    
    if not FORCE_CHANNEL:
        return True
    
    if user_id in OWNER_IDS:
        return True
    
    if not FORCE_JOIN_ENABLED:
        return True
    
    try:
        channel = FORCE_CHANNEL
        if channel.startswith('@'):
            channel = channel[1:]
        
        chat_id = f"@{channel}"
        member = bot.get_chat_member(chat_id, user_id)
        
        logger.info(f"🔍 Force join check: User {user_id} status: {member.status}")
        
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
            
    except Exception as e:
        error_msg = str(e).lower()
        logger.error(f"❌ Force join error: {e}")
        
        if "member list is inaccessible" in error_msg:
            FORCE_JOIN_ENABLED = False
            logger.warning("⚠️ Bot is NOT admin in channel! Force join DISABLED.")
            logger.warning(f"⚠️ Add @{bot.get_me().username} as admin with 'Get members' permission")
            return True
        
        if "bot is not a member" in error_msg or "bot is not an administrator" in error_msg:
            FORCE_JOIN_ENABLED = False
            logger.warning("⚠️ Bot is NOT admin in channel! Force join DISABLED.")
            return True
        
        if "user not found" in error_msg:
            return False
        
        return True

def force_join_decorator(func):
    """Decorator to force join check before any command"""
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        
        if not FORCE_JOIN_ENABLED or not FORCE_CHANNEL:
            return func(message, *args, **kwargs)
        
        if not is_user_joined_channel(user_id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            if FORCE_CHANNEL_LINK:
                markup.add(types.InlineKeyboardButton("📢 Join Channel", url=FORCE_CHANNEL_LINK))
            markup.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="check_join"))
            
            bot.reply_to(message, 
                f"<b>⚠️ JOIN CHANNEL FIRST!</b>\n\n"
                f"Please join our channel to use this bot.\n\n"
                f"<b>📢 Channel:</b> @{FORCE_CHANNEL}\n\n"
                f"Click <b>Join Channel</b> then <b>I've Joined</b> to continue.",
                parse_mode='HTML', reply_markup=markup)
            return
        
        return func(message, *args, **kwargs)
    return wrapper

# ============ DECORATORS ============
def rate_limited(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        limited, wait_time = rate_limiter.is_limited(user_id)
        if limited:
            bot.reply_to(message, f"⏰ Please wait {wait_time} seconds")
            return
        return func(message, *args, **kwargs)
    return wrapper

def admin_only(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        return func(message, *args, **kwargs)
    return wrapper

def owner_only(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Owner Only!")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ============ KEYBOARDS ============
def get_main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        types.KeyboardButton("📱 PHONE SEARCH"),
        types.KeyboardButton("🆔 AADHAAR SEARCH"),
        types.KeyboardButton("👤 PROFILE"),
        types.KeyboardButton("💰 REFER & EARN"),
        types.KeyboardButton("🎁 DAILY BONUS"),
        types.KeyboardButton("📜 HISTORY"),
        types.KeyboardButton("🛍 BUY PREMIUM"),
        types.KeyboardButton("📞 SUPPORT"),
    ]
    if user_id and (user_id in ADMIN_IDS or user_id in OWNER_IDS):
        buttons.append(types.KeyboardButton("👑 ADMIN"))
    markup.add(*buttons)
    return markup

def get_osint_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        types.KeyboardButton("📱 PHONE"),
        types.KeyboardButton("🆔 AADHAAR"),
        types.KeyboardButton("◀️ BACK"),
    ]
    markup.add(*buttons)
    return markup

# ============ SEARCH FUNCTION ============
def perform_search(message, query: str, search_type: str):
    try:
        user_id = message.from_user.id
        
        with db_lock:
            user = db.get_user(user_id)
            if not user:
                db.create_user(user_id, 
                             message.from_user.username or '', 
                             message.from_user.first_name or '', 
                             message.from_user.last_name or '')
                user = db.get_user(user_id)
            
            if user and user.get('is_banned', 0) == 1:
                bot.reply_to(message, "🚫 You are banned!")
                return
            
            is_premium = db.is_premium(user_id)
            tokens = db.get_tokens(user_id)
        
        if not is_premium:
            if tokens <= 0:
                bot.reply_to(message, "❌ No credits left!\nUse /daily for free credit\nOr /refer to earn more")
                return
            with db_lock:
                if not db.deduct_token(user_id):
                    bot.reply_to(message, "❌ Failed to deduct token")
                    return
        
        result = search_api(query)
        
        if result.get('error'):
            bot.reply_to(message, f"❌ Error: {result['error']}")
            return
        
        records = extract_records(result)
        
        with db_lock:
            db.add_search_history(user_id, query, search_type, len(records))
            db.update_user(user_id, total_requests=user.get('total_requests', 0) + 1)
        
        tokens_info = {
            'is_premium': is_premium,
            'tokens': db.get_tokens(user_id) if not is_premium else None
        }
        
        formatted = Formatter.format_result(result, query, tokens_info)
        
        if len(formatted) > 4096:
            for i in range(0, len(formatted), 4096):
                bot.send_message(message.chat.id, formatted[i:i+4096], parse_mode='HTML')
        else:
            bot.reply_to(message, formatted, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ START COMMAND ============

@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        user = message.from_user
        user_id = user.id
        
        # ====== FIRST: CHECK FORCE JOIN ======
        if FORCE_JOIN_ENABLED and FORCE_CHANNEL:
            if not is_user_joined_channel(user_id):
                markup = types.InlineKeyboardMarkup(row_width=1)
                if FORCE_CHANNEL_LINK:
                    markup.add(types.InlineKeyboardButton("📢 Join Channel", url=FORCE_CHANNEL_LINK))
                markup.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="check_join"))
                
                bot.reply_to(message, 
                    f"<b>⚠️ JOIN CHANNEL FIRST!</b>\n\n"
                    f"Please join our channel to use this bot.\n\n"
                    f"<b>📢 Channel:</b> @{FORCE_CHANNEL}\n\n"
                    f"Click <b>Join Channel</b> then <b>I've Joined</b> to continue.",
                    parse_mode='HTML', reply_markup=markup)
                return
        
        # ====== SECOND: PROCESS REFERRAL ======
        args = message.text.split()
        referral_code = None
        if len(args) > 1 and args[1].startswith('ref_'):
            referral_code = args[1][4:]
        
        with db_lock:
            if not db.get_user(user_id):
                db.create_user(user_id, user.username or '', user.first_name or '', 
                             user.last_name or '')
            
            if referral_code:
                success, msg = db.process_referral(user_id, referral_code)
                if success:
                    bot.reply_to(message, f"🎉 {msg}")
        
        # ====== THIRD: SHOW WELCOME ======
        with db_lock:
            referral_code = db.generate_referral_code(user_id)
            tokens = db.get_tokens(user_id)
            is_premium = db.is_premium(user_id)
            user_data = db.get_user(user_id)
        
        username = escape_html(user.first_name or 'User')
        
        response = f"""
<b>👋 Welcome, {username}!</b>

<b>🔍 OSINT SEARCH BOT</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 COMMANDS:</b>
<b>🔍</b> <code>/num 91xxxxxxxxxx</code> — Phone lookup
<b>🆔</b> <code>/aadhaar 12digits</code> — Aadhaar search
<b>💳</b> <code>/balance</code> — Check credits
<b>🔗</b> <code>/refer</code> — Refer & earn
<b>🛍</b> <code>/shop</code> — Buy premium
<b>ℹ️</b> <code>/help</code> — Help menu

<b>📊 YOUR STATUS:</b>
├ <b>Status:</b> {'💎 PREMIUM' if is_premium else '📄 FREE'}
├ <b>Credits:</b> {tokens if not is_premium else '♾️ Unlimited'}
├ <b>Searches:</b> {user_data.get('total_requests', 0)}
└ <b>Referrals:</b> {db.get_referral_stats(user_id)['count']}

<b>🔗 YOUR REFERRAL LINK:</b>
<code>https://t.me/{bot.get_me().username}?start=ref_{referral_code}</code>

<b>📝 SHARE & EARN!</b>
• Each referral = <b>+3 FREE CREDITS</b>
• No limit on referrals

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>💡</b> Tap <b>📋 OSINT MENU</b> below to start!
"""
        bot.reply_to(message, response, parse_mode='HTML',
                    reply_markup=get_main_keyboard(user_id))
        
    except Exception as e:
        logger.error(f"Start error: {e}")
        bot.reply_to(message, "❌ Error starting bot.")

# ============ CALLBACK HANDLER ============

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data == "check_join":
            user_id = call.from_user.id
            
            if is_user_joined_channel(user_id):
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except:
                    pass
                
                bot.answer_callback_query(call.id, "✅ Verified! You can use the bot now.", show_alert=True)
                start_command(call.message)
            else:
                bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet! Please join first.", show_alert=True)
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                if FORCE_CHANNEL_LINK:
                    markup.add(types.InlineKeyboardButton("📢 Join Channel", url=FORCE_CHANNEL_LINK))
                markup.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="check_join"))
                
                try:
                    bot.edit_message_text(
                        f"<b>⚠️ JOIN CHANNEL FIRST!</b>\n\n"
                        f"Please join our channel to use this bot.\n\n"
                        f"<b>📢 Channel:</b> @{FORCE_CHANNEL}\n\n"
                        f"Click <b>Join Channel</b> then <b>I've Joined</b> to continue.",
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                except:
                    pass
            return
        
        # Admin callbacks
        handle_admin_callbacks(call, bot)
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Error", show_alert=True)

# ============ COMMAND HANDLERS ============

@bot.message_handler(commands=['help'])
@force_join_decorator
def help_command(message):
    try:
        user_id = message.from_user.id
        with db_lock:
            is_premium = db.is_premium(user_id)
            tokens = db.get_tokens(user_id)
            user = db.get_user(user_id)
        
        searches_today = user.get('total_requests', 0) if user else 0
        
        response = f"""
<b>📖 HELP - OSINT SEARCH BOT</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>🔍 SEARCH COMMANDS</b>

<b>📱</b> <code>/num 91xxxxxxxxxx</code>
    └─ Phone number lookup
    
<b>🆔</b> <code>/aadhaar 12digits</code>
    └─ Aadhaar number search

<b>💰 ACCOUNT COMMANDS</b>

<b>💳</b> <code>/balance</code>
    └─ Check your credits
    
<b>🔗</b> <code>/refer</code>
    └─ Get referral link & stats
    
<b>🎁</b> <code>/daily</code>
    └─ Claim free credit
    
<b>📜</b> <code>/history</code>
    └─ View search history

<b>🛍 PREMIUM COMMANDS</b>

<b>🛍</b> <code>/shop</code>
    └─ View premium plans
    
<b>🔮</b> <code>/redeem CODE</code>
    └─ Redeem premium code

<b>📞 SUPPORT</b>
<b>📱</b> Telegram: <b>@Rahul_Neoo</b>

<b>📊 YOUR STATUS</b>
├ <b>Status:</b> {'💎 Premium' if is_premium else '📄 Free'}
├ <b>Credits:</b> {tokens if not is_premium else '♾️ Unlimited'}
└ <b>Searches:</b> {searches_today}

<b>💡 TIPS</b>
• Each search uses 1 credit
• Get free credits via <b>/daily</b>
• Earn <b>+3</b> credits per referral
• Premium = Unlimited searches!

━━━━━━━━━━━━━━━━━━━━━━━━
<b>📞</b> Support: @Rahul_Neoo
"""
        bot.reply_to(message, response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Help error: {e}")
        bot.reply_to(message, "❌ Error showing help.")

@bot.message_handler(commands=['balance'])
@force_join_decorator
def balance_command(message):
    try:
        user_id = message.from_user.id
        
        with db_lock:
            is_premium = db.is_premium(user_id)
            tokens = db.get_tokens(user_id)
            user = db.get_user(user_id)
            stats = db.get_referral_stats(user_id)
        
        searches = user.get('total_requests', 0) if user else 0
        
        response = f"""
<b>💳 BALANCE</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>Status:</b> {'💎 Premium' if is_premium else '📄 Free'}
<b>Credits:</b> {tokens if not is_premium else '♾️ Unlimited'}
<b>Total Searches:</b> {searches}
<b>Referrals:</b> {stats['count']}
<b>Tokens Earned:</b> {stats['tokens_earned']}

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>🎁</b> Use <code>/daily</code> for free credit
<b>🔗</b> Use <code>/refer</code> to earn more
<b>🛍</b> Use <code>/shop</code> for premium
"""
        bot.reply_to(message, response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Balance error: {e}")
        bot.reply_to(message, "❌ Error checking balance")

@bot.message_handler(commands=['num', 'phone'])
@rate_limited
@force_join_decorator
def num_command(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "📱 Use: /num 91xxxxxxxxxx")
        return
    
    query = args[1].strip()
    if not re.fullmatch(r'91\d{10}', query):
        bot.reply_to(message, "❌ Invalid! Use: 91 + 10 digits")
        return
    
    executor.submit(perform_search, message, query, 'phone')

@bot.message_handler(commands=['aadhaar', 'uid'])
@rate_limited
@force_join_decorator
def aadhaar_command(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "🆔 Use: /aadhaar 12digits")
        return
    
    query = args[1].strip().replace(' ', '')
    if not re.fullmatch(r'\d{12}', query):
        bot.reply_to(message, "❌ Invalid Aadhaar! Use 12 digits")
        return
    
    executor.submit(perform_search, message, query, 'aadhaar')

@bot.message_handler(commands=['refer'])
@force_join_decorator
def refer_command(message):
    try:
        user_id = message.from_user.id
        args = message.text.split(maxsplit=1)
        
        if len(args) > 1:
            code = args[1].strip().upper()
            with db_lock:
                success, msg = db.process_referral(user_id, code)
            bot.reply_to(message, msg)
            return
        
        with db_lock:
            referral_code = db.generate_referral_code(user_id)
            stats = db.get_referral_stats(user_id)
            tokens = db.get_tokens(user_id)
        
        bot_username = bot.get_me().username
        
        response = f"""
<b>💰 REFERRAL SYSTEM</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 Your Referral Code:</b>
<code>{referral_code}</code>

<b>🔗 Share this link:</b>
<code>https://t.me/{bot_username}?start=ref_{referral_code}</code>

<b>📊 Your Stats:</b>
├ <b>Referrals:</b> {stats['count']}
├ <b>Tokens Earned:</b> {stats['tokens_earned']}
└ <b>Your Credits:</b> {tokens}

<b>✨ How it works:</b>
• Share your code with friends
• When they join, you get <b>+3 TOKENS</b>!
• Unlimited referrals!
• No limit on earning!

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>📝</b> Share: <code>/refer YOUR_CODE</code>
"""
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Refer error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(commands=['redeem'])
@force_join_decorator
def redeem_command(message):
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            bot.reply_to(message, "🔮 Use: /redeem CODE")
            return
        
        code = args[1].strip().upper()
        
        with db_lock:
            success, display = db.redeem_code(code, message.from_user.id)
        
        if success:
            bot.reply_to(message, f"✅ Redeemed! Premium for {display}")
        else:
            bot.reply_to(message, "❌ Invalid code!")
    except Exception as e:
        logger.error(f"Redeem error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(commands=['daily'])
@force_join_decorator
def daily_command(message):
    try:
        user_id = message.from_user.id
        
        with db_lock:
            if db.is_premium(user_id):
                bot.reply_to(message, "💎 You are Premium - Unlimited credits!", parse_mode='HTML')
                return
            
            success, new_total = db.claim_daily(user_id)
        
        if success:
            response = f"""
<b>🎁 DAILY BONUS CLAIMED!</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>✅</b> +3 Credits Added!
<b>📊</b> Total Credits: {new_total}

<b>💡</b> Come back tomorrow for +3 more!
<b>🔗</b> Share & earn via <code>/refer</code>
"""
            bot.reply_to(message, response, parse_mode='HTML')
        else:
            with db_lock:
                user = db.get_user(user_id)
                tokens = user.get('tokens', 0) if user else 0
            
            response = f"""
<b>⏰ ALREADY CLAIMED TODAY!</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>📊</b> Your Credits: {tokens}

<b>💡</b> Come back tomorrow for +3 free credits!
<b>🔗</b> Or use <code>/refer</code> to earn more!
"""
            bot.reply_to(message, response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Daily error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(commands=['history'])
@force_join_decorator
def history_command(message):
    try:
        user_id = message.from_user.id
        
        with db_lock:
            history = db.get_search_history(user_id, 10)
        
        if not history:
            bot.reply_to(message, "📭 No search history found")
            return
        
        response = "<b>📜 SEARCH HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for idx, item in enumerate(history, 1):
            query = escape_html(item.get('query', 'N/A'))
            s_type = escape_html(item.get('search_type', 'N/A'))
            count = item.get('result_count', 0)
            timestamp = escape_html(item.get('timestamp', 'N/A'))
            
            response += f"<b>{idx}.</b> <code>{query}</code>\n"
            response += f"   ├ <b>Type:</b> {s_type}\n"
            response += f"   ├ <b>Results:</b> {count}\n"
            response += f"   └ <b>Time:</b> {timestamp}\n\n"
        
        bot.reply_to(message, response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"History error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(commands=['profile'])
@force_join_decorator
def profile_command(message):
    try:
        user_id = message.from_user.id
        
        with db_lock:
            user = db.get_user(user_id)
            if not user:
                bot.reply_to(message, "❌ Please /start first")
                return
            
            is_premium = db.is_premium(user_id)
            is_owner = db.is_owner(user_id)
            tokens = db.get_tokens(user_id)
            stats = db.get_referral_stats(user_id)
            sub_end = db.get_subscription_end(user_id)
        
        status = "👑 OWNER" if is_owner else "💎 PREMIUM" if is_premium else "📄 FREE"
        credits = "♾️ Unlimited" if is_owner or is_premium else str(tokens)
        
        response = f"""
<b>👤 PROFILE</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>ID:</b> <code>{user_id}</code>
<b>Name:</b> {escape_html(user.get('first_name', 'Not set'))}
<b>Username:</b> @{escape_html(message.from_user.username or 'Not set')}

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>Status:</b> {status}
<b>Credits:</b> {credits}
<b>Searches:</b> {user.get('total_requests', 0)}

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>💰 Referrals:</b> {stats['count']}
<b>🎁 Tokens Earned:</b> {stats['tokens_earned']}
<b>📅 Subscription:</b> {escape_html(sub_end or 'No active subscription')}
"""
        bot.reply_to(message, response, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Profile error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(commands=['shop'])
@force_join_decorator
def shop_command(message):
    response = """
<b>🛍 PREMIUM PLANS</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>⏱️ 1 Hour</b>      — ₹49
<b>📅 1 Day</b>       — ₹249
<b>📆 15 Days</b>     — ₹999
<b>🗓️ 30 Days</b>     — ₹1499

<b>✨ PREMIUM FEATURES</b>
├ Unlimited searches
├ All commands available
├ Priority support
└ No daily limits

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>📞</b> Contact: @Rahul_Neoo
<b>🔮</b> Have code? Use <code>/redeem CODE</code>

<b>💳</b> Payment: UPI / Crypto / Card
"""
    bot.reply_to(message, response, parse_mode='HTML')

@bot.message_handler(commands=['support'])
@force_join_decorator
def support_command(message):
    response = """
<b>📞 SUPPORT</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>📱 Telegram:</b> @Rahul_Neoo
<b>📧 Email:</b> support@osintbot.com

<b>🛍 BUY PREMIUM:</b>
Use <code>/shop</code> to view plans

<b>❓ FAQ:</b>
├ <b>Q:</b> How to get free credits?
├ <b>A:</b> Use <code>/daily</code> or <code>/refer</code>
├ 
├ <b>Q:</b> What is premium?
├ <b>A:</b> Unlimited searches + priority
├ 
├ <b>Q:</b> How to redeem code?
└ <b>A:</b> Use <code>/redeem CODE</code>

<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>
<b>💬</b> Reply within 24 hours
"""
    bot.reply_to(message, response, parse_mode='HTML')

# ============ BACKUP COMMAND ============

@bot.message_handler(commands=['backupnow'])
@force_join_decorator
def backup_now_command(message):
    """Manual backup - Owner only"""
    user_id = message.from_user.id
    if user_id not in OWNER_IDS:
        bot.reply_to(message, "❌ Access Denied!")
        return
    
    try:
        bot.reply_to(message, "📦 Creating backup...")
        backup_manager._send_backup()
        bot.reply_to(message, "✅ Backup sent to your DM!")
    except Exception as e:
        logger.error(f"Backup error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ ADMIN COMMANDS ============

@bot.message_handler(commands=['admin'])
@force_join_decorator
def admin_panel_handler(message):
    admin_panel(message, bot)

@bot.message_handler(commands=['stats'])
@admin_only
@force_join_decorator
def stats_handler(message):
    stats_command(message, bot)

@bot.message_handler(commands=['users'])
@admin_only
@force_join_decorator
def users_handler(message):
    users_command(message, bot)

@bot.message_handler(commands=['givesub'])
@admin_only
@force_join_decorator
def give_sub_handler(message):
    give_subscription_command(message, bot)

@bot.message_handler(commands=['removesub'])
@admin_only
@force_join_decorator
def remove_sub_handler(message):
    remove_subscription_command(message, bot)

@bot.message_handler(commands=['addtokens'])
@admin_only
@force_join_decorator
def add_tokens_handler(message):
    add_tokens_command(message, bot)

@bot.message_handler(commands=['ban'])
@admin_only
@force_join_decorator
def ban_handler(message):
    ban_command(message, bot)

@bot.message_handler(commands=['unban'])
@admin_only
@force_join_decorator
def unban_handler(message):
    unban_command(message, bot)

@bot.message_handler(commands=['deleteuser'])
@admin_only
@force_join_decorator
def delete_user_handler(message):
    delete_user_command(message, bot)

@bot.message_handler(commands=['gen'])
@admin_only
@force_join_decorator
def gen_code_handler(message):
    gen_code_command(message, bot)

@bot.message_handler(commands=['broadcast'])
@owner_only
@force_join_decorator
def broadcast_handler(message):
    broadcast_command(message, bot)

@bot.message_handler(commands=['adminlogs'])
@admin_only
@force_join_decorator
def admin_logs_handler(message):
    admin_logs_command(message, bot)

# ============ BUTTON HANDLERS ============

@bot.message_handler(func=lambda message: message.text == "📱 PHONE SEARCH")
@force_join_decorator
def phone_search_button(message):
    bot.reply_to(message, "📱 Enter phone number:\n<code>91xxxxxxxxxx</code>", parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == "🆔 AADHAAR SEARCH")
@force_join_decorator
def aadhaar_search_button(message):
    bot.reply_to(message, "🆔 Enter Aadhaar number:\n<code>12 digits</code> only", parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == "👤 PROFILE")
@force_join_decorator
def profile_button_handler(message):
    profile_command(message)

@bot.message_handler(func=lambda message: message.text == "💰 REFER & EARN")
@force_join_decorator
def refer_button_handler(message):
    refer_command(message)

@bot.message_handler(func=lambda message: message.text == "🎁 DAILY BONUS")
@force_join_decorator
def daily_button_handler(message):
    daily_command(message)

@bot.message_handler(func=lambda message: message.text == "📜 HISTORY")
@force_join_decorator
def history_button_handler(message):
    history_command(message)

@bot.message_handler(func=lambda message: message.text == "🛍 BUY PREMIUM")
@force_join_decorator
def shop_button_handler(message):
    shop_command(message)

@bot.message_handler(func=lambda message: message.text == "📞 SUPPORT")
@force_join_decorator
def support_button_handler(message):
    support_command(message)

@bot.message_handler(func=lambda message: message.text == "◀️ BACK")
def back_to_main(message):
    user_id = message.from_user.id
    user_mode[user_id] = None
    bot.reply_to(message, "🏠 Main Menu", reply_markup=get_main_keyboard(user_id))

# ============ ADMIN BUTTONS ============

@bot.message_handler(func=lambda message: message.text == "👑 ADMIN")
@force_join_decorator
def admin_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        admin_panel(message, bot)
    except Exception as e:
        logger.error(f"Admin button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "📊 STATS")
@force_join_decorator
def stats_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        stats_command(message, bot)
    except Exception as e:
        logger.error(f"Stats button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "👥 USERS")
@force_join_decorator
def users_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        users_command(message, bot)
    except Exception as e:
        logger.error(f"Users button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "📢 BROADCAST")
@force_join_decorator
def broadcast_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "📢 Send broadcast:\n<code>/broadcast Your message here</code>", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Broadcast button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "🎫 GEN CODE")
@force_join_decorator
def gen_code_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "🎫 Generate code:\n<code>/gen 1hour|1day|7day|15day|30day</code>", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Gen code button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "💎 ADD TOKENS")
@force_join_decorator
def add_tokens_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "💎 Add tokens:\n<code>/addtokens USER_ID AMOUNT</code>", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Add tokens button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "🎁 GIVE SUBSCRIPTION")
@force_join_decorator
def give_sub_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "🎁 Give subscription:\n<code>/givesub USER_ID DURATION</code>\n\nOptions: 1hour, 1day, 7day, 15day, 30day", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Give sub button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "🚫 BAN")
@force_join_decorator
def ban_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "🚫 Ban user:\n<code>/ban USER_ID [reason]</code>", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ban button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "✅ UNBAN")
@force_join_decorator
def unban_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "✅ Unban user:\n<code>/unban USER_ID</code>", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Unban button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "🗑️ DELETE USER")
@force_join_decorator
def delete_user_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        bot.reply_to(message, "🗑️ Delete user:\n<code>/deleteuser USER_ID</code>\n⚠️ This action cannot be undone!", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Delete user button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

@bot.message_handler(func=lambda message: message.text == "📋 ADMIN LOGS")
@force_join_decorator
def admin_logs_button_handler(message):
    try:
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied!")
            return
        admin_logs_command(message, bot)
    except Exception as e:
        logger.error(f"Admin logs button error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ OSINT BUTTONS ============

@bot.message_handler(func=lambda message: message.text == "📱 PHONE")
@force_join_decorator
def phone_osint_button(message):
    bot.reply_to(message, "📱 Enter phone number:\n<code>91xxxxxxxxxx</code>", parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text == "🆔 AADHAAR")
@force_join_decorator
def aadhaar_osint_button(message):
    bot.reply_to(message, "🆔 Enter Aadhaar number:\n<code>12 digits</code> only", parse_mode='HTML')

# ============ TEXT HANDLER ============

@bot.message_handler(func=lambda message: True, content_types=['text'])
@rate_limited
@force_join_decorator
def handle_text(message):
    try:
        user_id = message.from_user.id
        text = message.text.strip()
        
        if text.startswith('/'):
            return
        
        buttons = ["📱 PHONE SEARCH", "🆔 AADHAAR SEARCH", "👤 PROFILE", 
                   "💰 REFER & EARN", "🎁 DAILY BONUS", "📜 HISTORY", 
                   "🛍 BUY PREMIUM", "📞 SUPPORT", "👑 ADMIN", 
                   "◀️ BACK", "📊 STATS", "👥 USERS", "📢 BROADCAST", 
                   "🎫 GEN CODE", "💎 ADD TOKENS", "🎁 GIVE SUBSCRIPTION",
                   "🚫 BAN", "✅ UNBAN", "🗑️ DELETE USER", "📋 ADMIN LOGS",
                   "📱 PHONE", "🆔 AADHAAR"]
        if text in buttons:
            return
        
        search_type, query = detect_search_type(text)
        
        if search_type == 'unknown':
            bot.reply_to(message, """
<b>❌ INVALID INPUT</b>
━━━━━━━━━━━━━━━━━━━━━━━━

<b>📱</b> Phone: <code>91xxxxxxxxxx</code>
<b>🆔</b> Aadhaar: <code>12 digits</code>

Use <code>/help</code> for commands
""", parse_mode='HTML')
            return
        
        executor.submit(perform_search, message, query, search_type)
    except Exception as e:
        logger.error(f"Text handler error: {e}")

# ============ START BACKUP MANAGER ============
try:
    backup_manager = BackupManager(BOT_TOKEN, OWNER_IDS, DATABASE_FILE)
    backup_manager.start()
    logger.info("✅ Backup Manager started")
except Exception as e:
    logger.error(f"❌ Backup Manager failed: {e}")

# ============ START BOT ============

def main():
    try:
        if not BOT_TOKEN:
            logger.error("❌ BOT_TOKEN not set!")
            return
        
        print("=" * 60)
        print("🔥 HACKERS DB - OSINT BOT v3.0")
        print("✅ FORCE JOIN CHANNEL - ACTIVATED")
        print(f"👑 Owners: {OWNER_IDS}")
        print(f"👥 Admins: {ADMIN_IDS}")
        if FORCE_CHANNEL:
            print(f"📢 Force Channel: @{FORCE_CHANNEL}")
        else:
            print("📢 Force Channel: DISABLED")
        print("=" * 60)
        print("✅ Bot started successfully!")
        print("📦 Auto Backup: EVERY 23 HOURS")
        print("📊 HTML Parse Mode - 100% Safe")
        print("⚠️ Press Ctrl+C to stop")
        
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except KeyboardInterrupt:
        print("\n⏹️ Bot stopped by user")
        try:
            backup_manager.stop()
        except:
            pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()