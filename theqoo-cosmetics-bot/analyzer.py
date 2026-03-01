"""트렌딩 분석 — 브랜드/제품/스킨케어/추천 언급 추적."""

import html
import logging

from config import RECOMMEND_KEYWORDS, SKINCARE_KEYWORDS, TRENDING_KEYWORDS
from database import (
    get_posts_by_keywords,
    get_skincare_trending,
    get_trending,
    save_mention,
)
from scraper import Post

logger = logging.getLogger(__name__)

# 전체 추적 키워드
_ALL_TRACK_KEYWORDS = TRENDING_KEYWORDS + SKINCARE_KEYWORDS + RECOMMEND_KEYWORDS


def extract_and_record_mentions(posts: list[Post]) -> None:
    """게시글 제목에서 키워드를 찾아 DB에 기록한다."""
    for post in posts:
        title_lower = post.title.lower()
        for keyword in _ALL_TRACK_KEYWORDS:
            if keyword.lower() in title_lower:
                save_mention(keyword, post.document_srl)


def get_trending_report(hours: int = 24, limit: int = 10) -> str:
    """브랜드 트렌딩 보고서를 텔레그램 HTML 메시지로 생성한다."""
    trending = get_trending(hours=hours, limit=limit)

    if not trending:
        return "수집된 브랜드 트렌딩 데이터가 없습니다."

    days = hours // 24
    period = f"{days}일" if hours >= 24 and hours % 24 == 0 else f"{hours}시간"
    lines = [f"<b>🔥 최근 {period} 브랜드 트렌딩 TOP {limit}</b>\n"]
    for i, item in enumerate(trending, 1):
        keyword = item["keyword"]
        count = item["cnt"]
        lines.append(f"{i}. <b>{keyword}</b> — {count}회 언급")

    return "\n".join(lines)


def get_skincare_report(hours: int = 24) -> str:
    """스킨케어 성분/제품 키워드 리포트를 생성한다."""
    trending = get_skincare_trending(SKINCARE_KEYWORDS, hours=hours, limit=10)

    if not trending:
        return ""

    days = hours // 24
    period = f"{days}일" if hours >= 24 and hours % 24 == 0 else f"{hours}시간"
    parts = [f"<b>🧪 최근 {period} 스킨케어 키워드 TOP 10</b>\n"]

    for i, item in enumerate(trending, 1):
        keyword = item["keyword"]
        count = item["cnt"]
        parts.append(f"{i}. <b>{keyword}</b> — {count}회 언급")

    top_posts = get_posts_by_keywords(SKINCARE_KEYWORDS, hours=hours, limit=10)

    if top_posts:
        parts.append(f"\n<b>📊 스킨케어 관련 조회수 TOP 10</b>\n")
        for i, p in enumerate(top_posts, 1):
            safe_title = html.escape(p["title"])
            views_str = f'{p["views"]:,}' if p["views"] else "?"
            parts.append(
                f'{i}. <a href="{p["url"]}">{safe_title}</a> (👀 {views_str})'
            )

    return "\n".join(parts)


def get_recommend_report(hours: int = 24) -> str:
    """추천/리뷰 게시글 리포트를 생성한다."""
    top_posts = get_posts_by_keywords(RECOMMEND_KEYWORDS, hours=hours, limit=10)

    if not top_posts:
        return ""

    days = hours // 24
    period = f"{days}일" if hours >= 24 and hours % 24 == 0 else f"{hours}시간"
    parts = [f"<b>💡 최근 {period} 추천/리뷰 인기글 TOP 10</b>\n"]
    for i, p in enumerate(top_posts, 1):
        safe_title = html.escape(p["title"])
        views_str = f'{p["views"]:,}' if p["views"] else "?"
        parts.append(
            f'{i}. <a href="{p["url"]}">{safe_title}</a> (👀 {views_str})'
        )

    return "\n".join(parts)
