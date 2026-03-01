import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS
from cookie_manager import get_x_cookies, validate_cookies, invalidate_cache
from x_client import XClient, XClientError
from summarizer import summarize_tweets
from watcher import Watcher

logger = logging.getLogger(__name__)

x_client = XClient()
watcher: Watcher | None = None  # set in build()


def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "X(Twitter) 요약 봇\n\n"
        "명령어:\n"
        "/summary username — 최근 24시간 트윗 요약+해설\n"
        "/subscribe username — 계정 구독 (자동 요약 알림)\n"
        "/unsubscribe username — 구독 해제\n"
        "/list — 구독 중인 계정 목록\n"
        "/cookie_status — 쿠키 상태 확인",
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /summary username")
        return

    username = args[0].lstrip("@")
    msg = await update.message.reply_text(f"X:{username}의 최근 24시간 트윗을 가져오는 중…")

    try:
        tweets = await x_client.get_tweets_last_24h(username)
    except XClientError as e:
        await msg.edit_text(f"오류: {e}")
        return

    if not tweets:
        await msg.edit_text(f"X:{username}의 최근 24시간 트윗이 없습니다.")
        return

    await msg.edit_text(f"X:{username}의 트윗 {len(tweets)}개를 요약하는 중…")

    summary = await summarize_tweets(username, tweets)

    header = f"📋 X:{username} 최근 24시간 요약\n({len(tweets)}개 트윗 기반)\n\n"

    full_text = header + summary
    # Telegram 4096 char limit — split if needed
    if len(full_text) <= 4096:
        await msg.edit_text(full_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await msg.edit_text(header)
        for i in range(0, len(summary), 4000):
            chunk = summary[i:i + 4000]
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /subscribe username")
        return

    username = args[0].lstrip("@")
    chat_id = update.effective_chat.id

    try:
        await x_client.get_user_id(username)
    except XClientError as e:
        await update.message.reply_text(f"오류: {e}")
        return

    watcher.add(username, chat_id)
    await update.message.reply_text(
        f"✅ X:{username} 구독 완료!\n"
        f"주기적으로 새 트윗 요약을 보내드립니다."
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("사용법: /unsubscribe username")
        return

    username = args[0].lstrip("@")
    chat_id = update.effective_chat.id
    removed = watcher.remove(username, chat_id)
    if removed:
        await update.message.reply_text(f"🗑 X:{username} 구독이 해제되었습니다.")
    else:
        await update.message.reply_text(f"X:{username}은(는) 구독 중이 아닙니다.")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    chat_id = update.effective_chat.id
    accounts = watcher.list_for_chat(chat_id)
    if not accounts:
        await update.message.reply_text("구독 중인 계정이 없습니다.")
        return
    text = "구독 중인 계정:\n" + "\n".join(f"• X:{a}" for a in accounts)
    await update.message.reply_text(text)


async def cmd_cookie_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    invalidate_cache()
    cookies = get_x_cookies(force_refresh=True)
    ok, msg = validate_cookies(cookies)
    if ok:
        await update.message.reply_text("쿠키 상태: ✅ 정상\nauth_token, ct0 모두 존재합니다.")
    else:
        await update.message.reply_text(f"쿠키 상태: ❌ 비정상\n{msg}")


def build(watcher_instance: Watcher) -> Application:
    global watcher
    watcher = watcher_instance

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("cookie_status", cmd_cookie_status))
    return app
