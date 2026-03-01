"""IR 프레젠테이션 자동 수집 (LLM + Playwright)

LLM으로 기업별 IR presentations 페이지 URL 후보를 획득한 뒤
Playwright로 접속하여 PDF 링크를 추출하고 다운로드.

LLM URL이 모두 실패하면 DuckDuckGo 검색 fallback으로 재시도.
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import httpx
from playwright.async_api import Browser, Page

from .config import (
    DOWNLOADS_DIR,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
)
from .models import Company, Presentation

logger = logging.getLogger(__name__)

# PDF 링크 필터링 키워드 (확장)
_PDF_KEYWORDS = re.compile(
    r"present|slide|deck|investor|earning|annual|quarter"
    r"|supplement|result|financial|report|overview|guidance"
    r"|shareholder|conference|outlook|fiscal|FY\d{2,4}|Q[1-4]"
    r"|strategy|update|letter",
    re.IGNORECASE,
)

# IR 페이지 URL 패턴 — 매칭 시 키워드 필터 비활성화
_IR_PAGE_PATTERN = re.compile(
    r"/investor|/ir/|/ir\b|investor-relations|events.*presentation",
    re.IGNORECASE,
)

# 다운로드 동시 요청 제한
_DOWNLOAD_SEM_LIMIT = 3

# httpx 공용 헤더
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── LLM으로 IR 페이지 URL 후보 획득 ──

async def _ask_llm_for_ir_urls(company: Company) -> list[str]:
    """LLM에 IR 페이지 URL 후보 6개를 요청 (다중 카테고리)."""
    prompt = (
        f"For the company {company.name} (ticker: {company.ticker}), "
        f"provide up to 6 candidate URLs for their Investor Relations pages.\n\n"
        f"Include URLs from MULTIPLE categories if possible:\n"
        f"- Events & Presentations page\n"
        f"- Quarterly earnings / results page\n"
        f"- Annual reports page\n"
        f"- SEC filings / financial info page\n\n"
        f"Return a JSON array of up to 6 URL strings, ordered by likelihood. Example:\n"
        f'["https://investor.nvidia.com/events-and-presentations", '
        f'"https://investor.nvidia.com/financial-info/quarterly-results", '
        f'"https://investor.nvidia.com/financial-info/annual-reports", '
        f'"https://investor.nvidia.com/financial-info/sec-filings", '
        f'"https://nvidianews.nvidia.com/events", '
        f'"https://investor.nvidia.com/financial-info/presentations"]\n\n'
        f"Return ONLY the JSON array, no explanation."
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Return only the requested JSON array of URLs."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        # JSON 배열 추출 (마크다운 코드블록 처리)
        cleaned = content
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1:
            urls = json.loads(cleaned[start:end + 1])
            urls = [u.strip() for u in urls if isinstance(u, str) and u.startswith("http")]
            logger.info(f"[IR] {company.ticker} LLM 후보 URL {len(urls)}개: {urls}")
            return urls
        # 단일 URL fallback
        url_match = re.search(r"https?://[^\s<>\"']+", content)
        if url_match:
            return [url_match.group(0).rstrip(".,;)")]
    except Exception as e:
        logger.error(f"[IR] {company.ticker} LLM 호출 실패: {e}")
    return []


# ── DuckDuckGo 검색 fallback ──

async def _search_ir_urls_ddg(company: Company) -> list[dict]:
    """DuckDuckGo HTML 검색으로 IR 관련 URL 목록을 찾는다.

    Returns:
        [{"url": str, "is_pdf": bool}, ...]
    """
    query = f"{company.name} {company.ticker} investor relations presentations"
    search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"

    try:
        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            follow_redirects=True,
            timeout=15,
        ) as client:
            resp = await client.get(search_url)
            resp.raise_for_status()
            html = resp.text

        # DuckDuckGo HTML 버전 URL 추출 (uddg= redirect)
        url_pattern = re.compile(r'uddg=(https?[^&"]+)')
        matches = url_pattern.findall(html)

        results = []
        seen = set()
        ir_keywords = re.compile(r"investor|ir\.|\/ir\/|presentations|events", re.IGNORECASE)

        for match in matches:
            url = unquote(match)
            if url in seen:
                continue
            seen.add(url)

            is_pdf = url.lower().endswith(".pdf") or ".pdf?" in url.lower()
            has_ir = bool(ir_keywords.search(url))

            # 직접 PDF — IR 검색어로 나온 결과이므로 키워드 필터 없이 수집
            if is_pdf:
                results.append({"url": url, "is_pdf": True})
            elif has_ir:
                results.append({"url": url, "is_pdf": False})

        logger.info(f"[IR] {company.ticker} DuckDuckGo 결과 {len(results)}개")
        return results[:5]
    except Exception as e:
        logger.warning(f"[IR] {company.ticker} DuckDuckGo 검색 실패: {e}")
    return []


# ── Playwright로 페이지 접속 + PDF 링크 추출 ──

async def _visit_and_extract(
    url: str, ticker: str, browser: Browser
) -> tuple[list[dict], list[str]]:
    """IR 페이지에 접속하고 PDF 링크 + sibling IR 페이지를 추출.

    Returns:
        (pdf_links, sibling_urls) — 실패 시 ([], [])
    """
    # stealth: navigator.webdriver 숨기기
    stealth_script = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    """

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720},
        locale="en-US",
    )
    await context.add_init_script(stealth_script)
    page = await context.new_page()
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if not resp or not resp.ok:
            logger.warning(
                f"[IR] {ticker} 페이지 접속 실패 "
                f"(status={resp.status if resp else 'N/A'}, url={url})"
            )
            return [], []

        # JS 렌더링 대기
        await page.wait_for_timeout(5000)

        # 페이지네이션 / Load More 확장
        await _expand_all_content(page)

        # IR 페이지이면 키워드 필터 비활성화
        skip_filter = bool(_IR_PAGE_PATTERN.search(url))

        pdf_links = await _extract_pdf_links(page, url, skip_keyword_filter=skip_filter)

        # sibling IR 페이지 탐색
        siblings = await _discover_sibling_ir_pages(page, url)

        return pdf_links, siblings
    except Exception as e:
        logger.error(f"[IR] {ticker} 페이지 처리 실패: {e}")
        return [], []
    finally:
        await context.close()


