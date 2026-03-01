import json
import logging
import os

from telegram.constants import ParseMode
from config import WATCH_DATA_FILE, DAILY_CHANNEL
from x_client import XClient, XClientError
from summarizer import summarize_tweets

logger = logging.getLogger(__name__)


class Watcher:
    """Tracks subscribed accounts and sends periodic summaries."""

    def __init__(self, x_client: XClient) -> None:
        self.x_client = x_client
        # Structure: { "username": { "chat_ids": [int, ...], "last_tweet_id": str|None } }
        self._data: dict[str, dict] = {}
        self._load()

    # --- persistence ---

    def _load(self) -> None:
        if os.path.exists(WATCH_DATA_FILE):
            try:
                with open(WATCH_DATA_FILE, "r") as f:
                    self._data = json.load(f)
                logger.info("Loaded subscription data: %d accounts", len(self._data))
            except Exception as e:
                logger.warning("Failed to load subscription data: %s", e)

    def _save(self) -> None:
        try:
            with open(WATCH_DATA_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save subscription data: %s", e)

    # --- public API ---

    def add(self, username: str, chat_id: int) -> None:
        username = username.lower()
        if username not in self._data:
            self._data[username] = {"chat_ids": [], "last_tweet_id": None}
        if chat_id not in self._data[username]["chat_ids"]:
            self._data[username]["chat_ids"].append(chat_id)
        self._save()

    def remove(self, username: str, chat_id: int) -> bool:
        username = username.lower()
        entry = self._data.get(username)
        if not entry or chat_id not in entry["chat_ids"]:
            return False
        entry["chat_ids"].remove(chat_id)
        if not entry["chat_ids"]:
            del self._data[username]
        self._save()
        return True

    def list_for_chat(self, chat_id: int) -> list[str]:
        return [u for u, d in self._data.items() if chat_id in d["chat_ids"]]

    # --- polling: check for new tweets and send summary ---

    async def check_all(self, bot) -> None:
        """Check all subscribed accounts for new tweets and send summary."""
        for username in list(self._data.keys()):
            entry = self._data[username]
            try:
                tweets = await self.x_client.get_tweets_last_24h(username)
            except XClientError as e:
                logger.warning("Error fetching @%s: %s", username, e)
                continue

            if not tweets:
                continue

            last_id = entry.get("last_tweet_id")

            # On first check, just record the latest tweet ID
            if last_id is None:
                entry["last_tweet_id"] = tweets[0].id
                self._save()
                continue

            # Find new tweets only
            new_tweets = [t for t in tweets if int(t.id) > int(last_id)]
            if not new_tweets:
                continue

            # Update last seen
            entry["last_tweet_id"] = max(new_tweets, key=lambda t: int(t.id)).id
            self._save()

            # Summarize new tweets
            summary = await summarize_tweets(username, new_tweets)

            header = f"🔔 X:{username} 새 트윗 요약 ({len(new_tweets)}개)\n\n"
            full_text = header + summary

            for chat_id in entry["chat_ids"]:
                try:
                    if len(full_text) <= 4096:
                        await bot.send_message(chat_id=chat_id, text=full_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                    else:
                        await bot.send_message(chat_id=chat_id, text=header)
                        for i in range(0, len(summary), 4000):
                            chunk = summary[i:i + 4000]
                            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception as e:
                    logger.warning("Failed to send to chat %s: %s", chat_id, e)

    # --- daily summary to channel ---

    async def daily_summary(self, bot) -> None:
        """Send 24h summary of all subscribed accounts to the channel."""
        if not DAILY_CHANNEL:
            logger.warning("DAILY_CHANNEL not set, skipping daily summary")
            return

        usernames = list(self._data.keys())
        if not usernames:
            logger.info("No subscribed accounts, skipping daily summary")
            return

        for username in usernames:
            try:
                tweets = await self.x_client.get_tweets_last_24h(username)
            except XClientError as e:
                logger.warning("Daily summary: error fetching X:%s: %s", username, e)
                continue

            if not tweets:
                logger.info("Daily summary: no tweets from X:%s in last 24h", username)
                continue

            summary = await summarize_tweets(username, tweets)

            header = f"📋 X:{username} 일일 요약\n({len(tweets)}개 트윗 기반)\n\n"
            full_text = header + summary

            try:
                if len(full_text) <= 4096:
                    await bot.send_message(chat_id=DAILY_CHANNEL, text=full_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                else:
                    await bot.send_message(chat_id=DAILY_CHANNEL, text=header)
                    for i in range(0, len(summary), 4000):
                        chunk = summary[i:i + 4000]
                        await bot.send_message(chat_id=DAILY_CHANNEL, text=chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                logger.info("Daily summary sent for X:%s to %s", username, DAILY_CHANNEL)
            except Exception as e:
                logger.error("Failed to send daily summary for X:%s to %s: %s", username, DAILY_CHANNEL, e)
