"""discountingcashflows.com 트랜스크립트 스크래퍼

JS 렌더링이 필요하므로 Playwright를 사용하되,
로그인 불필요 — 단순 페이지 렌더링만 수행.

URL 구조:
- 트랜스크립트 목록: /company/{TICKER}/transcripts/
- 개별 트랜스크립트: /company/{TICKER}/transcripts/{YEAR}/{QUARTER}/

페이지 DOM 구조 (트랜스크립트):
    div.flex.flex-col.my-5  (각 speaker 블록)
        div.text-primary > span  (speaker 이름)
        div.p-4  (발언 내용)
"""

import logging
import re

from playwright.async_api import Browser

from .browser import create_browser, close_browser

logger = logging.getLogger(__name__)

_BASE_URL = "https://discountingcashflows.com"

# 날짜 텍스트 패턴: "Nov 19" 등
_DATE_TEXT_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}")


async def list_transcripts(ticker: str, browser: Browser | None = None) -> list[dict]:
    """트랜스크립트 목록 조회.

    Args:
        ticker: 종목 코드
        browser: 기존 브라우저 인스턴스 (None이면 새로 생성)

    Returns:
        [{year: int, quarter: int, date_text: str}, ...]
        최신순 정렬.
    """
    ticker = ticker.upper()
    url = f"{_BASE_URL}/company/{ticker}/transcripts/"

    own_browser = browser is None
    pw = None
    if own_browser:
        pw, browser = await create_browser()

    try:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # JS 렌더링 대기
            await page.wait_for_timeout(3000)

            # 트랜스크립트 링크 추출
            raw_items = await page.evaluate("""(ticker) => {
                const results = [];
                const links = document.querySelectorAll('a');
                const pattern = new RegExp(
                    "/company/" + ticker + "/transcripts/(\\\\d{4})/(\\\\d)/", "i"
                );
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const match = href.match(pattern);
                    if (match) {
                        results.push({
                            year: parseInt(match[1]),
                            quarter: parseInt(match[2]),
                            text: link.textContent.trim(),
                        });
                    }
                }
                return results;
            }""", ticker)

            # 중복 제거 및 정렬
            seen = set()
            items = []
            for raw in raw_items:
                key = (raw["year"], raw["quarter"])
                if key in seen:
                    continue
                seen.add(key)

                # 날짜 텍스트 추출
                date_match = _DATE_TEXT_RE.search(raw.get("text", ""))
                date_text = date_match.group(0) if date_match else ""

                items.append({
                    "year": raw["year"],
                    "quarter": raw["quarter"],
                    "date_text": date_text,
                })

            # 최신순 정렬
            items.sort(key=lambda x: (x["year"], x["quarter"]), reverse=True)
            logger.info(f"{ticker} 트랜스크립트 목록: {len(items)}개")
            return items
        finally:
            await page.close()
    finally:
        if own_browser and pw:
            await close_browser(pw, browser)


async def fetch_transcript_blocks(ticker: str, year: int, quarter: int,
                                  browser: Browser | None = None) -> list[dict]:
    """특정 분기 트랜스크립트를 구조화된 speaker 블록으로 반환.

    Args:
        ticker: 종목 코드
        year: 회계연도
        quarter: 회계분기
        browser: 기존 브라우저 인스턴스 (None이면 새로 생성)

    Returns:
        [{speaker_name: str, content: str}, ...]
    """
    ticker = ticker.upper()
    url = f"{_BASE_URL}/company/{ticker}/transcripts/{year}/{quarter}/"

    own_browser = browser is None
    pw = None
    if own_browser:
        pw, browser = await create_browser()

    try:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # JS 렌더링 대기
            await page.wait_for_timeout(5000)

            # DOM에서 구조화된 speaker 블록 추출
            blocks = await page.evaluate("""() => {
                const results = [];

                // 방법 1: div.flex.flex-col.my-5 블록 (dcf 기본 구조)
                const speakerBlocks = document.querySelectorAll('div.flex.flex-col.my-5');
                if (speakerBlocks.length > 0) {
                    for (const block of speakerBlocks) {
                        const nameEl = block.querySelector('.text-primary span');
                        if (!nameEl) continue;
                        const name = nameEl.textContent.trim();
                        if (!name) continue;

                        const contentEl = block.querySelector('.p-4');
                        if (!contentEl) continue;
                        const content = contentEl.innerText.trim();
                        if (!content) continue;

                        results.push({speaker_name: name, content: content});
                    }
                    if (results.length > 0) return results;
                }

                // 방법 2: Fallback — innerText를 "Name\\nContent" 패턴으로 파싱
                const body = document.body.innerText || '';
                const lines = body.split('\\n');
                let currentSpeaker = '';
                let currentContent = [];
                const namePattern = /^[A-Z][a-zA-Z .'-]+$/;

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;

                    if (namePattern.test(trimmed) && trimmed.length < 50) {
                        if (currentSpeaker && currentContent.length > 0) {
                            results.push({
                                speaker_name: currentSpeaker,
                                content: currentContent.join(' '),
                            });
                        }
                        currentSpeaker = trimmed;
                        currentContent = [];
                    } else if (currentSpeaker) {
                        currentContent.push(trimmed);
                    }
                }
                if (currentSpeaker && currentContent.length > 0) {
                    results.push({
                        speaker_name: currentSpeaker,
                        content: currentContent.join(' '),
                    });
                }

                return results;
            }""")

            if not blocks:
                logger.warning(f"{ticker} FY{year} Q{quarter}: 트랜스크립트 블록이 비어 있습니다")
                return []

            logger.info(f"{ticker} FY{year} Q{quarter} 트랜스크립트: {len(blocks)}블록")
            return blocks
        finally:
            await page.close()
    finally:
        if own_browser and pw:
            await close_browser(pw, browser)


async def find_latest_transcript(ticker: str,
                                 browser: Browser | None = None) -> dict | None:
    """최신 트랜스크립트 정보 반환.

    Args:
        ticker: 종목 코드
        browser: 기존 브라우저 인스턴스 (None이면 새로 생성)

    Returns:
        {year: int, quarter: int, date_text: str} 또는 None
    """
    items = await list_transcripts(ticker, browser=browser)
    if not items:
        return None
    return items[0]