async def _expand_all_content(page: Page) -> None:
    """페이지네이션 / Load More / lazy loading 콘텐츠 확장.

    1. "Show All" / "View All" 링크 클릭
    2. "Load More" 버튼 반복 클릭 (최대 10회)
    3. 페이지 하단까지 스크롤 (lazy loading 대응)
    """
    # 1) "Show All" / "View All" 링크 클릭
    try:
        show_all = await page.query_selector(
            'a:text-matches("(Show|View|See)\\s+(All|More)", "i")'
        )
        if show_all and await show_all.is_visible():
            await show_all.click()
            await page.wait_for_timeout(3000)
            logger.debug("[IR] 'Show/View All' 링크 클릭 완료")
    except Exception as e:
        logger.debug(f"[IR] 'Show/View All' 클릭 실패 (무시): {e}")

    # 2) "Load More" 버튼 반복 클릭
    for _ in range(10):
        try:
            load_more = await page.query_selector(
                'button:text-matches("(Load|Show)\\s+More", "i"), '
                'a:text-matches("(Load|Show)\\s+More", "i"), '
                '[class*="load-more"], [class*="loadMore"]'
            )
            if load_more and await load_more.is_visible():
                await load_more.click()
                await page.wait_for_timeout(2000)
                logger.debug("[IR] 'Load More' 버튼 클릭")
            else:
                break
        except Exception:
            break

    # 3) 스크롤 다운 (lazy loading 대응)
    for _ in range(5):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await page.wait_for_timeout(800)


