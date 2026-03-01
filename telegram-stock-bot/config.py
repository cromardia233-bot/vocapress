import os
from dotenv import load_dotenv

load_dotenv()

# Telegram User API
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Output channel
OUTPUT_CHANNEL = os.getenv("OUTPUT_CHANNEL", "")

# OpenAI / OpenRouter
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Daily digest settings
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "8"))
HISTORY_HOURS = int(os.getenv("HISTORY_HOURS", "24"))
MESSAGE_FETCH_LIMIT = int(os.getenv("MESSAGE_FETCH_LIMIT", "500"))

# Database (Docker 볼륨 마운트 시 환경변수로 재지정 가능)
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "bot.db"))

# 세션 파일 디렉토리 (Telethon 세션 파일 위치)
SESSION_DIR = os.getenv("SESSION_DIR", os.path.dirname(__file__))
