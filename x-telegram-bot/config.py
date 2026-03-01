import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro-preview")

_allowed = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: list[int] = [int(x.strip()) for x in _allowed.split(",") if x.strip()]

WATCH_INTERVAL = int(os.getenv("WATCH_INTERVAL", "180"))
DEFAULT_FETCH_COUNT = int(os.getenv("DEFAULT_FETCH_COUNT", "5"))
MAX_FETCH_COUNT = int(os.getenv("MAX_FETCH_COUNT", "50"))

WATCH_DATA_FILE = os.path.join(os.path.dirname(__file__), "watch_data.json")

DAILY_CHANNEL = os.getenv("DAILY_CHANNEL", "")  # e.g. "@xpffprmfoadydir"
DAILY_HOUR = int(os.getenv("DAILY_HOUR", "8"))   # KST hour

# X (Twitter) internal API constants
X_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
X_GRAPHQL_USER_BY_SCREEN_NAME = "xc8f1g7BYqr6VTzTbvNlGw/UserByScreenName"
X_GRAPHQL_USER_TWEETS = "E3opETHurmVJflFsUBVuUQ/UserTweets"