async def _extract_pdf_links(
    page: Page, base_url: str, *, skip_keyword_filter: bool = False
) -> list[dict]:
    """DOM에서 PDF 링크 추출. skip_keyword_filter=True면 모든 PDF 수집."""
    raw_links = await page.evaluate("""() => {
        const results = [];
        const anchors = document.querySelectorAll('a[href]');
        for (const a of anchors) {
            const href = a.getAttribute('href') || '';
            const lower = href.toLowerCase();
            if (lower.endsWith('.pdf') || lower.includes('.pdf?') || lower.includes('.pdf#')) {
                results.push({
                    href: href,
                    text: a.textContent.trim(),
                });
            }
        }
        return results;
    }""")

    pdf_links = []
    seen_urls = set()

    for item in raw_links:
        href = item["href"]
        text = item["text"]

        full_url = urljoin(base_url, href)

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        if skip_keyword_filter or _PDF_KEYWORDS.search(f"{full_url} {text}"):
            pdf_links.append({"url": full_url, "text": text})

    logger.info(f"[IR] PDF 링크 {len(pdf_links)}개 추출 (전체 PDF: {len(raw_links)}개)")
    return pdf_links


async def _discover_sibling_ir_pages(page: Page, base_url: str) -> list[str]:
    """현재 IR 페이지 네비게이션에서 다른 IR 섹션 링크를 추출."""
    ir_nav_pattern = re.compile(
        r"presentation|event|earning|quarter|annual|result|financial|report",
        re.IGNORECASE,
    )
    try:
        nav_links = await page.evaluate("""() => {
            const results = [];
            const navs = document.querySelectorAll('nav a[href], [role="navigation"] a[href], .nav a[href], .menu a[href], .sidebar a[href], .subnav a[href]');
            for (const a of navs) {
                results.push({
                    href: a.getAttribute('href') || '',
                    text: a.textContent.trim(),
                });
            }
            return results;
        }""")

        sibling_urls = []
        seen = {base_url}
        base_domain = urlparse(base_url).netloc

        for link in nav_links:
            full_url = urljoin(base_url, link["href"])
            parsed = urlparse(full_url)
            # 같은 도메인, IR 관련 텍스트/URL
            if parsed.netloc != base_domain:
                continue
            if full_url in seen:
                continue
            combined = f"{full_url} {link['text']}"
            if ir_nav_pattern.search(combined):
                seen.add(full_url)
                sibling_urls.append(full_url)

        logger.info(f"[IR] sibling IR 페이지 {len(sibling_urls)}개 발견")
        return sibling_urls[:5]
    except Exception as e:
        logger.debug(f"[IR] sibling 탐색 실패: {e}")
        return []


# ── PDF 다운로드 ──

