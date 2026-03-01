import asyncio
import logging
import os
import signal
import sys

from telethon import TelegramClient

import database as db
from monitor import DailyDigest
from bot_commands import register_commands
from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_PHONE,
    TELEGRAM_BOT_TOKEN,
    OUTPUT_CHANNEL,
    OPENAI_API_KEY,
    SESSION_DIR,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    # 설정 검증
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        logger.error("TELEGRAM_API_ID / TELEGRAM_API_HASH가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not OUTPUT_CHANNEL:
        logger.error("OUTPUT_CHANNEL이 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY가 설정되지 않았습니다. LLM 요약 기능이 동작하지 않습니다.")

    # DB 초기화
    await db.init_db()
    logger.info("데이터베이스 초기화 완료")

    # User API 클라이언트 (채널 히스토리 조회용)
    user_session_path = os.path.join(SESSION_DIR, "user_session")
    user_client = TelegramClient(user_session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await user_client.start(phone=TELEGRAM_PHONE)
    logger.info("User API 클라이언트 연결 완료")

    # Bot 클라이언트 (명령어 처리 + 메시지 전송용)
    bot_session_path = os.path.join(SESSION_DIR, "bot_session")
    bot_client = TelegramClient(bot_session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await bot_client.start(bot_token=TELEGRAM_BOT_TOKEN)
    logger.info("Bot 클라이언트 연결 완료")

    # 일일 요약 인스턴스
    digest = DailyDigest(user_client, bot_client)

    # 봇 명령어 등록 (digest 인스턴스 전달)
    register_commands(bot_client, digest)

    # 스케줄러 시작
    await digest.start()

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("종료 신호 수신, 정리 중...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("봇이 실행 중입니다. Ctrl+C로 종료합니다.")
    await stop_event.wait()

    # 정리
    await digest.stop()
    await bot_client.disconnect()
    await user_client.disconnect()
    logger.info("봇 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
