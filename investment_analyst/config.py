"""설정 관리 — 환경변수에서 API 키, 봇 토큰 등 로드"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 파일 로드 (investment_analyst/.env 우선, 없으면 상위)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@lweaifn")

# SEC EDGAR API 요청 시 필수 User-Agent
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "InvestmentAnalyst/1.0 (contact@example.com)")

# SQLite DB 경로 (Docker 볼륨 마운트 시 환경변수로 재지정 가능)
DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "investment_data.db")))


def validate_config():
    """필수 환경변수 검증."""
    missing = []
    if not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if missing:
        raise RuntimeError(
            f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing)}\n"
            f".env 파일을 확인해주세요."
        )
