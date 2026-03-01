"""환경변수 및 설정 관리"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 파일 로드 (패키지 내부 우선, 없으면 상위)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

# OpenRouter API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# SEC EDGAR
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "ValueChainAnalyzer/1.0 (contact@example.com)")

# Google Drive
GOOGLE_CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
GOOGLE_TOKEN_PATH = Path(__file__).parent / "token.json"

# 다운로드 디렉토리
DOWNLOADS_DIR = Path(__file__).parent / "_downloads"

# SEC rate limit 설정
SEC_SEMAPHORE_LIMIT = 5
SEC_REQUEST_DELAY = 0.15  # 초


def validate_config():
    """필수 환경변수 검증."""
    missing = []
    if not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if missing:
        raise RuntimeError(
            f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing)}\n"
            f".env 파일을 확인해주세요."
        )
