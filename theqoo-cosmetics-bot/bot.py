"""더쿠 화장품 텔레그램 봇 — 채널 자동 포스팅."""

import asyncio
import datetime
import html
import logging
from functools import partial

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from analyzer import (
    extract_and_record_mentions,
    get_recommend_report,
    get_skincare_report,
    get_trending_report,
)
from config import (
    CLEANUP_HOUR,
    CRAWL_INTERVAL_MINUTES,
    DAILY_DIGEST_HOUR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)
from database import (
    cleanup_old_data,
    get_recent_posts,
    init_db,
    is_post_seen,
    save_post,
)
from scraper import Post, TheqooScraper

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

scraper = TheqooScraper()


# ── 유틸리티 ──────────────────────────────────────────────────

def format_posts_html(posts: list[dict], title: str) -> str:
    """게시글 dict 목록을 텔레그램 HTML 메시지로 포맷한다."""
    if not posts:
        return ""

    lines = [f"<b>{title}</b>\n"]
    for i, p in enumerate(posts[:15], 1):
        safe_title = html.escape(p["title"])
        views_str = f'{p["views"]:,}' if p["views"] else "?"
        lines.append(
            f'{i}. <a href="{p["url"]}">{safe_title}</a>  (👀 {views_str})'
        )
    return "\n".join(lines)


async def run_blocking(func, *args):
    """동기 함수를 이벤트 루프 executor에서 실행한다."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def send_to_channel(bot, text: str) -> bool:
    """채널에 메시지를 보낸다."""
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error("채널 전송 실패: %s", e)
        return False


# ── 명령어 핸들러 ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — 즉시 크롤링 + 채널에 다이제스트 전송 (DM용)."""
    msg = await update.message.reply_text("⏳ 더쿠 크롤링 중...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await _crawl_silently()
    await msg.edit_text("📝 다이제스트 생성 중...")
    text = _build_digest()
    if text:
        await msg.edit_text("📤 채널에 전송 중...")
        ok = await send_to_channel(context.bot, text)
        if ok:
            await msg.edit_text("✅ 채널에 전송 완료!")
        else:
            await msg.edit_text("❌ 채널 전송 실패. 봇이 채널 관리자인지 확인하세요.")
    else:
        await msg.edit_text("수집된 게시글이 없습니다.")


async def cmd_start_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — 채널에서 입력 시 즉시 다이제스트 전송."""
    chat_id = update.channel_post.chat.id
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ 더쿠 크롤링 중...")
    await _crawl_silently()
    await msg.edit_text("📝 다이제스트 생성 중...")
    text = _build_digest()
    if text:
        await msg.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await msg.edit_text("수집된 게시글이 없습니다.")


# ── 크롤링 & 다이제스트 ──────────────────────────────────────

def _save_and_analyze(posts: list[Post]) -> list[Post]:
    """게시글을 DB에 저장·분석하고, 새 게시글만 반환한다."""
    new_posts = []
    for p in posts:
        if not is_post_seen(p.document_srl):
            save_post(p.document_srl, p.board, p.title, p.url, p.views)
            new_posts.append(p)
    if new_posts:
        extract_and_record_mentions(new_posts)
    return new_posts


async def _crawl_silently() -> None:
    """더쿠를 크롤링해서 DB에 저장만 한다."""
    hot_posts = await run_blocking(scraper.fetch_hot_cosmetic_posts)
    beauty_posts = await run_blocking(scraper.fetch_beauty_posts)
    new_hot = _save_and_analyze(hot_posts)
    new_beauty = _save_and_analyze(beauty_posts)
    logger.info("크롤링 완료: HOT 새글 %d, 뷰티 새글 %d", len(new_hot), len(new_beauty))


def _build_digest() -> str:
    """24시간 다이제스트 메시지를 생성한다."""
    recent = get_recent_posts(hours=24, limit=20)
    if not recent:
        return ""

    hot = [p for p in recent if p["board"] == "hot"]
    beauty = [p for p in recent if p["board"] == "beauty"]

    parts = ["<b>📋 더쿠 화장품 24시간 다이제스트</b>"]

    beauty_text = format_posts_html(beauty, "💄 뷰티 게시판 인기글")
    if beauty_text:
        parts.append(beauty_text)

    hot_text = format_posts_html(hot, "🔥 HOT 게시판 화장품 글")
    if hot_text:
        parts.append(hot_text)

    trending = get_trending_report(hours=168)
    parts.append(trending)

    skincare = get_skincare_report(hours=168)
    if skincare:
        parts.append(skincare)

    recommend = get_recommend_report(hours=168)
    if recommend:
        parts.append(recommend)

    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    parts.append(f"<i>{today.strftime('%Y.%m.%d %H:%M')} 기준</i>")

    return "\n\n".join(parts)


async def scheduled_crawl(context: ContextTypes.DEFAULT_TYPE) -> None:
    """30분마다: 백그라운드 크롤링 (DB 수집만)."""
    logger.info("백그라운드 크롤링 시작")
    await _crawl_silently()


async def scheduled_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """매일 아침 8시(KST): 크롤링 + 채널에 다이제스트 포스팅."""
    logger.info("일일 다이제스트 시작")

    await _crawl_silently()

    text = _build_digest()
    if not text:
        logger.info("다이제스트 데이터 없음")
        return

    ok = await send_to_channel(context.bot, text)
    logger.info("채널 다이제스트 전송: %s", "성공" if ok else "실패")


async def first_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """시작 직후 1회: 테스트 전송."""
    logger.info("첫 다이제스트 전송 (테스트)")

    await _crawl_silently()

    text = _build_digest()
    if not text:
        logger.info("첫 다이제스트 데이터 없음")
        return

    ok = await send_to_channel(context.bot, text)
    logger.info("첫 다이제스트 채널 전송: %s", "성공" if ok else "실패")


async def scheduled_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """매일 오래된 데이터 정리."""
    deleted = cleanup_old_data()
    logger.info("DB 정리 완료: %d건 삭제", deleted)


# ── 메인 ─────────────────────────────────────────────────────

def main() -> None:
    """봇을 실행한다."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # /start → DM에서
    app.add_handler(CommandHandler("start", cmd_start))
    # /start → 채널에서
    app.add_handler(MessageHandler(
        filters.UpdateType.CHANNEL_POST & filters.Regex(r"^/start"),
        cmd_start_channel,
    ))

    job_queue = app.job_queue

    # 시작 15초 후 첫 다이제스트 채널 전송 (테스트)
    job_queue.run_once(first_digest, when=15, name="first_digest")

    # 30분마다 백그라운드 크롤링 (DB 수집만)
    job_queue.run_repeating(
        scheduled_crawl,
        interval=CRAWL_INTERVAL_MINUTES * 60,
        first=CRAWL_INTERVAL_MINUTES * 60,
        name="crawl",
    )

    # 매일 아침 8시(KST) = UTC 23시 다이제스트
    job_queue.run_daily(
        scheduled_digest,
        time=datetime.time(hour=DAILY_DIGEST_HOUR, minute=0),
        name="digest",
    )

    # 매일 DB 정리
    job_queue.run_daily(
        scheduled_cleanup,
        time=datetime.time(hour=CLEANUP_HOUR, minute=0),
        name="cleanup",
    )

    logger.info("봇 시작! (채널: %s, 매일 KST 08시 다이제스트)", TELEGRAM_CHANNEL_ID)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
