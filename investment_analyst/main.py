"""텔레그램 봇 entry point

사용법:
    python -m investment_analyst.main

명령:
    /start   — 봇 소개
    /report TICKER — 종합 투자분석 리포트 (전문 + 쉬운 버전)
    /easy TICKER — 쉬운 버전만 조회
    /history TICKER — 최근 분석 이력 조회
    /help    — 사용법 안내
    텍스트 입력 (1-5자 알파벳) — 티커로 인식하여 전체 분석
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
from .context import InvestmentContext
from .database import init_db, get_latest_reports

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── 메시지 분할 유틸 ──

def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """텔레그램 메시지 길이 제한에 맞게 분할."""
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    lines = text.split("\n")
    current = ""
    for line in lines:
        # 단일 라인이 max_len 초과 시 강제 분할
        while len(line) > max_len:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:max_len])
            line = line[max_len:]

        if current and len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        parts.append(current)
    return parts


# ── 핸들러 ──

def _get_msg(update: Update):
    """DM이든 채널 포스트든 effective_message 반환."""
    return update.effective_message


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """봇 소개."""
    await _get_msg(update).reply_text(
        "Investment Analyst Bot\n\n"
        "티커를 입력하면 종합 투자분석 리포트를 생성합니다.\n"
        "(주가 + 밸류에이션 + 재무제표 + 어닝콜)\n\n"
        "사용법:\n"
        "  NVDA — 티커 직접 입력 (전체 분석)\n"
        "  /report NVDA — 전체 분석\n"
        "  /easy NVDA — 쉬운 버전만\n"
        "  /history NVDA — 최근 분석 이력\n"
        "  /help — 도움말"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """도움말."""
    await _get_msg(update).reply_text(
        "사용법\n\n"
        "TICKER — 티커 직접 입력 (1-5자 알파벳)\n"
        "/report TICKER — 종합 투자분석 리포트\n"
        "/easy TICKER — 쉬운 버전만 조회\n"
        "/history TICKER — 최근 분석 이력\n\n"
        "예시: NVDA, AAPL, MSFT, GOOGL, TSLA"
    )


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/report TICKER — 전체 분석."""
    if context.args:
        ticker = context.args[0].upper()
    else:
        await _get_msg(update).reply_text("사용법: /report TICKER\n예시: /report NVDA")
        return
    await _run_analysis(update, ticker)


async def cmd_easy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/easy TICKER — 쉬운 버전만."""
    if context.args:
        ticker = context.args[0].upper()
    else:
        await _get_msg(update).reply_text("사용법: /easy TICKER\n예시: /easy NVDA")
        return
    await _run_analysis(update, ticker, easy_only=True)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/history TICKER — 최근 분석 이력."""
    if not context.args:
        await _get_msg(update).reply_text("사용법: /history TICKER\n예시: /history NVDA")
        return

    ticker = context.args[0].upper()
    reports = await get_latest_reports(ticker, limit=5)
    if not reports:
        await _get_msg(update).reply_text(f"{ticker} 분석 이력이 없습니다.")
        return

    lines = [f"{ticker} 최근 분석 이력\n"]
    for r in reports:
        rtype = r["report_type"]
        created = r["created_at"][:16]
        preview = r["report_text"][:100].replace("\n", " ")
        lines.append(f"[{created}] ({rtype})\n{preview}...\n")

    await _get_msg(update).reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 텍스트 — 1-5자 알파벳이면 티커로 인식."""
    msg = _get_msg(update)
    text = (msg.text or "").strip().upper()
    if text.isalpha() and 1 <= len(text) <= 5:
        await _run_analysis(update, text)


# ── 분석 실행 ──

def _is_channel_post(update: Update) -> bool:
    """채널에서 온 메시지인지 판별."""
    return update.channel_post is not None


async def _run_analysis(update: Update, ticker: str, easy_only: bool = False) -> None:
    """에이전트 파이프라인을 실행하고 결과를 전송."""
    msg = _get_msg(update)
    from_channel = _is_channel_post(update)

    status_msg = await msg.reply_text(f"{ticker} 종합 투자분석 중... (1-3분 소요)")

    try:
        ic = InvestmentContext(ticker=ticker)

        result = await Runner.run(
            starting_agent=orchestrator_agent,
            input=f"Analyze {ticker} for a comprehensive investment report",
            context=ic,
            max_turns=30,
        )

        # 상태 메시지 삭제
        try:
            await status_msg.delete()
        except Exception:
            pass

        # 전문 리포트 전송 (easy_only가 아닌 경우)
        if not easy_only and ic.professional_report:
            parts = _split_message(ic.professional_report)
            for part in parts:
                await msg.reply_text(part)

        # 차트 이미지 전송
        if not easy_only:
            if ic.quarterly_chart:
                await msg.reply_photo(
                    photo=ic.quarterly_chart,
                    caption=f"📊 {ticker} Quarterly Financials",
                )
            if ic.annual_chart:
                await msg.reply_photo(
                    photo=ic.annual_chart,
                    caption=f"📊 {ticker} Annual Trend",
                )

        # 쉬운 리포트 전송
        if ic.easy_report:
            if not easy_only:
                await msg.reply_text("─" * 20 + "\n📘 쉬운 버전\n" + "─" * 20)
            parts = _split_message(ic.easy_report)
            for part in parts:
                await msg.reply_text(part)

        # 리포트 없는 경우
        if not ic.professional_report and not ic.easy_report:
            fallback = result.final_output or "분석 결과를 생성하지 못했습니다."
            await msg.reply_text(fallback)

        # 에러가 있었으면 알림
        if ic.errors:
            error_text = "\n".join(f"⚠️ {e}" for e in ic.errors)
            await msg.reply_text(f"일부 데이터 수집 중 문제 발생:\n{error_text}")

        # DM에서 온 경우 채널에도 전송
        if not from_channel and ic.easy_report:
            try:
                # 채널에는 쉬운 버전만 전송
                channel_parts = _split_message(ic.easy_report)
                for part in channel_parts:
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

async def _on_startup(app):
    """봇 시작 시 DB 초기화."""
    await init_db()
    logger.info("DB 초기화 완료")


def main() -> None:
    """봇 시작."""
    from .config import validate_config
    validate_config()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.post_init = _on_startup

    # DM 핸들러
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("easy", cmd_easy))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 채널 포스트 핸들러
    channel_filter = filters.UpdateType.CHANNEL_POST
    app.add_handler(CommandHandler("report", cmd_report, filters=channel_filter))
    app.add_handler(CommandHandler("easy", cmd_easy, filters=channel_filter))
    app.add_handler(MessageHandler(channel_filter & filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Investment Analyst Bot starting...")
    app.run_polling(allowed_updates=[
        UpdateType.MESSAGE,
        UpdateType.CHANNEL_POST,
    ])


if __name__ == "__main__":
    main()
