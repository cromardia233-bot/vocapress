"""메인 파이프라인 오케스트레이션

5단계: 밸류체인 분석 → CIK 조회 → IR자료 다운로드 → Drive 업로드 → NotebookLM 안내
"""

import asyncio
import logging

from .config import validate_config
from .models import Company, PipelineResult
from .valuechain_llm import analyze_valuechain
from .sec_downloader import resolve_ciks, download_filings_for_company
from .transcript_fetcher import (
    create_browser,
    close_browser,
    fetch_transcripts_for_company,
)
from .ir_fetcher import fetch_presentations_for_company
from .drive_uploader import upload_to_drive

logger = logging.getLogger(__name__)


async def run_pipeline(
    ticker: str,
    skip_drive: bool = False,
    num_filings_per_type: int = 2,
    num_transcript_quarters: int = 4,
    max_ir_count: int = 20,
) -> PipelineResult:
    """전체 파이프라인 실행.

    Args:
        ticker: 분석 대상 미국 주식 티커
        skip_drive: True이면 Google Drive 업로드 건너뜀
        num_filings_per_type: filing 유형당 다운로드 수
        num_transcript_quarters: 어닝콜 수집 분기 수
        max_ir_count: IR 프레젠테이션 최대 다운로드 수

    Returns:
        PipelineResult
    """
    ticker = ticker.upper()
    result = PipelineResult(target_ticker=ticker)

    # 필수 설정 검증
    validate_config()

    # ── 1단계: 밸류체인 분석 ──
    print(f"\n[1/5] {ticker} 밸류체인 분석 중...")
    try:
        related_companies = await analyze_valuechain(ticker)
    except Exception as e:
        result.errors.append(f"밸류체인 분석 실패: {e}")
        print(f"  ✗ 밸류체인 분석 실패: {e}")
        return result

    if not related_companies:
        msg = "밸류체인 분석 결과 관련 기업이 없습니다. LLM 응답을 확인하세요."
        result.errors.append(msg)
        print(f"  ⚠ {msg}")

    # target 기업 추가
    target = Company(ticker=ticker, name=ticker, role="target")
    all_companies = [target] + related_companies
    result.companies = all_companies

    print(f"  ✓ {len(related_companies)}개 관련 기업 식별")
    for c in related_companies:
        print(f"    - {c.ticker} ({c.name}): {c.role} — {c.description}")

    # ── 2단계: CIK 조회 ──
    print(f"\n[2/5] CIK 조회 중 ({len(all_companies)}개 기업)...")
    await resolve_ciks(all_companies)

    cik_found = [c for c in all_companies if c.cik]
    cik_failed = [c for c in all_companies if not c.cik]
    print(f"  ✓ CIK 조회 성공: {len(cik_found)}개")
    for c in cik_failed:
        msg = f"CIK 조회 실패: {c.ticker}"
        result.errors.append(msg)
        print(f"  ✗ {msg}")

    # ── 3단계: IR자료 비동기 다운로드 ──
    print(f"\n[3/5] SEC filing + 어닝콜 트랜스크립트 + IR 프레젠테이션 다운로드 중...")

    # Playwright 브라우저 공유
    pw, browser = await create_browser()
    try:
        # SEC filings 비동기 다운로드
        filing_tasks = [
            download_filings_for_company(c, count_per_type=num_filings_per_type)
            for c in cik_found
        ]
        # 어닝콜 트랜스크립트 (순차 — 동일 사이트 rate limit)
        all_filings_results = await asyncio.gather(*filing_tasks, return_exceptions=True)

        for i, res in enumerate(all_filings_results):
            if isinstance(res, Exception):
                msg = f"SEC filing 다운로드 실패 ({cik_found[i].ticker}): {res}"
                result.errors.append(msg)
                logger.error(msg)
            else:
                result.filings.extend(res)

        print(f"  ✓ SEC filing {len(result.filings)}개 다운로드 완료")

        # 어닝콜 트랜스크립트 (순차 처리 — 웹사이트 부하 방지)
        for company in all_companies:
            try:
                transcripts = await fetch_transcripts_for_company(
                    company, browser, num_quarters=num_transcript_quarters
                )
                result.transcripts.extend(transcripts)
                if transcripts:
                    print(f"    - {company.ticker}: {len(transcripts)}개 트랜스크립트")
            except Exception as e:
                msg = f"트랜스크립트 수집 실패 ({company.ticker}): {e}"
                result.errors.append(msg)
                logger.error(msg)

        print(f"  ✓ 어닝콜 트랜스크립트 {len(result.transcripts)}개 수집 완료")

        # IR 프레젠테이션 (순차 처리 — 사이트별 rate limit 존중)
        print(f"  ▸ IR 프레젠테이션 수집 중...")
        for company in all_companies:
            try:
                presentations = await fetch_presentations_for_company(
                    company, browser, max_count=max_ir_count
                )
                result.presentations.extend(presentations)
                if presentations:
                    print(f"    - {company.ticker}: {len(presentations)}개 프레젠테이션")
            except Exception as e:
                msg = f"IR 프레젠테이션 수집 실패 ({company.ticker}): {e}"
                result.errors.append(msg)
                logger.error(msg)

        print(f"  ✓ IR 프레젠테이션 {len(result.presentations)}개 수집 완료")
    finally:
        await close_browser(pw, browser)

    # ── 4단계: Google Drive 업로드 ──
    if skip_drive:
        print(f"\n[4/5] Google Drive 업로드 건너뜀 (--no-drive)")
    else:
        print(f"\n[4/5] Google Drive 업로드 중...")
        all_paths = []
        for f in result.filings:
            if f.local_path:
                all_paths.append(f.local_path)
        for t in result.transcripts:
            if t.local_path:
                all_paths.append(t.local_path)
        for p in result.presentations:
            if p.local_path:
                all_paths.append(p.local_path)

        if all_paths:
            try:
                folder_url = upload_to_drive(ticker, all_paths)
                result.drive_folder_url = folder_url
                print(f"  ✓ {len(all_paths)}개 파일 업로드 완료")
            except Exception as e:
                msg = f"Drive 업로드 실패: {e}"
                result.errors.append(msg)
                print(f"  ✗ {msg}")
        else:
            print(f"  ✗ 업로드할 파일 없음")

    # ── 5단계: NotebookLM 연동 안내 ──
    print(f"\n[5/5] NotebookLM 연동 안내")
    print("=" * 60)
    if result.drive_folder_url:
        print(f"\n  Google Drive 폴더: {result.drive_folder_url}")
        print(f"\n  NotebookLM에서 소스를 추가하려면:")
        print(f"  1. https://notebooklm.google.com 접속")
        print(f"  2. 새 노트북 생성")
        print(f"  3. 'Add source' → 'Google Drive' 선택")
        print(f"  4. 위 Drive 폴더에서 파일을 선택하여 추가")
    else:
        local_dir = f"valuechain_analyzer/_downloads/{ticker}/"
        print(f"\n  로컬 다운로드 경로: {local_dir}")
        print(f"  Google Drive에 수동으로 업로드한 뒤 NotebookLM에서 소스로 추가하세요.")
    print("=" * 60)

    # 에러 요약
    if result.errors:
        print(f"\n⚠ {len(result.errors)}개 에러 발생:")
        for err in result.errors:
            print(f"  - {err}")

    return result
