"""OpenAI Agents SDK @function_tool 정의

각 도구는 RunContextWrapper[EarningsCallContext]를 통해
파이프라인 전체에서 공유되는 상태에 접근한다.
"""

import logging

from agents import function_tool, RunContextWrapper

from .browser import create_browser, close_browser
from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from .context import EarningsCallContext
from .dcf import find_latest_transcript, fetch_transcript_blocks
from .qa_organizer import organize_qa
from .report_formatter import format_report
from .transcript_parser import classify_and_split
from .translator import Translator

logger = logging.getLogger(__name__)


@function_tool
async def fetch_transcript(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Fetch the latest earnings call transcript for the ticker stored in context."""
    ec = ctx.context

    # 브라우저 생성
    if ec.browser is None:
        ec.pw, ec.browser = await create_browser()

    # 최신 트랜스크립트 검색
    latest = await find_latest_transcript(ec.ticker, browser=ec.browser)
    if not latest:
        return f"ERROR: No transcript found for {ec.ticker}"

    ec.year = latest["year"]
    ec.quarter = latest["quarter"]

    # 블록 스크래핑
    blocks = await fetch_transcript_blocks(
        ec.ticker, ec.year, ec.quarter, browser=ec.browser
    )
    if not blocks:
        return (
            f"ERROR: Transcript blocks empty for "
            f"{ec.ticker} FY{ec.year} Q{ec.quarter}"
        )

    ec.raw_blocks = blocks
    return (
        f"OK: Fetched {len(blocks)} blocks for "
        f"{ec.ticker} FY{ec.year} Q{ec.quarter}"
    )


@function_tool
async def parse_transcript_blocks(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Parse raw transcript blocks into prepared remarks and Q&A sections."""
    ec = ctx.context
    if not ec.raw_blocks:
        return "ERROR: No raw blocks to parse"

    ec.prepared_remarks, ec.qa_blocks = classify_and_split(ec.raw_blocks)
    return (
        f"OK: {len(ec.prepared_remarks)} prepared remarks, "
        f"{len(ec.qa_blocks)} Q&A blocks"
    )


@function_tool
async def analyze_qa(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Organize Q&A blocks into pairs and summarize them with LLM."""
    ec = ctx.context
    if not ec.qa_blocks:
        return "SKIP: No Q&A blocks to analyze"

    # Q&A 구조화
    ec.qa_pairs = organize_qa(ec.qa_blocks)
    if not ec.qa_pairs:
        return "SKIP: No substantive Q&A pairs found"

    # LLM 요약
    translator = Translator(api_key=OPENROUTER_API_KEY, model=OPENROUTER_MODEL)
    ec.qa_summary = await translator.summarize_qa_pairs(ec.qa_pairs)
    return (
        f"OK: {len(ec.qa_pairs)} Q&A pairs → "
        f"{len(ec.qa_summary)} summarized items"
    )


@function_tool
async def extract_guidance_tool(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Extract forward guidance from prepared remarks using LLM."""
    ec = ctx.context
    if not ec.prepared_remarks:
        return "SKIP: No prepared remarks for guidance extraction"

    translator = Translator(api_key=OPENROUTER_API_KEY, model=OPENROUTER_MODEL)
    ec.guidance = await translator.extract_guidance(ec.prepared_remarks)

    nq = len(ec.guidance.get("next_quarter", []))
    fy = len(ec.guidance.get("full_year", []))
    return f"OK: Guidance — {nq} next-quarter items, {fy} full-year items"


@function_tool
async def extract_metrics_tool(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Extract quarterly financial metrics from prepared remarks using LLM."""
    ec = ctx.context
    if not ec.prepared_remarks:
        return "SKIP: No prepared remarks for metrics extraction"

    translator = Translator(api_key=OPENROUTER_API_KEY, model=OPENROUTER_MODEL)
    ec.metrics = await translator.extract_metrics_from_remarks(ec.prepared_remarks)
    return f"OK: Metrics extracted — {list(ec.metrics.keys())}"


@function_tool
async def generate_report(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Generate the final Korean-language earnings call report."""
    ec = ctx.context
    ec.final_report = format_report(
        ec.ticker, ec.year, ec.quarter,
        ec.metrics, ec.guidance, ec.qa_summary,
    )
    return ec.final_report


@function_tool
async def cleanup_browser(
    ctx: RunContextWrapper[EarningsCallContext],
) -> str:
    """Clean up Playwright browser resources."""
    ec = ctx.context
    if ec.pw and ec.browser:
        await close_browser(ec.pw, ec.browser)
        ec.pw = None
        ec.browser = None
    return "OK: Browser cleaned up"
