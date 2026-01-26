import os
from dotenv import load_dotenv

load_dotenv()

# Plaid configuration
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")

# Anthropic configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Database configuration (use DATA_DIR for Railway volume mount)
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(__file__))
DATABASE_PATH = os.path.join(DATA_DIR, "spend_tracker.db")

# Plaid access tokens storage
ACCESS_TOKENS_PATH = os.path.join(DATA_DIR, "plaid_tokens.json")

# Web app configuration
WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "5001"))  # Railway sets PORT automatically

# Sync interval in minutes
SYNC_INTERVAL_MINUTES = 15
