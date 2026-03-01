"""텔레그램 봇 entry point

사용법:
    python -m earnings_call_agent.main

명령:
    /start   — 봇 소개
    /analyze TICKER — 어닝콜 분석
    /help    — 사용법 안내
    텍스트 입력 (1-5자 알파벳) — 티커로 인식하여 분석
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import UpdateType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents import Runner

from .agents_def import orchestrator_agent
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from .context import EarningsCallContext
from .report_formatter import split_message

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── 핸들러 (DM + 채널 공용) ──


def _get_msg(update: Update):
    """DM이든 채널 포스트든 effective_message 반환."""
    return update.effective_message


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """봇 소개 메시지."""
    await _get_msg(update).reply_text(
        "Earnings Call Summarizer Bot\n\n"
        "티커를 입력하면 최신 어닝콜을 분석합니다.\n\n"
        "사용법:\n"
        "  /analyze NVDA — 특정 티커 분석\n"
        "  AAPL — 티커 직접 입력\n"
        "  /help — 도움말"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """도움말."""
    await _get_msg(update).reply_text(
        "사용법\n\n"
        "/analyze TICKER — 어닝콜 분석\n"
        "TICKER — 티커 직접 입력 (1-5자 알파벳)\n\n"
        "예시: /analyze NVDA, AAPL, MSFT, GOOGL"
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/analyze TICKER 명령 처리."""
    if context.args:
        ticker = context.args[0].upper()
    else:
        await _get_msg(update).reply_text("사용법: /analyze TICKER\n예시: /analyze NVDA")
        return

    await _run_analysis(update, ticker)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 텍스트 — 1-5자 알파벳이면 티커로 인식. DM + 채널 모두 동작."""
    msg = _get_msg(update)
    text = (msg.text or "").strip().upper()
    if text.isalpha() and 1 <= len(text) <= 5:
        await _run_analysis(update, text)


# ── 분석 실행 ──


def _is_channel_post(update: Update) -> bool:
    """채널에서 온 메시지인지 판별."""
    return update.channel_post is not None


async def _run_analysis(update: Update, ticker: str) -> None:
    """에이전트 파이프라인을 실행하고 결과를 전송."""
    msg = _get_msg(update)
    from_channel = _is_channel_post(update)

    status_msg = await msg.reply_text(f"{ticker} 어닝콜 분석 중...")

    try:
        ec = EarningsCallContext(ticker=ticker)

        result = await Runner.run(
            starting_agent=orchestrator_agent,
            input=f"Analyze the latest earnings call for {ticker}",
            context=ec,
        )

        report = ec.final_report or result.final_output or "분석 결과를 생성하지 못했습니다."

        # 상태 메시지 삭제
        try:
            await status_msg.delete()
        except Exception:
            pass

        parts = split_message(report)

        # 현재 채팅에 결과 전송
        for part in parts:
            await msg.reply_text(part)

        # DM에서 온 경우 채널에도 전송 (채널에서 온 경우 중복 방지)
        if not from_channel:
            try:
                for part in parts:
                    await update.get_bot().send_message(
                        chat_id=TELEGRAM_CHANNEL_ID, text=part
                    )
                logger.info(f"{ticker} 리포트를 채널 {TELEGRAM_CHANNEL_ID}에 전송 완료")
            except Exception as e:
                logger.warning(f"채널 전송 실패: {e}")

    except Exception as e:
        logger.error(f"분석 실패 ({ticker}): {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"분석 실패: {str(e)[:500]}")
        except Exception:
            await msg.reply_text(f"분석 실패: {str(e)[:500]}")


# ── 메인 ──


def main() -> None:
    """봇 시작."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # DM 핸들러
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 채널 포스트 핸들러
    channel_filter = filters.UpdateType.CHANNEL_POST
    app.add_handler(CommandHandler("analyze", cmd_analyze, filters=channel_filter))
    app.add_handler(MessageHandler(channel_filter & filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Earnings Call Summarizer Bot starting...")
    app.run_polling(allowed_updates=[
        UpdateType.MESSAGE,
        UpdateType.CHANNEL_POST,
    ])


if __name__ == "__main__":
    main()
