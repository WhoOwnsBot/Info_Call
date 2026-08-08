"""
Admin Commands for OSINT Bot - HTML Mode
NO MORE "can't parse" ERRORS
"""

import logging
import time
import re
from datetime import datetime
from telebot import types
from config import ADMIN_IDS, OWNER_IDS
from database import db
import threading

logger = logging.getLogger(__name__)
db_lock = threading.Lock()

# ============ HTML ESCAPE FUNCTION ============

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

# ============ DECORATORS ============

def admin_only(func):
    def wrapper(message, bot):
        user_id = message.from_user.id
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Access Denied! You are not an admin.")
            return
        return func(message, bot)
    return wrapper

def owner_only(func):
    def wrapper(message, bot):
        user_id = message.from_user.id
        if user_id not in OWNER_IDS:
            bot.reply_to(message, "❌ Owner Only!")
            return
        return func(message, bot)
    return wrapper

def log_admin_action(action: str, user_id: int, details: str):
    logger.warning(f"👑 ADMIN ACTION: {action} - User: {user_id} - {details}")
    try:
        db.add_admin_log(user_id, action, details)
    except:
        pass

# ============ ADMIN KEYBOARDS ============

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [
        types.KeyboardButton("📊 STATS"),
        types.KeyboardButton("👥 USERS"),
        types.KeyboardButton("📢 BROADCAST"),
        types.KeyboardButton("🎫 GEN CODE"),
        types.KeyboardButton("💎 ADD TOKENS"),
        types.KeyboardButton("🎁 GIVE SUBSCRIPTION"),
        types.KeyboardButton("🚫 BAN"),
        types.KeyboardButton("✅ UNBAN"),
        types.KeyboardButton("🗑️ DELETE USER"),
        types.KeyboardButton("📋 ADMIN LOGS"),
        types.KeyboardButton("◀️ BACK"),
    ]
    markup.add(*buttons)
    return markup

# ============ MAIN ADMIN COMMANDS ============

@admin_only
def admin_panel(message, bot):
    admin_msg = """
👑 ADMIN PANEL
━━━━━━━━━━━━━━━━━━━━━━━━

📊 /stats     - Bot Statistics
👥 /users     - All Users List
📢 /broadcast - Send Broadcast
🎫 /gen       - Generate Premium Code
💎 /addtokens - Add Tokens
🎁 /givesub   - Give Subscription
🚫 /ban       - Ban User
✅ /unban     - Unban User
🗑️ /deleteuser - Delete User
📋 /adminlogs - View Admin Logs

📌 Use buttons below for quick access
"""
    bot.reply_to(message, admin_msg, parse_mode='HTML',
                reply_markup=get_admin_keyboard())
    log_admin_action('admin_panel', message.from_user.id, 'Admin panel accessed')

# ============ STATISTICS ============

