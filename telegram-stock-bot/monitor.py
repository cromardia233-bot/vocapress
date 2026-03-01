import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

import database as db
from filters import keyword_filter, llm_summarize
from config import (
    OUTPUT_CHANNEL,
    DAILY_REPORT_HOUR,
    HISTORY_HOURS,
    MESSAGE_FETCH_LIMIT,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class DailyDigest:
    def __init__(self, user_client: TelegramClient, bot_client: TelegramClient):
        self.user_client = user_client
        self.bot_client = bot_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """스케줄러 시작."""
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "일일 요약 스케줄러 시작 (매일 %02d:00 KST, 최근 %d시간)",
            DAILY_REPORT_HOUR,
            HISTORY_HOURS,
        )

    async def stop(self):
        """스케줄러 중지."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("일일 요약 스케줄러 중지")

    async def _scheduler_loop(self):
        """매일 DAILY_REPORT_HOUR(KST)에 run_digest 실행."""
        while self._running:
            now = datetime.now(KST)
            target = now.replace(
                hour=DAILY_REPORT_HOUR, minute=0, second=0, microsecond=0
            )
            if now >= target:
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.info(
                "다음 일일 요약까지 %.0f초 대기 (%s)",
                wait_seconds,
                target.strftime("%Y-%m-%d %H:%M KST"),
            )

            await asyncio.sleep(wait_seconds)

            if self._running:
                try:
                    await self.run_digest()
                except Exception as e:
                    logger.error("일일 요약 실행 중 오류: %s", e, exc_info=True)

    async def run_digest(self) -> str:
        """
        지난 HISTORY_HOURS 시간의 메시지를 수집 → 키워드 필터 → LLM 요약 → 전송.
        /digest 명령어에서도 호출 가능한 public 메서드.
        반환: 요약 결과 상태 메시지.
        """
        channels = await db.list_channels()
        if not channels:
            msg = "등록된 모니터링 채널이 없습니다."
            logger.warning(msg)
            return msg

        stocks = await db.list_stocks()
        if not stocks:
            msg = "등록된 종목/키워드가 없습니다."
            logger.warning(msg)
            return msg

        keywords = []
        for s in stocks:
            keywords.extend([kw.strip() for kw in s["keywords"].split(",") if kw.strip()])

        since = datetime.now(timezone.utc) - timedelta(hours=HISTORY_HOURS)
        all_matched: list[dict] = []

        for ch in channels:
            username = ch["username"]
            try:
                entity = await self.user_client.get_entity(f"@{username}")
            except Exception as e:
                logger.error("채널 엔티티 조회 실패 @%s: %s", username, e)
                continue

            count = 0
            async for message in self.user_client.iter_messages(
                entity, limit=MESSAGE_FETCH_LIMIT, offset_date=None
            ):
                if message.date and message.date < since:
                    break
                if not message.text:
                    continue

                matched = keyword_filter(message.text, keywords)
                if not matched:
                    continue

                all_matched.append({
                    "channel": f"@{username}",
                    "text": message.text,
                    "matched_keywords": matched,
                    "date": message.date.strftime("%Y-%m-%d %H:%M") if message.date else "",
                    "link": f"https://t.me/{username}/{message.id}",
                })
                count += 1

            logger.info("채널 @%s: %d건 키워드 매칭", username, count)

        if not all_matched:
            msg = f"최근 {HISTORY_HOURS}시간 내 키워드 매칭 메시지가 없습니다."
            logger.info(msg)
            try:
                await self.bot_client.send_message(
                    OUTPUT_CHANNEL,
                    f"📋 <b>일일 요약</b> ({datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')})\n\n{msg}",
                    parse_mode="html",
                )
            except Exception as e:
                logger.error("빈 요약 전송 실패: %s", e)
            return msg

        logger.info("총 %d건 키워드 매칭 메시지, LLM 요약 시작", len(all_matched))

        # 종목명 → 키워드 매핑 전달
        stock_map = {s["name"]: s["keywords"] for s in stocks}

        try:
            summary_text = await llm_summarize(all_matched, stock_map)
        except Exception as e:
            logger.error("LLM 요약 실패: %s", e)
            summary_text = self._fallback_summary(all_matched)

        header = (
            f"📋 <b>일일 요약</b> ({datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')})\n"
            f"📡 채널 {len(channels)}개 | 📨 매칭 {len(all_matched)}건\n"
            f"━━━━━━━━━━━━━━━\n\n"
        )
        full_message = header + summary_text

        # 텔레그램 메시지 길이 제한 (4096자) 대응
        chunks = self._split_message(full_message, max_len=4000)
        sent = 0
        for chunk in chunks:
            try:
                await self.bot_client.send_message(
                    OUTPUT_CHANNEL, chunk, parse_mode="html"
                )
                sent += 1
            except Exception as e:
                logger.error("요약 전송 실패: %s", e)

        result = f"일일 요약 완료: {len(all_matched)}건 분석, {sent}건 메시지 전송"
        logger.info(result)
        return result

    @staticmethod
    def _fallback_summary(messages: list[dict]) -> str:
        """LLM 실패 시 간단한 폴백 요약."""
        lines = []
        for msg in messages[:20]:
            kw = ", ".join(msg["matched_keywords"])
            text_preview = msg["text"][:100].replace("\n", " ")
            lines.append(f"• [{msg['channel']}] ({kw}) {text_preview}")
        if len(messages) > 20:
            lines.append(f"\n... 외 {len(messages) - 20}건")
        return "\n".join(lines)

    @staticmethod
    def _split_message(text: str, max_len: int = 4000) -> list[str]:
        """긴 메시지를 max_len 이하로 분할."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # 줄바꿈 기준으로 자르기
            cut = text.rfind("\n", 0, max_len)
            if cut == -1:
                cut = max_len
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks
