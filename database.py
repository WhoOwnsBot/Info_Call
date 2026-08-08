import sqlite3
import threading
import json
import re
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)

# Import config
from config import OWNER_IDS

class SecureDatabase:
    """Fully secure database with SQL injection protection"""
    
    ALLOWED_COLUMNS = {
        'username': str,
        'first_name': str,
        'last_name': str,
        'subscription_end': str,
        'tokens': int,
        'total_requests': int,
        'last_daily_claim': str,
        'last_token_reset': str,
        'is_banned': int,
        'notes': str,
        'referred_by': int,
        'referral_count': int,
        'referral_code': str
    }
    
    READONLY_COLUMNS = {'user_id', 'registration_date'}
    
    def __init__(self, db_file='osint_bot.db'):
        self.db_file = db_file
        self._local = threading.local()
        self.init_db()
        self.migrate_db()
        logger.info(f"✅ Database initialized: {db_file}")
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_file, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # USERS TABLE
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                subscription_end TEXT,
                tokens INTEGER DEFAULT 3,
                registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
                total_requests INTEGER DEFAULT 0,
                last_daily_claim TEXT,
                last_token_reset TEXT,
                is_banned INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                referred_by INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referral_code TEXT DEFAULT ''
            )''')
            
            # Indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_username ON users(username)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_subscription ON users(subscription_end)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_banned ON users(is_banned)")
            
            # REDEEM CODES TABLE
            c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                duration_days REAL,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                used_by INTEGER,
                used_at TEXT,
                is_used INTEGER DEFAULT 0
            )''')
            
            # SEARCH HISTORY TABLE
            c.execute('''CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                query TEXT,
                search_type TEXT,
                result_count INTEGER DEFAULT 0,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # REFERRAL LOGS TABLE
            c.execute('''CREATE TABLE IF NOT EXISTS referral_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                tokens_earned INTEGER DEFAULT 3,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # ADMIN LOGS TABLE
            c.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            conn.commit()
            logger.info("✅ Database tables created/verified")
    
    def migrate_db(self):
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                c.execute("PRAGMA table_info(users)")
                columns = [col[1] for col in c.fetchall()]
                
                if 'referral_code' not in columns:
                    c.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT ''")
                    import random, string
                    c.execute("SELECT user_id FROM users WHERE referral_code = '' OR referral_code IS NULL")
                    users = c.fetchall()
                    for user in users:
                        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        c.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (code, user[0]))
                
                if 'referred_by' not in columns:
                    c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT 0")
                
                if 'referral_count' not in columns:
                    c.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
                
                conn.commit()
                logger.info("✅ Database migration complete")
                
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    # ============ USER METHODS ============
    
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = c.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def create_user(self, user_id: int, username: str = '', 
                   first_name: str = '', last_name: str = '') -> bool:
        if not user_id or user_id <= 0:
            return False
        
        import random
        import string
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                c.execute("""INSERT OR IGNORE INTO users 
                             (user_id, username, first_name, last_name, 
                              registration_date, last_token_reset, referral_code, tokens)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (user_id, username[:50], first_name[:50], last_name[:50], 
                           now, now, referral_code, 3))
                
                conn.commit()
                return c.rowcount > 0
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        if not user_id or user_id <= 0:
            return False
        
        validated_data = {}
        for key, value in kwargs.items():
            if key not in self.ALLOWED_COLUMNS:
                continue
            if key in self.READONLY_COLUMNS:
                continue
            
            expected_type = self.ALLOWED_COLUMNS[key]
            if not isinstance(value, expected_type):
                try:
                    value = expected_type(value)
                except:
                    continue
            
            validated_data[key] = value
        
        if not validated_data:
            return False
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                for key, value in validated_data.items():
                    c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", 
                             (value, user_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    def delete_user(self, user_id: int) -> bool:
        if not user_id or user_id <= 0:
            return False
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
                c.execute("DELETE FROM redeem_codes WHERE created_by = ? OR used_by = ?", 
                         (user_id, user_id))
                c.execute("DELETE FROM referral_logs WHERE referrer_id = ? OR referred_id = ?",
                         (user_id, user_id))
                c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                conn.commit()
                return c.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return False
    
    def get_all_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        if limit <= 0 or limit > 1000:
            limit = 100
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""SELECT user_id, username, first_name, last_name, 
                                   subscription_end, tokens, is_banned, referral_count
                            FROM users 
                            ORDER BY user_id 
                            LIMIT ? OFFSET ?""", (limit, offset))
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    def get_user_count(self) -> int:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM users")
                result = c.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting user count: {e}")
            return 0
    
    def get_premium_count(self) -> int:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM users WHERE subscription_end > datetime('now')")
                result = c.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting premium count: {e}")
            return 0
    
    # ============ TOKEN METHODS ============
    
    def is_owner(self, user_id: int) -> bool:
        return user_id in OWNER_IDS
    
    def is_premium(self, user_id: int) -> bool:
        if self.is_owner(user_id):
            return True
        
        user = self.get_user(user_id)
        if user and user.get('subscription_end'):
            try:
                sub_end = datetime.strptime(user['subscription_end'], "%Y-%m-%d %H:%M:%S")
                return sub_end > datetime.now()
            except:
                pass
        return False
    
    def get_subscription_end(self, user_id: int) -> Optional[str]:
        user = self.get_user(user_id)
        if user:
            return user.get('subscription_end')
        return None
    
    def set_subscription(self, user_id: int, duration_days: float) -> bool:
        user = self.get_user(user_id)
        if not user:
            return False
        
        now = datetime.now()
        current_end = user.get('subscription_end')
        if current_end:
            try:
                existing_end = datetime.strptime(current_end, "%Y-%m-%d %H:%M:%S")
                if existing_end > now:
                    new_end = existing_end + timedelta(days=duration_days)
                else:
                    new_end = now + timedelta(days=duration_days)
            except:
                new_end = now + timedelta(days=duration_days)
        else:
            new_end = now + timedelta(days=duration_days)
        
        new_end_str = new_end.strftime("%Y-%m-%d %H:%M:%S")
        return self.update_user(user_id, subscription_end=new_end_str)
    
    def get_tokens(self, user_id: int) -> int:
        if self.is_owner(user_id):
            return 999999
        
        user = self.get_user(user_id)
        return user.get('tokens', 0) if user else 0
    
    def update_tokens(self, user_id: int, tokens: int) -> bool:
        if self.is_owner(user_id):
            return True
        if tokens < 0:
            tokens = 0
        return self.update_user(user_id, tokens=tokens)
    
    def deduct_token(self, user_id: int) -> bool:
        if self.is_owner(user_id):
            return True
        
        tokens = self.get_tokens(user_id)
        if tokens > 0:
            return self.update_tokens(user_id, tokens - 1)
        return False
    
    def add_tokens(self, user_id: int, amount: int) -> bool:
        if self.is_owner(user_id):
            return True
        if amount <= 0:
            return False
        tokens = self.get_tokens(user_id)
        return self.update_tokens(user_id, tokens + amount)
    
    # ============ DAILY BONUS - 3 CREDITS ============
    
    def claim_daily(self, user_id: int) -> Tuple[bool, int]:
        if self.is_owner(user_id):
            return True, 999999
        
        user = self.get_user(user_id)
        if not user:
            return False, 0
        
        today = datetime.now().strftime("%Y-%m-%d")
        last_claim = user.get('last_daily_claim', '')
        
        if last_claim and last_claim.startswith(today):
            return False, user.get('tokens', 0)
        
        new_tokens = user.get('tokens', 0) + 3
        
        success = self.update_user(user_id, 
                                   tokens=new_tokens,
                                   last_daily_claim=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        if success:
            return True, new_tokens
        return False, 0
    
    # ============ REFERRAL SYSTEM ============
    
    def generate_referral_code(self, user_id: int) -> Optional[str]:
        import random
        import string
        
        user = self.get_user(user_id)
        if user and user.get('referral_code'):
            return user['referral_code']
        
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            existing = self.get_user_by_referral_code(code)
            if not existing:
                break
        
        self.update_user(user_id, referral_code=code)
        return code
    
    def get_user_by_referral_code(self, code: str) -> Optional[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE referral_code = ?", (code,))
                row = c.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting user by referral code: {e}")
            return None
    
    def process_referral(self, referred_user_id: int, referral_code: str) -> Tuple[bool, str]:
        if not referral_code:
            return False, "No referral code provided"
        
        user = self.get_user(referred_user_id)
        if user and user.get('referred_by', 0) > 0:
            return False, "You have already been referred!"
        
        referrer = self.get_user_by_referral_code(referral_code.upper())
        if not referrer:
            return False, "Invalid referral code!"
        
        referrer_id = referrer['user_id']
        
        if referrer_id == referred_user_id:
            return False, "You can't refer yourself!"
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                
                c.execute("UPDATE users SET referred_by = ? WHERE user_id = ?",
                         (referrer_id, referred_user_id))
                
                c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?",
                         (referrer_id,))
                
                current_tokens = self.get_tokens(referrer_id)
                c.execute("UPDATE users SET tokens = ? WHERE user_id = ?",
                         (current_tokens + 3, referrer_id))
                
                c.execute("""INSERT INTO referral_logs 
                             (referrer_id, referred_id, tokens_earned) 
                             VALUES (?, ?, ?)""",
                          (referrer_id, referred_user_id, 3))
                
                conn.commit()
                
                referrer_username = referrer.get('username', 'User')
                
                return True, f"✅ {referrer_username} got +3 tokens!"
        except Exception as e:
            logger.error(f"Error processing referral: {e}")
            return False, "Error processing referral"
    
    def get_referral_stats(self, user_id: int) -> Dict[str, Any]:
        user = self.get_user(user_id)
        if not user:
            return {'code': None, 'count': 0, 'tokens_earned': 0}
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM referral_logs WHERE referrer_id = ?", (user_id,))
                count_result = c.fetchone()
                count = count_result[0] if count_result else 0
                
                c.execute("SELECT SUM(tokens_earned) FROM referral_logs WHERE referrer_id = ?", (user_id,))
                tokens_result = c.fetchone()
                tokens = tokens_result[0] if tokens_result and tokens_result[0] else 0
                
                return {
                    'code': user.get('referral_code'),
                    'count': count,
                    'tokens_earned': tokens or 0
                }
        except Exception as e:
            logger.error(f"Error getting referral stats: {e}")
            return {'code': user.get('referral_code'), 'count': 0, 'tokens_earned': 0}
    
    # ============ SEARCH HISTORY ============
    
    def add_search_history(self, user_id: int, query: str, 
                          search_type: str, result_count: int) -> bool:
        if not user_id or not query:
            return False
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""INSERT INTO search_history 
                             (user_id, query, search_type, result_count) 
                             VALUES (?, ?, ?, ?)""",
                          (user_id, query[:200], search_type[:20], result_count))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding search history: {e}")
            return False
    
    def get_search_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        if limit <= 0 or limit > 100:
            limit = 10
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""SELECT query, search_type, result_count, timestamp 
                             FROM search_history 
                             WHERE user_id = ? 
                             ORDER BY timestamp DESC 
                             LIMIT ?""",
                          (user_id, limit))
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting search history: {e}")
            return []
    
    def clear_search_history(self, user_id: int) -> bool:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
                conn.commit()
                return c.rowcount > 0
        except Exception as e:
            logger.error(f"Error clearing search history: {e}")
            return False
    
    # ============ REDEEM CODES ============
    
    def generate_code(self, duration: int, unit: str, created_by: int) -> Optional[str]:
        import random
        import string
        
        if duration <= 0 or duration > 365:
            return None
        
        alphabet = string.ascii_uppercase + string.digits
        alphabet = alphabet.replace('O', '').replace('I', '').replace('0', '').replace('1', '')
        code = ''.join(random.choices(alphabet, k=12))
        
        duration_days = duration if unit == 'days' else duration / 24
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""INSERT INTO redeem_codes 
                             (code, duration_days, created_by) 
                             VALUES (?, ?, ?)""",
                          (code, duration_days, created_by))
                conn.commit()
                return code
        except Exception as e:
            logger.error(f"Error generating code: {e}")
            return None
    
    def redeem_code(self, code: str, user_id: int) -> Tuple[bool, Optional[str]]:
        code = code.upper().strip()
        if not code or len(code) != 12:
            return False, None
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM redeem_codes WHERE code = ? AND is_used = 0", (code,))
                row = c.fetchone()
                
                if row:
                    code_data = dict(row)
                    duration_days = code_data['duration_days']
                    
                    success = self.set_subscription(user_id, duration_days)
                    
                    if not success:
                        return False, None
                    
                    c.execute("""UPDATE redeem_codes 
                                SET used_by = ?, used_at = datetime('now'), is_used = 1 
                                WHERE code = ?""",
                             (user_id, code))
                    
                    conn.commit()
                    
                    if duration_days < 1:
                        hours = int(round(duration_days * 24))
                        display = f"{hours} hour(s)"
                    else:
                        days = int(duration_days)
                        display = f"{days} day(s)"
                    
                    return True, display
                
                return False, None
        except Exception as e:
            logger.error(f"Error redeeming code: {e}")
            return False, None
    
    def get_redeem_codes(self, created_by: Optional[int] = None) -> List[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                if created_by:
                    c.execute("SELECT * FROM redeem_codes WHERE created_by = ? ORDER BY created_at DESC", 
                             (created_by,))
                else:
                    c.execute("SELECT * FROM redeem_codes ORDER BY created_at DESC LIMIT 100")
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting codes: {e}")
            return []
    
    # ============ ADMIN LOGS ============
    
    def add_admin_log(self, admin_id: int, action: str, details: str = '') -> bool:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""INSERT INTO admin_logs (admin_id, action, details) 
                             VALUES (?, ?, ?)""",
                          (admin_id, action, details))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding admin log: {e}")
            return False
    
    def get_admin_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute("""SELECT * FROM admin_logs 
                             ORDER BY timestamp DESC LIMIT ?""", (limit,))
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error getting admin logs: {e}")
            return []
    
    def execute_raw_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if not query.strip().upper().startswith('SELECT'):
            return []
        
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute(query, params)
                return [dict(row) for row in c.fetchall()]
        except Exception as e:
            logger.error(f"Error executing raw query: {e}")
            return []

# Global database instance
db = SecureDatabase()