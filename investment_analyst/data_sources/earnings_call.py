"""기존 earnings_call_agent 파이프라인 래핑

earnings_call_agent의 모듈들을 직접 import하여
어닝콜 트랜스크립트 수집 → 파싱 → 요약을 수행.
"""

import logging
import sys
from pathlib import Path

# earnings_call_agent를 import할 수 있도록 상위 디렉토리를 path에 추가
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from earnings_call_agent.browser import create_browser, close_browser
from earnings_call_agent.dcf import find_latest_transcript, fetch_transcript_blocks
from earnings_call_agent.transcript_parser import classify_and_split
from earnings_call_agent.qa_organizer import organize_qa
from earnings_call_agent.translator import Translator

logger = logging.getLogger(__name__)


async def fetch_earnings_call(ticker: str, api_key: str, model: str) -> dict:
    """어닝콜 분석 파이프라인 실행.

    기존 earnings_call_agent의 모듈을 순차 호출하여
    가이던스, Q&A 요약, 재무지표를 추출.

    Returns:
        {
            "year": int, "quarter": int,
            "guidance": dict, "qa_summary": list,
            "metrics": dict, "error": str | None,
        }
    """
    pw = None
    browser = None
    result = {
        "year": 0, "quarter": 0,
        "guidance": {}, "qa_summary": [], "metrics": {},
        "error": None,
    }

    try:
        # 브라우저 생성
        pw, browser = await create_browser()

        # 최신 트랜스크립트 검색
        latest = await find_latest_transcript(ticker, browser=browser)
        if not latest:
            result["error"] = f"No transcript found for {ticker}"
            return result

        year = latest["year"]
        quarter = latest["quarter"]
        result["year"] = year
        result["quarter"] = quarter

        # 트랜스크립트 블록 스크래핑
        raw_blocks = await fetch_transcript_blocks(ticker, year, quarter, browser=browser)
        if not raw_blocks:
            result["error"] = f"Empty transcript for {ticker} FY{year} Q{quarter}"
            return result

        # 역할 분류 + Q&A 분리
        prepared_remarks, qa_blocks = classify_and_split(raw_blocks)

        translator = Translator(api_key=api_key, model=model)

        # 가이던스 추출
        try:
            result["guidance"] = await translator.extract_guidance(prepared_remarks)
        except Exception as e:
            logger.warning(f"가이던스 추출 실패: {e}")

        # 재무지표 추출 (어닝콜에서 언급된 수치)
        try:
            result["metrics"] = await translator.extract_metrics_from_remarks(prepared_remarks)
        except Exception as e:
            logger.warning(f"재무지표 추출 실패: {e}")

        # Q&A 요약
        if qa_blocks:
            try:
                qa_pairs = organize_qa(qa_blocks)
                if qa_pairs:
                    result["qa_summary"] = await translator.summarize_qa_pairs(qa_pairs)
            except Exception as e:
                logger.warning(f"Q&A 요약 실패: {e}")

        logger.info(
            f"[EarningsCall] {ticker} FY{year} Q{quarter} 분석 완료: "
            f"guidance={bool(result['guidance'])}, "
            f"qa={len(result['qa_summary'])}개, "
            f"metrics={list(result['metrics'].keys())}"
        )

    except Exception as e:
        logger.error(f"[EarningsCall] {ticker} 분석 실패: {e}")
        result["error"] = str(e)

    finally:
        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.warning(f"브라우저 닫기 실패: {e}")
        if pw:
            try:
                await pw.stop()
            except Exception as e:
                logger.warning(f"Playwright 종료 실패: {e}")

    return result