async def _download_pdf(
    url: str,
    ticker: str,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> str | None:
    """PDF 파일을 다운로드하여 로컬에 저장. 반환: 파일 경로 또는 None."""
    save_dir = DOWNLOADS_DIR / ticker / "ir"
    save_dir.mkdir(parents=True, exist_ok=True)

    # URL에서 파일명 추출
    parsed = urlparse(url)
    raw_name = Path(unquote(parsed.path)).name
    if not raw_name or not raw_name.lower().endswith(".pdf"):
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        raw_name = f"{ticker}_presentation_{url_hash}.pdf"

    safe_name = re.sub(r"[^\w.\-]", "_", raw_name)
    save_path = save_dir / safe_name

    # 이미 존재하면 스킵
    if save_path.exists() and save_path.stat().st_size > 0:
        logger.info(f"[IR] 이미 존재: {save_path}")
        return str(save_path)

    async with sem:
        try:
            resp = await client.get(url, follow_redirects=True, timeout=60)
            resp.raise_for_status()

            ct = resp.headers.get("content-type", "")
            if "pdf" not in ct and "octet-stream" not in ct:
                logger.warning(f"[IR] PDF가 아닌 응답: {ct} — {url}")
                return None

            save_path.write_bytes(resp.content)
            size_kb = len(resp.content) / 1024
            logger.info(f"[IR] 다운로드 완료: {save_path} ({size_kb:.0f}KB)")
            return str(save_path)
        except Exception as e:
            logger.error(f"[IR] 다운로드 실패 ({url}): {e}")
            return None


# ── 공개 API ──

async def fetch_presentations_for_company(
    company: Company,
    browser: Browser,
    max_count: int = 20,
) -> list[Presentation]:
    """기업의 IR 프레젠테이션 PDF를 수집.

    1단계: LLM 후보 URL → 모든 유효 URL 순회 + sibling 탐색
    2단계: 부족하면 DuckDuckGo fallback
    3단계: PDF 다운로드

    Args:
        company: 대상 기업
        browser: 공유 Playwright 브라우저
        max_count: 최대 다운로드 수 (기본 20)

    Returns:
        Presentation 목록
    """
    pdf_links: list[dict] = []
    direct_pdf_urls: list[dict] = []
    seen_pdf_urls: set[str] = set()

    def _add_unique(links: list[dict], target: list[dict]) -> None:
        """중복 제거하며 PDF 링크 누적."""
        for link in links:
            if link["url"] not in seen_pdf_urls:
                seen_pdf_urls.add(link["url"])
                target.append(link)

    # ── 1단계: LLM 후보 URL → 모든 유효 URL 순회 ──
    candidate_urls = await _ask_llm_for_ir_urls(company)
    visited_urls: set[str] = set()
    sibling_queue: list[str] = []
    sibling_seen: set[str] = set()

    for url in candidate_urls:
        if url in visited_urls:
            continue
        visited_urls.add(url)

        page_pdfs, siblings = await _visit_and_extract(url, company.ticker, browser)
        _add_unique(page_pdfs, pdf_links)

        # sibling URL 큐에 추가 (중복 방지)
        for s in siblings:
            if s not in visited_urls and s not in sibling_seen:
                sibling_seen.add(s)
                sibling_queue.append(s)

    # sibling IR 페이지 순회
    for url in sibling_queue:
        if url in visited_urls:
            continue
        visited_urls.add(url)
        page_pdfs, _ = await _visit_and_extract(url, company.ticker, browser)
        _add_unique(page_pdfs, pdf_links)

    # ── 2단계: DuckDuckGo fallback (PDF가 부족할 때) ──
    if len(pdf_links) < max_count:
        logger.info(
            f"[IR] {company.ticker}: LLM URL에서 {len(pdf_links)}개 수집, "
            f"DuckDuckGo fallback 시도"
        )
        ddg_results = await _search_ir_urls_ddg(company)

        # 직접 PDF URL — IR 검색어로 나온 PDF이므로 키워드 필터 제거
        for r in ddg_results:
            if r["is_pdf"]:
                _add_unique([{"url": r["url"], "text": ""}], direct_pdf_urls)

        # IR 페이지 URL 시도
        for r in ddg_results:
            if not r["is_pdf"] and r["url"] not in visited_urls:
                visited_urls.add(r["url"])
                page_pdfs, _ = await _visit_and_extract(
                    r["url"], company.ticker, browser
                )
                _add_unique(page_pdfs, pdf_links)

    # 페이지 추출 PDF + 직접 PDF URL 합산
    all_pdf_links = pdf_links + direct_pdf_urls
    if not all_pdf_links:
        logger.warning(f"[IR] {company.ticker}: 매칭되는 PDF 링크 없음")
        return []

    # 최대 N개로 제한
    all_pdf_links = all_pdf_links[:max_count]

    # ── 3단계: PDF 다운로드 ──
    sem = asyncio.Semaphore(_DOWNLOAD_SEM_LIMIT)
    presentations = []

    async with httpx.AsyncClient(headers=_BROWSER_HEADERS) as client:
        tasks = [
            _download_pdf(link["url"], company.ticker, sem, client)
            for link in all_pdf_links
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for link, res in zip(all_pdf_links, results):
            if isinstance(res, Exception):
                logger.error(f"[IR] {company.ticker} 다운로드 예외: {res}")
                continue
            if res:
                title = (
                    link["text"]
                    or Path(unquote(urlparse(link["url"]).path)).stem
                    or f"{company.ticker}_presentation"
                )
                presentations.append(Presentation(
                    ticker=company.ticker,
                    title=title,
                    url=link["url"],
                    local_path=res,
                ))

    logger.info(f"[IR] {company.ticker}: {len(presentations)}개 프레젠테이션 수집 완료")
    return presentations
