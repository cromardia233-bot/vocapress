"""더쿠(theqoo.net) 웹 스크래핑."""

import logging
import re
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from config import (
    FILTER_KEYWORDS,
    MAX_PAGES,
    REQUEST_DELAY,
    REQUEST_HEADERS,
    THEQOO_BASE_URL,
    THEQOO_BEAUTY_URL,
    THEQOO_HOT_URL,
    VIEW_THRESHOLD_BEAUTY,
    VIEW_THRESHOLD_HOT,
)

logger = logging.getLogger(__name__)


@dataclass
class Post:
    """크롤링된 게시글."""
    document_srl: str
    board: str
    title: str
    url: str
    views: int


class TheqooScraper:
    """더쿠 게시판 크롤러."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    # ── 공개 API ─────────────────────────────────────────────

    def fetch_beauty_posts(self, pages: int = MAX_PAGES) -> list[Post]:
        """뷰티 게시판에서 인기글을 가져온다."""
        return self._fetch_board(
            board_url=THEQOO_BEAUTY_URL,
            board_name="beauty",
            threshold=VIEW_THRESHOLD_BEAUTY,
            pages=pages,
            filter_keywords=False,
        )

    def fetch_hot_cosmetic_posts(self, pages: int = MAX_PAGES) -> list[Post]:
        """HOT 게시판에서 화장품 관련 인기글만 가져온다."""
        return self._fetch_board(
            board_url=THEQOO_HOT_URL,
            board_name="hot",
            threshold=VIEW_THRESHOLD_HOT,
            pages=pages,
            filter_keywords=True,
        )

    def search_posts(
        self, keyword: str, pages: int = MAX_PAGES
    ) -> list[Post]:
        """뷰티 + HOT 게시판에서 키워드로 제목 검색한다 (클라이언트 사이드)."""
        results: list[Post] = []
        kw_lower = keyword.lower()

        for board_url, board_name in [
            (THEQOO_BEAUTY_URL, "beauty"),
            (THEQOO_HOT_URL, "hot"),
        ]:
            posts = self._fetch_board(
                board_url=board_url,
                board_name=board_name,
                threshold=0,
                pages=pages,
                filter_keywords=False,
            )
            for p in posts:
                if kw_lower in p.title.lower():
                    results.append(p)
            time.sleep(REQUEST_DELAY)

        # 조회수 높은 순 정렬
        results.sort(key=lambda p: p.views, reverse=True)
        return results[:20]

    # ── 내부 구현 ─────────────────────────────────────────────

    def _fetch_board(
        self,
        board_url: str,
        board_name: str,
        threshold: int,
        pages: int,
        filter_keywords: bool,
    ) -> list[Post]:
        """게시판 페이지들을 크롤링하여 Post 목록을 반환한다."""
        posts: list[Post] = []

        for page in range(1, pages + 1):
            url = board_url if page == 1 else f"{board_url}?page={page}"
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.warning("페이지 요청 실패: %s — %s", url, e)
                break

            page_posts = self._parse_board_page(
                resp.text, board_name, threshold, filter_keywords
            )
            posts.extend(page_posts)

            if page < pages:
                time.sleep(REQUEST_DELAY)

        # 조회수 높은 순
        posts.sort(key=lambda p: p.views, reverse=True)
        return posts

    def _parse_board_page(
        self,
        html: str,
        board_name: str,
        threshold: int,
        filter_keywords: bool,
    ) -> list[Post]:
        """HTML에서 게시글 목록을 파싱한다."""
        soup = BeautifulSoup(html, "html.parser")
        posts: list[Post] = []

        # XpressEngine 기반 다중 CSS selector 폴백
        rows = (
            soup.select("table.bd_lst tbody tr")
            or soup.select("div.board_list table tbody tr")
            or soup.select("table.bd_lst_wrp tbody tr")
            or soup.select("tr.bd_lst_tr")
        )

        for row in rows:
            # 공지사항 / 특수 행 건너뛰기
            row_classes = row.get("class", [])
            if any(
                c in row_classes
                for c in ["notice", "bd_lst_notice", "nofn", "nofnhide"]
            ):
                continue

            post = self._parse_row(row, board_name)
            if post is None:
                continue

            # 조회수 필터
            if post.views < threshold:
                continue

            # 키워드 필터 (HOT 게시판)
            if filter_keywords and not self._matches_keywords(post.title):
                continue

            posts.append(post)

        return posts

    def _parse_row(self, row, board_name: str) -> Post | None:
        """테이블 행에서 Post를 추출한다."""
        # 제목 추출 (다중 폴백)
        title_tag = (
            row.select_one("td.title a")
            or row.select_one("td.title .title_wrapper a")
            or row.select_one("a.hx")
            or row.select_one("a.title_link")
        )
        if title_tag is None:
            return None

        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")

        # document_srl 추출
        doc_srl = self._extract_document_srl(href)
        if not doc_srl:
            return None

        # URL 정규화
        if href.startswith("/"):
            full_url = THEQOO_BASE_URL + href
        elif href.startswith("http"):
            full_url = href
        else:
            full_url = f"{THEQOO_BASE_URL}/{href}"

        # 조회수 추출 (다중 폴백)
        views = 0
        views_td = (
            row.select_one("td.m_no")  # 일반적인 조회수 위치
            or row.select_one("td.read_count")
            or row.select_one("td:nth-of-type(4)")
        )
        if views_td:
            views = self._parse_number(views_td.get_text(strip=True))

        return Post(
            document_srl=doc_srl,
            board=board_name,
            title=title,
            url=full_url,
            views=views,
        )

    @staticmethod
    def _extract_document_srl(href: str) -> str:
        """URL에서 document_srl을 추출한다."""
        # /hot/3424897632 또는 ?document_srl=3424897632
        m = re.search(r"/(\d{8,})", href)
        if m:
            return m.group(1)
        m = re.search(r"document_srl=(\d+)", href)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _parse_number(text: str) -> int:
        """'1,234' 같은 숫자 문자열을 int로 변환한다."""
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else 0

    @staticmethod
    def _matches_keywords(title: str) -> bool:
        """제목이 화장품 키워드를 포함하는지 확인한다."""
        title_lower = title.lower()
        return any(kw.lower() in title_lower for kw in FILTER_KEYWORDS)
