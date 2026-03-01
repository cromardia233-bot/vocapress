"""SEC EDGAR 10-K/10-Q 다운로드

CIK 조회 → Submissions API → Filing HTML 다운로드.
asyncio.Semaphore로 SEC rate limit(10req/s) 준수.
"""

import asyncio
import logging
from pathlib import Path

import httpx

from .config import SEC_USER_AGENT, SEC_SEMAPHORE_LIMIT, SEC_REQUEST_DELAY, DOWNLOADS_DIR
from .models import Company, Filing

logger = logging.getLogger(__name__)

# ── CIK 조회 (edgar_fetcher.py에서 재사용) ──

_CIK_CACHE: dict[str, str] = {}
_TICKERS_DATA: dict | None = None
_TICKERS_LOCK: asyncio.Lock | None = None


def _get_tickers_lock() -> asyncio.Lock:
    """이벤트 루프 내에서 Lock을 lazy 생성."""
    global _TICKERS_LOCK
    if _TICKERS_LOCK is None:
        _TICKERS_LOCK = asyncio.Lock()
    return _TICKERS_LOCK


async def get_cik(ticker: str) -> str | None:
    """티커 → CIK 번호 변환 (캐싱 적용)."""
    global _TICKERS_DATA

    ticker_upper = ticker.upper()
    if ticker_upper in _CIK_CACHE:
        return _CIK_CACHE[ticker_upper]

    async with _get_tickers_lock():
        # double-check: 락 대기 중 다른 코루틴이 로드했을 수 있음
        if _TICKERS_DATA is None:
            url = "https://www.sec.gov/files/company_tickers.json"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT})
                resp.raise_for_status()
                _TICKERS_DATA = resp.json()

    for entry in _TICKERS_DATA.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            _CIK_CACHE[ticker_upper] = cik
            return cik
    return None


# ── Submissions API → Filing 목록 추출 ──

async def _fetch_recent_filings(
    cik: str,
    form_types: list[str],
    count_per_type: int,
    client: httpx.AsyncClient,
) -> list[dict]:
    """SEC Submissions API에서 최근 filing 목록 조회."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT})
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    type_counts: dict[str, int] = {ft: 0 for ft in form_types}

    for i, form in enumerate(forms):
        if form not in form_types:
            continue
        if type_counts[form] >= count_per_type:
            continue
        type_counts[form] += 1
        results.append({
            "form_type": form,
            "accession_number": accessions[i].replace("-", ""),
            "filed_date": dates[i],
            "primary_document": primary_docs[i],
        })
        # 모든 타입이 충분히 수집되었으면 조기 종료
        if all(c >= count_per_type for c in type_counts.values()):
            break

    return results


# ── Filing HTML 다운로드 ──

async def _download_filing(
    cik: str,
    filing: dict,
    ticker: str,
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> Filing | None:
    """단일 filing HTML 다운로드."""
    accession = filing["accession_number"]
    primary_doc = filing["primary_document"]
    # CIK 선행 0 제거 (SEC 리다이렉트 방지)
    cik_stripped = cik.lstrip("0") or "0"
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accession}/{primary_doc}"

    # 저장 경로
    save_dir = DOWNLOADS_DIR / ticker / "sec"
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}_{filing['form_type']}_{filing['filed_date']}_{primary_doc}"
    save_path = save_dir / filename

    async with sem:
        try:
            await asyncio.sleep(SEC_REQUEST_DELAY)
            resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=60)
            resp.raise_for_status()
            save_path.write_bytes(resp.content)
            logger.info(f"[SEC] {ticker} {filing['form_type']} 다운로드 완료: {filename}")
            return Filing(
                ticker=ticker,
                form_type=filing["form_type"],
                filed_date=filing["filed_date"],
                accession_number=accession,
                primary_document=primary_doc,
                local_path=str(save_path),
            )
        except Exception as e:
            logger.error(f"[SEC] {ticker} {filing['form_type']} 다운로드 실패: {e}")
            return None


# ── 공개 API ──

async def download_filings_for_company(
    company: Company,
    form_types: list[str] | None = None,
    count_per_type: int = 2,
) -> list[Filing]:
    """한 기업의 SEC filing을 다운로드.

    Args:
        company: CIK가 설정된 Company 객체
        form_types: 다운로드할 filing 유형 (기본: 10-K, 10-Q)
        count_per_type: 유형당 다운로드 수

    Returns:
        성공적으로 다운로드된 Filing 목록
    """
    if form_types is None:
        form_types = ["10-K", "10-Q"]

    if not company.cik:
        logger.warning(f"[SEC] {company.ticker}: CIK 없음, 건너뜀")
        return []

    sem = asyncio.Semaphore(SEC_SEMAPHORE_LIMIT)
    filings = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # filing 목록 조회
        try:
            filing_list = await _fetch_recent_filings(
                company.cik, form_types, count_per_type, client
            )
        except Exception as e:
            logger.error(f"[SEC] {company.ticker} filing 목록 조회 실패: {e}")
            return []

        if not filing_list:
            logger.warning(f"[SEC] {company.ticker}: 해당 filing 없음")
            return []

        # 병렬 다운로드
        tasks = [
            _download_filing(company.cik, f, company.ticker, sem, client)
            for f in filing_list
        ]
        results = await asyncio.gather(*tasks)
        filings = [r for r in results if r is not None]

    return filings


async def resolve_ciks(companies: list[Company]) -> list[Company]:
    """여러 기업의 CIK를 병렬 조회하여 설정.

    CIK 조회 실패한 기업은 에러 로그 후 cik=None으로 유지.
    """
    async def _resolve_one(company: Company):
        try:
            cik = await get_cik(company.ticker)
            if cik:
                company.cik = cik
            else:
                logger.warning(f"[CIK] {company.ticker}: CIK 찾기 실패")
        except Exception as e:
            logger.error(f"[CIK] {company.ticker}: 조회 오류 — {e}")

    await asyncio.gather(*[_resolve_one(c) for c in companies])
    return companies
