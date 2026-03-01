import aiosqlite
import hashlib
from datetime import datetime

from config import DB_PATH


async def init_db():
    """데이터베이스 초기화 및 테이블 생성."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                name TEXT,
                added_by INTEGER,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                keywords TEXT NOT NULL,
                added_by INTEGER,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                message_id INTEGER,
                content_hash TEXT UNIQUE,
                processed_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


# --- Channels ---

async def add_channel(username: str, name: str | None = None, added_by: int | None = None) -> bool:
    """채널 추가. 이미 존재하면 False 반환."""
    username = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO channels (username, name, added_by) VALUES (?, ?, ?)",
                (username, name, added_by),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_channel(username: str) -> bool:
    """채널 삭제. 존재하지 않으면 False 반환."""
    username = username.lstrip("@").lower()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM channels WHERE username = ?", (username,))
        await db.commit()
        return cursor.rowcount > 0


async def list_channels() -> list[dict]:
    """등록된 채널 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT username, name, added_at FROM channels ORDER BY added_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Stocks ---

async def add_stock(name: str, keywords: str | None = None, added_by: int | None = None) -> bool:
    """종목 추가. keywords는 쉼표 구분 문자열. 이미 존재하면 False 반환."""
    all_keywords = name
    if keywords:
        all_keywords = f"{name},{keywords}"
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO stocks (name, keywords, added_by) VALUES (?, ?, ?)",
                (name, all_keywords, added_by),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_stock(name: str) -> bool:
    """종목 삭제. 존재하지 않으면 False 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM stocks WHERE name = ?", (name,))
        await db.commit()
        return cursor.rowcount > 0


async def list_stocks() -> list[dict]:
    """등록된 종목 목록 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT name, keywords, added_at FROM stocks ORDER BY added_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_keywords() -> list[str]:
    """등록된 모든 종목의 키워드를 평탄화하여 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT keywords FROM stocks")
        rows = await cursor.fetchall()
        keywords = []
        for row in rows:
            keywords.extend([kw.strip() for kw in row[0].split(",") if kw.strip()])
        return keywords


# --- Message Log ---

def compute_hash(text: str) -> str:
    """메시지 텍스트의 SHA-256 해시 생성."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def is_message_processed(content_hash: str) -> bool:
    """해당 해시의 메시지가 이미 처리되었는지 확인."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM message_log WHERE content_hash = ?", (content_hash,)
        )
        return await cursor.fetchone() is not None


async def log_message(channel_id: int, message_id: int, content_hash: str):
    """처리된 메시지를 로그에 기록."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO message_log (channel_id, message_id, content_hash) VALUES (?, ?, ?)",
                (channel_id, message_id, content_hash),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            pass  # 중복 — 무시


async def get_message_count(since_hours: int = 24) -> int:
    """최근 N시간 내 처리된 메시지 수 반환."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM message_log WHERE processed_at > datetime('now', ?)",
            (f"-{since_hours} hours",),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