@admin_only
def stats_command(message, bot):
    try:
        with db_lock:
            total_users = db.get_user_count()
            premium_users = db.get_premium_count()
            
            history = db.execute_raw_query("SELECT COUNT(*) FROM search_history")
            total_searches = history[0]['COUNT(*)'] if history else 0
            
            ref_stats = db.execute_raw_query("SELECT COUNT(*) FROM referral_logs")
            total_refs = ref_stats[0]['COUNT(*)'] if ref_stats else 0
            
            today = datetime.now().strftime("%Y-%m-%d")
            today_searches = db.execute_raw_query(
                "SELECT COUNT(*) FROM search_history WHERE date(timestamp) = ?", 
                (today,)
            )
            today_count = today_searches[0]['COUNT(*)'] if today_searches else 0
            
            banned = db.execute_raw_query("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            banned_count = banned[0]['COUNT(*)'] if banned else 0
        
        stats = f"""
📊 BOT STATISTICS
━━━━━━━━━━━━━━━━━━━━━━━━

👥 Total Users: {total_users}
💎 Premium Users: {premium_users}
📄 Free Users: {total_users - premium_users}
🚫 Banned Users: {banned_count}

🔍 Total Searches: {total_searches}
📊 Today's Searches: {today_count}
💰 Total Referrals: {total_refs}

📅 Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        bot.reply_to(message, stats, parse_mode='HTML')
        log_admin_action('stats', message.from_user.id, 'Statistics viewed')
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ USERS LIST - BEAUTIFUL ============

@admin_only
def users_command(message, bot):
    try:
        args = message.text.split()
        page = 1
        if len(args) > 1:
            try:
                page = int(args[1])
                if page < 1:
                    page = 1
            except ValueError:
                page = 1
        
        limit = 10
        offset = (page - 1) * limit
        
        with db_lock:
            users = db.get_all_users(limit=limit, offset=offset)
            total_users = db.get_user_count()
        
        if not users:
            bot.reply_to(message, "📭 No users found!")
            return
        
        total_pages = (total_users // limit) + (1 if total_users % limit > 0 else 0)
        
        msg = f"""
<b>👥 USERS LIST</b>
<b>📊 Total:</b> {total_users} Users  |  <b>📄 Page:</b> {page}/{total_pages}
━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        rank_emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for idx, user in enumerate(users, offset + 1):
            is_premium = False
            if user.get('subscription_end'):
                try:
                    sub_end = datetime.strptime(user['subscription_end'], "%Y-%m-%d %H:%M:%S")
                    is_premium = sub_end > datetime.now()
                except:
                    pass
            
            status = "💎" if is_premium else "📄"
            banned = "🚫" if user.get('is_banned', 0) == 1 else ""
            
            # Get username
            username = user.get('username', 'N/A')
            first_name = user.get('first_name', '')
            
            # Show name with username
            if first_name:
                display_name = first_name
                if username and username != 'N/A':
                    display_name += f" (@{username})"
            elif username and username != 'N/A':
                display_name = f"@{username}"
            else:
                display_name = "No Username"
            
            rank = rank_emojis[(idx - 1) % len(rank_emojis)] if idx <= 10 else f"{idx}."
            
            msg += f"""
{rank} {status}{banned} <b>ID:</b> <code>{user.get('user_id', 'N/A')}</code>
    ├ <b>Name:</b> {escape_html(display_name)}
    ├ <b>Tokens:</b> {user.get('tokens', 0)}
    ├ <b>Referrals:</b> {user.get('referral_count', 0)}
    └ <b>Searches:</b> {user.get('total_requests', 0)}
"""
        
        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━"
        
        if total_pages > 1:
            nav = ""
            if page > 1:
                nav += f"◀️ /users {page-1}  "
            if page < total_pages:
                nav += f"/users {page+1} ▶️"
            msg += f"\n📌 {nav}"
        
        bot.reply_to(message, msg, parse_mode='HTML')
        log_admin_action('users_list', message.from_user.id, f'Viewed users page {page}')
        
    except Exception as e:
        logger.error(f"Users error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ GIVE SUBSCRIPTION ============

@admin_only
def give_subscription_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: /givesub USER_ID DURATION\n"
                                "Duration: 1hour, 1day, 7day, 15day, 30day\n"
                                "Example: /givesub 123456789 30day")
            return
        
        try:
            target_id = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID! Must be a number.")
            return
        
        duration_str = args[2].lower()
        
        duration_map = {
            '1hour': (1, 'hours'),
            '1day': (1, 'days'),
            '7day': (7, 'days'),
            '15day': (15, 'days'),
            '30day': (30, 'days')
        }
        
        if duration_str not in duration_map:
            bot.reply_to(message, "❌ Invalid duration! Use: 1hour, 1day, 7day, 15day, 30day")
            return
        
        duration, unit = duration_map[duration_str]
        duration_days = duration if unit == 'days' else duration / 24
        
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            if user.get('is_banned', 0) == 1:
                bot.reply_to(message, f"⚠️ User {target_id} is banned!")
                return
            
            success = db.set_subscription(target_id, duration_days)
            
            if not success:
                bot.reply_to(message, "❌ Failed to set subscription!")
                return
            
            new_end = db.get_subscription_end(target_id)
        
        bot.reply_to(message, f"""
🎁 SUBSCRIPTION ADDED!
━━━━━━━━━━━━━━━━━━━━━━━━

User: <code>{target_id}</code>
Duration: {duration} {unit}
Expires: {escape_html(new_end)}

✅ Subscription added successfully!
""", parse_mode='HTML')
        
        try:
            bot.send_message(target_id, 
                f"🎉 You received {duration} {unit} of premium subscription from admin!\n"
                f"📅 Expires: {new_end}\n"
                f"🔓 Enjoy unlimited searches!")
        except:
            pass
        
        log_admin_action('give_subscription', message.from_user.id, 
                        f'Gave {duration} {unit} subscription to {target_id}')
        
    except Exception as e:
        logger.error(f"Give subscription error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ REMOVE SUBSCRIPTION ============

@admin_only
def remove_subscription_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /removesub USER_ID\nExample: /removesub 123456789")
            return
        
        try:
            target_id = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID! Must be a number.")
            return
        
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            db.update_user(target_id, subscription_end=None)
        
        bot.reply_to(message, f"""
❌ SUBSCRIPTION REMOVED!
━━━━━━━━━━━━━━━━━━━━━━━━

User: <code>{target_id}</code>
Subscription removed successfully!
""", parse_mode='HTML')
        
        log_admin_action('remove_subscription', message.from_user.id, f'Removed subscription from {target_id}')
        
    except Exception as e:
        logger.error(f"Remove subscription error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ ADD TOKENS ============

@admin_only
def add_tokens_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: /addtokens USER_ID AMOUNT\nExample: /addtokens 123456789 10")
            return
        
        try:
            target_id = int(args[1])
            amount = int(args[2])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID or AMOUNT! Must be numbers.")
            return
        
        if amount <= 0 or amount > 10000:
            bot.reply_to(message, "❌ Amount must be between 1 and 10000")
            return
        
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            if user.get('is_banned', 0) == 1:
                bot.reply_to(message, f"⚠️ User {target_id} is banned!")
                return
            
            db.add_tokens(target_id, amount)
            new_tokens = db.get_tokens(target_id)
        
        bot.reply_to(message, f"""
✅ TOKENS ADDED!
━━━━━━━━━━━━━━━━━━━━━━━━

User: <code>{target_id}</code>
Added: +{amount} tokens
Total: {new_tokens} tokens
""", parse_mode='HTML')
        
        try:
            bot.send_message(target_id, 
                f"🎉 You received +{amount} tokens from admin!\n📊 Total: {new_tokens} tokens")
        except:
            pass
        
        log_admin_action('add_tokens', message.from_user.id, f'Added {amount} tokens to {target_id}')
        
    except Exception as e:
        logger.error(f"Add tokens error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ BAN ============

@admin_only
def ban_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /ban USER_ID [reason]\nExample: /ban 123456789 Spam")
            return
        
        try:
            target_id = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID! Must be a number.")
            return
        
        reason = ' '.join(args[2:]) if len(args) > 2 else 'No reason provided'
        
        if target_id in OWNER_IDS:
            bot.reply_to(message, "❌ Cannot ban an owner!")
            return
        
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            if user.get('is_banned', 0) == 1:
                bot.reply_to(message, f"⚠️ User {target_id} is already banned!")
                return
            
            db.update_user(target_id, is_banned=1, notes=f"Banned: {reason} | By: {message.from_user.id}")
        
        bot.reply_to(message, f"""
✅ USER BANNED!
━━━━━━━━━━━━━━━━━━━━━━━━

User: <code>{target_id}</code>
Reason: {escape_html(reason)}
""", parse_mode='HTML')
        
        try:
            bot.send_message(target_id, 
                f"🚫 You have been banned from using this bot!\nReason: {reason}\nContact: @Rahul_Neoo")
        except:
            pass
        
        log_admin_action('ban', message.from_user.id, f'Banned user {target_id} - Reason: {reason}')
        
    except Exception as e:
        logger.error(f"Ban error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ UNBAN ============

@admin_only
def unban_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /unban USER_ID")
            return
        
        try:
            target_id = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID! Must be a number.")
            return
        
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            if user.get('is_banned', 0) == 0:
                bot.reply_to(message, f"⚠️ User {target_id} is not banned!")
                return
            
            db.update_user(target_id, is_banned=0, notes=user.get('notes', '').replace("Banned: ", "Unbanned: "))
        
        bot.reply_to(message, f"""
✅ USER UNBANNED!
━━━━━━━━━━━━━━━━━━━━━━━━

User: <code>{target_id}</code>
""", parse_mode='HTML')
        
        try:
            bot.send_message(target_id, 
                f"✅ You have been unbanned! You can now use the bot again.")
        except:
            pass
        
        log_admin_action('unban', message.from_user.id, f'Unbanned user {target_id}')
        
    except Exception as e:
        logger.error(f"Unban error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ DELETE USER ============

@admin_only
def delete_user_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /deleteuser USER_ID\n⚠️ This will permanently delete the user!")
            return
        
        try:
            target_id = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Invalid USER_ID! Must be a number.")
            return
        
        if target_id in OWNER_IDS:
            bot.reply_to(message, "❌ Cannot delete an owner!")
            return
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Confirm Delete", callback_data=f"confirm_delete_{target_id}"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_delete")
        )
        
        bot.reply_to(message, 
            f"⚠️ Are you sure you want to delete user <code>{target_id}</code>?\nThis action cannot be undone!",
            parse_mode='HTML', reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Delete user error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

def confirm_delete_user(message, bot, target_id):
    try:
        with db_lock:
            user = db.get_user(target_id)
            if not user:
                bot.reply_to(message, f"❌ User {target_id} not found!")
                return
            
            db.delete_user(target_id)
        
        bot.reply_to(message, f"✅ User <code>{target_id}</code> has been permanently deleted!", parse_mode='HTML')
        log_admin_action('delete_user', message.from_user.id, f'Deleted user {target_id}')
        
    except Exception as e:
        logger.error(f"Confirm delete error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ GENERATE CODE ============

@admin_only
def gen_code_command(message, bot):
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /gen 1hour|1day|7day|15day|30day")
            return
        
        plan = args[1].lower()
        plans = {
            '1hour': (1, 'hours'),
            '1day': (1, 'days'),
            '7day': (7, 'days'),
            '15day': (15, 'days'),
            '30day': (30, 'days')
        }
        
        if plan not in plans:
            bot.reply_to(message, "❌ Invalid plan! Use: 1hour, 1day, 7day, 15day, 30day")
            return
        
        duration, unit = plans[plan]
        
        with db_lock:
            code = db.generate_code(duration, unit, message.from_user.id)
        
        if code:
            bot.reply_to(message, f"""
🎫 CODE GENERATED!
━━━━━━━━━━━━━━━━━━━━━━━━

Code: <code>{escape_html(code)}</code>
Duration: {duration} {unit}

Send to user: /redeem {escape_html(code)}
""", parse_mode='HTML')
            log_admin_action('gen_code', message.from_user.id, f'Generated {plan} code: {code}')
        else:
            bot.reply_to(message, "❌ Failed to generate code")
            
    except Exception as e:
        logger.error(f"Gen code error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ BROADCAST ============

@owner_only
def broadcast_command(message, bot):
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            bot.reply_to(message, "📢 Usage: /broadcast Your message here")
            return
        
        broadcast_msg = args[1]
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Send", callback_data="broadcast_confirm"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
        )
        
        bot.reply_to(message, 
            f"📢 Broadcast Preview:\n\n{broadcast_msg}\n\nSend to all users?",
            reply_markup=markup)
        
        verification_data['broadcast'] = {
            'message': broadcast_msg,
            'user_id': message.from_user.id
        }
        
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ ADMIN LOGS - BEAUTIFUL WITH NAMES ============

@admin_only
def admin_logs_command(message, bot):
    try:
        with db_lock:
            logs = db.get_admin_logs(100)
        
        if not logs:
            bot.reply_to(message, "📭 No admin logs found")
            return
        
        # ====== GROUP BY ACTION TYPE ======
        grouped_logs = {}
        for log in logs:
            action = log.get('action', 'N/A')
            if action not in grouped_logs:
                grouped_logs[action] = []
            grouped_logs[action].append(log)
        
        msg = f"""
<b>📋 ADMIN LOGS</b>
<b>📊 Total Actions:</b> {len(grouped_logs)} Types
━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        action_emojis = {
            'admin_panel': '👑',
            'stats': '📊',
            'users_list': '👥',
            'add_tokens': '💎',
            'deduct_tokens': '📉',
            'ban': '🚫',
            'unban': '✅',
            'delete_user': '🗑️',
            'give_subscription': '🎁',
            'remove_subscription': '❌',
            'gen_code': '🎫',
            'broadcast': '📢',
            'broadcast_photo': '🖼️',
            'stats_view': '📊',
            'admin_logs': '📋',
            'user_info': 'ℹ️',
        }
        
        for idx, (action, action_logs) in enumerate(grouped_logs.items(), 1):
            first_log = action_logs[0]
            admin_id = first_log.get('admin_id', 'N/A')
            details = first_log.get('details', 'N/A')
            timestamp = first_log.get('timestamp', 'N/A')
            count = len(action_logs)
            
            # ====== GET ADMIN NAME ======
            admin_name = "Unknown Admin"
            try:
                admin_user = db.get_user(admin_id)
                if admin_user:
                    first_name = admin_user.get('first_name', '')
                    username = admin_user.get('username', '')
                    if first_name:
                        admin_name = first_name
                        if username:
                            admin_name += f" (@{username})"
                    elif username:
                        admin_name = f"@{username}"
                    else:
                        admin_name = f"ID: {admin_id}"
                else:
                    admin_name = f"ID: {admin_id}"
            except:
                admin_name = f"ID: {admin_id}"
            
            # ====== REPLACE USER ID WITH NAME IN DETAILS ======
            # Find all user IDs in details and replace with names
            user_ids = re.findall(r'\b(\d{7,})\b', details)
            for uid in user_ids:
                try:
                    target_id = int(uid)
                    target_user = db.get_user(target_id)
                    if target_user:
                        first_name = target_user.get('first_name', '')
                        username = target_user.get('username', '')
                        if first_name:
                            name_display = first_name
                            if username:
                                name_display += f" (@{username})"
                        elif username:
                            name_display = f"@{username}"
                        else:
                            name_display = f"ID: {target_id}"
                        details = details.replace(uid, name_display)
                except:
                    pass
            
            # ====== REPLACE ADMIN ID WITH NAME IN DETAILS ======
            if str(admin_id) in details:
                try:
                    admin_user = db.get_user(admin_id)
                    if admin_user:
                        first_name = admin_user.get('first_name', '')
                        username = admin_user.get('username', '')
                        if first_name:
                            admin_display = first_name
                            if username:
                                admin_display += f" (@{username})"
                        elif username:
                            admin_display = f"@{username}"
                        else:
                            admin_display = f"ID: {admin_id}"
                        details = details.replace(str(admin_id), admin_display)
                except:
                    pass
            
            emoji = action_emojis.get(action, '📌')
            
            msg += f"""
{emoji} <b>{idx}. {escape_html(action)}</b> <i>({count} times)</i>
    ├ <b>Admin:</b> {escape_html(admin_name)}
    ├ <b>Details:</b> {escape_html(details)}
    └ <b>Last:</b> {escape_html(timestamp)}
"""
        
        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━"
        msg += "\n📌 Each action type shown only once with names"
        
        bot.reply_to(message, msg, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Admin logs error: {e}")
        bot.reply_to(message, f"❌ Error: {str(e)[:100]}")

# ============ CALLBACK HANDLERS ============

def handle_admin_callbacks(call, bot):
    try:
        user_id = call.from_user.id
        
        if user_id not in ADMIN_IDS and user_id not in OWNER_IDS:
            bot.answer_callback_query(call.id, "❌ Access Denied!", show_alert=True)
            return
        
        if call.data == 'broadcast_confirm':
            broadcast_data = verification_data.get('broadcast', {})
            msg = broadcast_data.get('message', '')
            
            if not msg:
                bot.answer_callback_query(call.id, "❌ No broadcast message found")
                return
            
            bot.answer_callback_query(call.id, "📢 Starting broadcast...")
            
            with db_lock:
                users = db.get_all_users(limit=99999)
            
            sent = 0
            failed = 0
            
            for user in users:
                try:
                    bot.send_message(user['user_id'], 
                        f"📢 ANNOUNCEMENT\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n{msg}")
                    sent += 1
                    time.sleep(0.05)
                except:
                    failed += 1
            
            bot.edit_message_text(
                f"✅ Broadcast Complete!\n\n📊 Sent: {sent}\n❌ Failed: {failed}",
                call.message.chat.id, call.message.message_id
            )
            log_admin_action('broadcast', user_id, f"Sent broadcast to {sent} users")
            
        elif call.data == 'broadcast_cancel':
            bot.edit_message_text("❌ Broadcast cancelled", 
                call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Cancelled")
            
        elif call.data.startswith('confirm_delete_'):
            target_id = int(call.data.split('_')[2])
            confirm_delete_user(call.message, bot, target_id)
            bot.answer_callback_query(call.id, "✅ User deleted!")
            
        elif call.data == 'cancel_delete':
            bot.edit_message_text("❌ Deletion cancelled", 
                call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Cancelled")
            
        verification_data.pop('broadcast', None)
        verification_data.pop('broadcast_photo', None)
        
    except Exception as e:
        logger.error(f"Admin callback error: {e}")
        bot.answer_callback_query(call.id, f"❌ Error", show_alert=True)

# ============ VARIABLES ============
verification_data = {}

# ============ EXPORTS ============
__all__ = [
    'admin_panel',
    'stats_command', 
    'users_command',
    'give_subscription_command',
    'remove_subscription_command',
    'add_tokens_command',
    'ban_command',
    'unban_command',
    'delete_user_command',
    'confirm_delete_user',
    'gen_code_command',
    'broadcast_command',
    'admin_logs_command',
    'get_admin_keyboard',
    'handle_admin_callbacks',
    'verification_data'
]