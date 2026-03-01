import asyncio
import logging
from datetime import timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import TELEGRAM_BOT_TOKEN, WATCH_INTERVAL, DAILY_CHANNEL, DAILY_HOUR
from cookie_manager import get_x_cookies, validate_cookies
from x_client import XClient
from watcher import Watcher
from telegram_bot import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


async def poll_job(watcher: Watcher, app) -> None:
    await watcher.check_all(app.bot)


async def daily_job(watcher: Watcher, app) -> None:
    logger.info("Running daily summary job…")
    await watcher.daily_summary(app.bot)
    logger.info("Daily summary job complete.")


def main() -> None:
    # Pre-flight checks
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
        return

    cookies = get_x_cookies()
    ok, msg = validate_cookies(cookies)
    if ok:
        logger.info("X cookies: OK")
    else:
        logger.warning("X cookies: %s — bot will start but /fetch may fail", msg)

    # Build components
    x_client = XClient()
    watcher_instance = Watcher(x_client)
    app = build(watcher_instance)

    # Set up scheduler
    scheduler = AsyncIOScheduler()

    # Periodic new-tweet check
    scheduler.add_job(
        poll_job,
        "interval",
        seconds=WATCH_INTERVAL,
        args=[watcher_instance, app],
        id="watcher_poll",
        max_instances=1,
    )

    # Daily 8 AM KST summary to channel
    if DAILY_CHANNEL:
        scheduler.add_job(
            daily_job,
            CronTrigger(hour=DAILY_HOUR, minute=0, timezone=KST),
            args=[watcher_instance, app],
            id="daily_summary",
            max_instances=1,
        )
        logger.info("Daily summary scheduled: %02d:00 KST → %s", DAILY_HOUR, DAILY_CHANNEL)
    else:
        logger.info("DAILY_CHANNEL not set, daily summary disabled")

    async def post_init(application) -> None:
        scheduler.start()
        logger.info("Scheduler started (poll=%ds)", WATCH_INTERVAL)

    async def post_shutdown(application) -> None:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    logger.info("Starting bot… Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
