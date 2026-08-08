import os
from dotenv import load_dotenv
import logging

load_dotenv()

# ============ VALIDATE ENVIRONMENT ============

def validate_env():
    """Validate all required environment variables"""
    required = ['BOT_TOKEN', 'API_URL', 'API_KEY']
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("Invalid BOT_TOKEN format")

validate_env()

# ============ LOAD CONFIGURATION ============

BOT_TOKEN = os.getenv('BOT_TOKEN')
API_URL = os.getenv('API_URL')
API_KEY = os.getenv('API_KEY')

def parse_ids(id_string):
    if not id_string:
        return []
    try:
        return [int(x.strip()) for x in id_string.split(',') if x.strip()]
    except ValueError:
        raise ValueError(f"Invalid ID format in: {id_string}")

OWNER_IDS = parse_ids(os.getenv('OWNER_IDS', ''))
ADMIN_IDS = parse_ids(os.getenv('ADMIN_IDS', ''))

if not OWNER_IDS:
    raise ValueError("At least one OWNER_ID must be configured")

# ============ FORCE JOIN SETTINGS ============
# ⚠️ Channel username WITHOUT @
FORCE_CHANNEL = os.getenv('FORCE_CHANNEL', '').replace('@', '')
FORCE_CHANNEL_LINK = os.getenv('FORCE_CHANNEL_LINK', '')

# ============ WORDLIST SYSTEM ============
WORDLIST_FOLDER = "collected_wordlists"
REQUIRED_UNIQUE = 500
CREDIT_REWARD = 1
COOLDOWN_SECONDS = 30
MAX_WORDS_PER_FILE = 5000

# ============ DATABASE ============
DATABASE_FILE = os.getenv('DATABASE_FILE', 'osint_bot.db')

# ============ SECURITY SETTINGS ============
MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_QUERY_LENGTH = 500
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_COOLDOWN = 30
MAX_HISTORY_LIMIT = 50
MAX_SEARCH_RESULTS = 5

# ============ LOGGING SETUP ============

def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format)
    
    LOG_FILE = os.getenv('LOG_FILE', 'bot.log')
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    logger = logging.getLogger()
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
    
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()
logger.info("✅ Configuration loaded successfully")
logger.info(f"👑 Owners: {OWNER_IDS}")
logger.info(f"👥 Admins: {ADMIN_IDS}")

if FORCE_CHANNEL:
    logger.info(f"📢 Force Channel: @{FORCE_CHANNEL}")
else:
    logger.info("📢 Force Channel: DISABLED")