import logging
from telethon import TelegramClient, events

import database as db
from config import DAILY_REPORT_HOUR, HISTORY_HOURS

logger = logging.getLogger(__name__)


def register_commands(bot_client: TelegramClient, digest):
    """봇 명령어 핸들러 등록. digest: DailyDigest 인스턴스."""

    @bot_client.on(events.NewMessage(pattern=r"/digest$"))
    async def digest_handler(event):
        await event.reply("⏳ 일일 요약을 수동 실행합니다. 잠시 기다려주세요...")
        try:
            result = await digest.run_digest()
            await event.reply(f"✅ {result}")
        except Exception as e:
            logger.error("/digest 실행 중 오류: %s", e, exc_info=True)
            await event.reply(f"❌ 요약 실행 중 오류가 발생했습니다: {e}")

    @bot_client.on(events.NewMessage(pattern=r"/add_stock\s+(.+)"))
    async def add_stock_handler(event):
        args = event.pattern_match.group(1).strip()
        parts = args.split(maxsplit=1)
        name = parts[0]
        keywords = parts[1] if len(parts) > 1 else None

        success = await db.add_stock(name, keywords, added_by=event.sender_id)
        if success:
            kw_display = f"{name},{keywords}" if keywords else name
            await event.reply(f"✅ 종목 추가 완료: <b>{name}</b>\n키워드: {kw_display}", parse_mode="html")
        else:
            await event.reply(f"⚠️ 이미 등록된 종목입니다: {name}")

    @bot_client.on(events.NewMessage(pattern=r"/remove_stock\s+(.+)"))
    async def remove_stock_handler(event):
        name = event.pattern_match.group(1).strip()
        success = await db.remove_stock(name)
        if success:
            await event.reply(f"✅ 종목 삭제 완료: {name}")
        else:
            await event.reply(f"⚠️ 등록되지 않은 종목입니다: {name}")

    @bot_client.on(events.NewMessage(pattern=r"/list_stocks$"))
    async def list_stocks_handler(event):
        stocks = await db.list_stocks()
        if not stocks:
            await event.reply("등록된 종목이 없습니다.")
            return
        lines = ["<b>📊 등록된 종목 목록</b>\n"]
        for i, s in enumerate(stocks, 1):
            lines.append(f"{i}. <b>{s['name']}</b> — 키워드: {s['keywords']}")
        await event.reply("\n".join(lines), parse_mode="html")

    @bot_client.on(events.NewMessage(pattern=r"/add_channel\s+(.+)"))
    async def add_channel_handler(event):
        username = event.pattern_match.group(1).strip().lstrip("@")
        success = await db.add_channel(username, added_by=event.sender_id)
        if success:
            await event.reply(f"✅ 채널 추가 완료: @{username}")
        else:
            await event.reply(f"⚠️ 이미 등록된 채널입니다: @{username}")

    @bot_client.on(events.NewMessage(pattern=r"/remove_channel\s+(.+)"))
    async def remove_channel_handler(event):
        username = event.pattern_match.group(1).strip().lstrip("@")
        success = await db.remove_channel(username)
        if success:
            await event.reply(f"✅ 채널 삭제 완료: @{username}")
        else:
            await event.reply(f"⚠️ 등록되지 않은 채널입니다: @{username}")

    @bot_client.on(events.NewMessage(pattern=r"/list_channels$"))
    async def list_channels_handler(event):
        channels = await db.list_channels()
        if not channels:
            await event.reply("등록된 채널이 없습니다.")
            return
        lines = ["<b>📡 모니터링 채널 목록</b>\n"]
        for i, ch in enumerate(channels, 1):
            name_display = f" ({ch['name']})" if ch.get("name") else ""
            lines.append(f"{i}. @{ch['username']}{name_display}")
        await event.reply("\n".join(lines), parse_mode="html")

    @bot_client.on(events.NewMessage(pattern=r"/status$"))
    async def status_handler(event):
        channels = await db.list_channels()
        stocks = await db.list_stocks()
        recent_count = await db.get_message_count(since_hours=24)

        text = (
            "<b>🤖 봇 상태</b>\n\n"
            f"📡 모니터링 채널: {len(channels)}개\n"
            f"📊 등록 종목: {len(stocks)}개\n"
            f"📨 최근 24시간 처리 메시지: {recent_count}건\n\n"
            f"<b>📋 일일 요약 설정</b>\n"
            f"⏰ 매일 {DAILY_REPORT_HOUR:02d}:00 KST 자동 실행\n"
            f"📅 최근 {HISTORY_HOURS}시간 메시지 분석\n"
            f"💡 /digest 로 수동 실행 가능"
        )
        await event.reply(text, parse_mode="html")

    @bot_client.on(events.NewMessage(pattern=r"/help$"))
    async def help_handler(event):
        text = (
            "<b>📖 사용 가이드</b>\n\n"
            "<b>종목 관리</b>\n"
            "/add_stock &lt;종목명&gt; [키워드1,키워드2,...]\n"
            "  예: /add_stock 삼성전자 삼성,삼전,005930\n"
            "/remove_stock &lt;종목명&gt;\n"
            "/list_stocks\n\n"
            "<b>채널 관리</b>\n"
            "/add_channel &lt;@username&gt;\n"
            "  예: /add_channel @stock_channel\n"
            "/remove_channel &lt;@username&gt;\n"
            "/list_channels\n\n"
            "<b>일일 요약</b>\n"
            f"/digest — 즉시 일일 요약 실행 (최근 {HISTORY_HOURS}시간)\n"
            f"⏰ 자동 실행: 매일 {DAILY_REPORT_HOUR:02d}:00 KST\n\n"
            "<b>기타</b>\n"
            "/status — 봇 상태 확인\n"
            "/help — 이 도움말"
        )
        await event.reply(text, parse_mode="html")

    logger.info("봇 명령어 핸들러 등록 완료")
