"""SQLite 데이터베이스 관리."""

import sqlite3
from datetime import datetime, timedelta, timezone

from config import DB_PATH, DATA_RETENTION_DAYS


def _utcnow_str() -> str:
    """SQLite datetime('now') 호환 형식의 현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_connection() -> sqlite3.Connection:
    """DB 연결을 반환한다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """테이블을 생성한다."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TEXT NOT NULL DEFAULT (datetime('now')),
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS seen_posts (
                document_srl TEXT PRIMARY KEY,
                board TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                notified INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                document_srl TEXT NOT NULL,
                mentioned_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (document_srl) REFERENCES seen_posts(document_srl)
            );

            CREATE INDEX IF NOT EXISTS idx_mentions_keyword
                ON mentions(keyword);
            CREATE INDEX IF NOT EXISTS idx_mentions_time
                ON mentions(mentioned_at);
            CREATE INDEX IF NOT EXISTS idx_seen_posts_board
                ON seen_posts(board);
        """)
        conn.commit()
    finally:
        conn.close()


# ── 구독자 관리 ──────────────────────────────────────────────

def add_subscriber(chat_id: int) -> bool:
    """구독자를 추가하거나 재활성화한다. 새로 추가되면 True."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT active FROM subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO subscribers (chat_id) VALUES (?)", (chat_id,)
            )
            conn.commit()
            return True
        if not row["active"]:
            conn.execute(
                "UPDATE subscribers SET active = 1, subscribed_at = datetime('now') "
                "WHERE chat_id = ?",
                (chat_id,),
            )
            conn.commit()
            return True
        return False  # 이미 활성 구독 중
    finally:
        conn.close()


def remove_subscriber(chat_id: int) -> bool:
    """구독을 해제한다. 해제 성공이면 True."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE subscribers SET active = 0 WHERE chat_id = ? AND active = 1",
            (chat_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_active_subscribers() -> list[int]:
    """활성 구독자 chat_id 목록을 반환한다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT chat_id FROM subscribers WHERE active = 1"
        ).fetchall()
        return [r["chat_id"] for r in rows]
    finally:
        conn.close()


# ── 게시글 관리 ──────────────────────────────────────────────

def is_post_seen(document_srl: str) -> bool:
    """게시글이 이미 기록되어 있는지 확인한다."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM seen_posts WHERE document_srl = ?", (document_srl,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def save_post(
    document_srl: str,
    board: str,
    title: str,
    url: str,
    views: int,
) -> None:
    """게시글을 저장한다 (중복 시 무시)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO seen_posts "
            "(document_srl, board, title, url, views) VALUES (?, ?, ?, ?, ?)",
            (document_srl, board, title, url, views),
        )
        conn.commit()
    finally:
        conn.close()


def mark_notified(document_srl: str) -> None:
    """게시글을 알림 발송 완료로 표시한다."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE seen_posts SET notified = 1 WHERE document_srl = ?",
            (document_srl,),
        )
        conn.commit()
    finally:
        conn.close()


def get_unnotified_posts(board: str) -> list[dict]:
    """알림 미발송 게시글을 반환한다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT document_srl, board, title, url, views "
            "FROM seen_posts WHERE board = ? AND notified = 0 "
            "ORDER BY views DESC",
            (board,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_posts(hours: int = 24, limit: int = 20) -> list[dict]:
    """최근 N시간 내 게시글을 조회수 순으로 반환한다."""
    conn = get_connection()
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            "SELECT document_srl, board, title, url, views "
            "FROM seen_posts WHERE created_at >= ? "
            "ORDER BY views DESC LIMIT ?",
            (since, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_skincare_trending(keywords: list[str], hours: int = 24, limit: int = 10) -> list[dict]:
    """스킨케어 키워드별 언급 횟수를 반환한다."""
    conn = get_connection()
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in keywords)
        rows = conn.execute(
            f"SELECT keyword, COUNT(*) as cnt "
            f"FROM mentions WHERE keyword IN ({placeholders}) "
            f"AND mentioned_at >= ? "
            f"GROUP BY keyword ORDER BY cnt DESC LIMIT ?",
            (*keywords, since, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_posts_by_keywords(keywords: list[str], hours: int = 24, limit: int = 10) -> list[dict]:
    """특정 키워드가 언급된 게시글을 조회수 순으로 반환한다."""
    conn = get_connection()
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in keywords)
        rows = conn.execute(
            f"SELECT DISTINCT sp.document_srl, sp.board, sp.title, sp.url, sp.views "
            f"FROM mentions m JOIN seen_posts sp ON m.document_srl = sp.document_srl "
            f"WHERE m.keyword IN ({placeholders}) AND m.mentioned_at >= ? "
            f"ORDER BY sp.views DESC LIMIT ?",
            (*keywords, since, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 멘션(트렌딩) 관리 ────────────────────────────────────────

def save_mention(keyword: str, document_srl: str) -> None:
    """키워드 멘션을 기록한다."""
    conn = get_connection()
    try:
        # 같은 게시글에서 같은 키워드 중복 방지
        row = conn.execute(
            "SELECT 1 FROM mentions WHERE keyword = ? AND document_srl = ?",
            (keyword, document_srl),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO mentions (keyword, document_srl) VALUES (?, ?)",
                (keyword, document_srl),
            )
            conn.commit()
    finally:
        conn.close()


def get_trending(hours: int = 24, limit: int = 10) -> list[dict]:
    """최근 N시간 동안 가장 많이 언급된 키워드 TOP N을 반환한다."""
    conn = get_connection()
    try:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            "SELECT keyword, COUNT(*) as cnt "
            "FROM mentions WHERE mentioned_at >= ? "
            "GROUP BY keyword ORDER BY cnt DESC LIMIT ?",
            (since, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 정리 ─────────────────────────────────────────────────────

def cleanup_old_data() -> int:
    """오래된 데이터를 삭제하고 삭제 건수를 반환한다."""
    conn = get_connection()
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=DATA_RETENTION_DAYS)
        ).strftime("%Y-%m-%d %H:%M:%S")

        # 멘션 먼저 삭제
        cur1 = conn.execute(
            "DELETE FROM mentions WHERE mentioned_at < ?", (cutoff,)
        )
        # 게시글 삭제
        cur2 = conn.execute(
            "DELETE FROM seen_posts WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        return cur1.rowcount + cur2.rowcount
    finally:
        conn.close()
