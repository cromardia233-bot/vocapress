"""어닝콜 트랜스크립트 수집 (Playwright)

discountingcashflows.com에서 최근 N분기 트랜스크립트를 스크래핑한 뒤
speaker 블록을 텍스트 파일로 변환 저장.

browser.py + dcf.py 로직을 재사용.
"""

import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright, Browser, Playwright

from .config import DOWNLOADS_DIR
from .models import Company, Transcript

logger = logging.getLogger(__name__)

_BASE_URL = "https://discountingcashflows.com"
_DATE_TEXT_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}")


# ── 브라우저 관리 (browser.py 재사용) ──

async def create_browser(headless: bool = True) -> tuple[Playwright, Browser]:
    """Playwright 브라우저 생성."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ],
    )
    # keepalive context+page (프로세스 종료 방지)
    _ctx = await browser.new_context()
    await _ctx.new_page()
    logger.debug("브라우저 생성 완료")
    return pw, browser


async def close_browser(pw: Playwright, browser: Browser):
    """브라우저 리소스 정리."""
    try:
        await browser.close()
    except Exception as e:
        logger.warning(f"브라우저 닫기 실패: {e}")
    try:
        await pw.stop()
    except Exception as e:
        logger.warning(f"Playwright 종료 실패: {e}")


# ── 트랜스크립트 목록 조회 (dcf.py 재사용) ──

async def _list_transcripts(ticker: str, browser: Browser) -> list[dict]:
    """트랜스크립트 목록 조회 (최신순 정렬)."""
    ticker = ticker.upper()
    url = f"{_BASE_URL}/company/{ticker}/transcripts/"

    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

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

        seen = set()
        items = []
        for raw in raw_items:
            key = (raw["year"], raw["quarter"])
            if key in seen:
                continue
            seen.add(key)
            date_match = _DATE_TEXT_RE.search(raw.get("text", ""))
            date_text = date_match.group(0) if date_match else ""
            items.append({
                "year": raw["year"],
                "quarter": raw["quarter"],
                "date_text": date_text,
            })

        items.sort(key=lambda x: (x["year"], x["quarter"]), reverse=True)
        logger.info(f"{ticker} 트랜스크립트 목록: {len(items)}개")
        return items
    finally:
        await page.close()


# ── 트랜스크립트 본문 추출 (dcf.py 재사용) ──

async def _fetch_transcript_blocks(
    ticker: str, year: int, quarter: int, browser: Browser
) -> list[dict]:
    """특정 분기 트랜스크립트를 speaker 블록으로 반환."""
    ticker = ticker.upper()
    url = f"{_BASE_URL}/company/{ticker}/transcripts/{year}/{quarter}/"

    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        blocks = await page.evaluate("""() => {
            const results = [];

            // 방법 1: DOM 구조 활용
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

            // 방법 2: Fallback — innerText 파싱
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
            logger.warning(f"{ticker} FY{year} Q{quarter}: 트랜스크립트 블록 없음")
        else:
            logger.info(f"{ticker} FY{year} Q{quarter} 트랜스크립트: {len(blocks)}블록")
        return blocks or []
    finally:
        await page.close()


# ── 텍스트 파일 변환 저장 ──

def _save_transcript_text(ticker: str, year: int, quarter: int, blocks: list[dict]) -> str:
    """speaker 블록을 텍스트 파일로 저장. 반환: 파일 경로."""
    save_dir = DOWNLOADS_DIR / ticker / "earnings"
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{ticker}_FY{year}_Q{quarter}_earnings_call.txt"
    save_path = save_dir / filename

    lines = [f"# {ticker} FY{year} Q{quarter} Earnings Call Transcript\n\n"]
    for block in blocks:
        speaker = block.get("speaker_name", "Unknown")
        content = block.get("content", "")
        lines.append(f"## {speaker}\n{content}\n\n")

    save_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"[Transcript] 저장: {save_path}")
    return str(save_path)


# ── 공개 API ──

async def fetch_transcripts_for_company(
    company: Company,
    browser: Browser,
    num_quarters: int = 4,
) -> list[Transcript]:
    """한 기업의 최근 N분기 어닝콜 트랜스크립트 수집 및 저장.

    Args:
        company: 대상 기업
        browser: 공유 Playwright 브라우저
        num_quarters: 수집할 분기 수

    Returns:
        Transcript 목록
    """
    try:
        items = await _list_transcripts(company.ticker, browser)
    except Exception as e:
        logger.error(f"[Transcript] {company.ticker} 목록 조회 실패: {e}")
        return []

    # 최근 N분기만
    items = items[:num_quarters]
    transcripts = []

    for item in items:
        try:
            blocks = await _fetch_transcript_blocks(
                company.ticker, item["year"], item["quarter"], browser
            )
            if not blocks:
                continue

            local_path = _save_transcript_text(
                company.ticker, item["year"], item["quarter"], blocks
            )
            transcripts.append(Transcript(
                ticker=company.ticker,
                year=item["year"],
                quarter=item["quarter"],
                date_text=item.get("date_text", ""),
                blocks=blocks,
                local_path=local_path,
            ))
        except Exception as e:
            logger.error(
                f"[Transcript] {company.ticker} FY{item['year']} Q{item['quarter']} 실패: {e}"
            )

    return transcripts
