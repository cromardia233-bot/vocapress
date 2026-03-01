"""OpenAI Agents SDK @function_tool 정의

각 도구는 RunContextWrapper[InvestmentContext]를 통해
파이프라인 전체에서 공유되는 상태에 접근한다.
"""

import logging

from agents import function_tool, RunContextWrapper

from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from .context import InvestmentContext
from .data_sources.yfinance_fetcher import fetch_price_data
from .data_sources.edgar_fetcher import fetch_financials
from .data_sources.earnings_call import fetch_earnings_call
from .report.narrative import generate_narrative
from .report.professional import generate_professional_report, generate_final_report
from .report.critique import generate_critique
from .report.easy import generate_easy_report
from .report.charts import create_quarterly_chart, create_annual_chart
from .database import (
    save_report, save_financials, save_valuation, save_earnings_call,
)

logger = logging.getLogger(__name__)


@function_tool
async def collect_price_data(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Collect stock price and valuation data from yfinance."""
    ic = ctx.context
    ic.price_data = await fetch_price_data(ic.ticker)

    if ic.price_data.get("error"):
        ic.errors.append(f"yfinance: {ic.price_data['error']}")
        return f"ERROR: {ic.price_data['error']}"

    price = ic.price_data.get("price", "N/A")
    mcap = ic.price_data.get("market_cap", "N/A")
    return f"OK: {ic.ticker} price={price}, market_cap={mcap}"


@function_tool
async def collect_financials(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Collect financial statements from SEC EDGAR."""
    ic = ctx.context
    ic.financials = await fetch_financials(ic.ticker)

    if ic.financials.get("error"):
        ic.errors.append(f"EDGAR: {ic.financials['error']}")
        return f"WARNING: {ic.financials['error']} (continuing with available data)"

    annual_count = len(ic.financials.get("annual", []))
    quarterly_count = len(ic.financials.get("quarterly", []))
    return f"OK: {annual_count} annual + {quarterly_count} quarterly records"


@function_tool
async def collect_earnings_call(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Collect earnings call analysis (guidance, Q&A summary, metrics)."""
    ic = ctx.context
    ic.earnings_call = await fetch_earnings_call(
        ic.ticker, OPENROUTER_API_KEY, OPENROUTER_MODEL
    )

    if ic.earnings_call.get("error"):
        ic.errors.append(f"EarningsCall: {ic.earnings_call['error']}")
        return f"WARNING: {ic.earnings_call['error']} (continuing without earnings call)"

    year = ic.earnings_call.get("year", 0)
    quarter = ic.earnings_call.get("quarter", 0)
    qa_count = len(ic.earnings_call.get("qa_summary", []))
    return f"OK: FY{year} Q{quarter}, {qa_count} Q&A items"


@function_tool
async def generate_charts_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Generate quarterly and annual financial charts as PNG images."""
    ic = ctx.context
    results = []

    quarterly = ic.financials.get("quarterly", [])
    if quarterly:
        chart = await create_quarterly_chart(ic.ticker, quarterly)
        if chart:
            ic.quarterly_chart = chart
            results.append(f"quarterly({len(chart)} bytes)")

    annual = ic.financials.get("annual", [])
    if annual:
        chart = await create_annual_chart(ic.ticker, annual)
        if chart:
            ic.annual_chart = chart
            results.append(f"annual({len(chart)} bytes)")

    if results:
        return f"OK: Charts generated [{', '.join(results)}]"
    return "WARNING: No chart data available"


@function_tool
async def write_narrative_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Generate Acquired-style company narrative."""
    ic = ctx.context
    if not ic.price_data:
        return "ERROR: Price data not available yet"

    ic.company_narrative = await generate_narrative(ic.ticker, ic.price_data)
    if ic.company_narrative:
        return f"OK: Narrative generated ({len(ic.company_narrative)} chars)"
    return "WARNING: Narrative generation failed (will be omitted from final report)"


@function_tool
async def write_draft_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Generate the draft investment analysis report."""
    ic = ctx.context
    ic.draft_report = await generate_professional_report(
        ic.ticker, ic.price_data, ic.financials, ic.earnings_call
    )
    return f"OK: Draft report generated ({len(ic.draft_report)} chars)"


@function_tool
async def critique_report_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Critique the draft report from CIO perspective."""
    ic = ctx.context
    if not ic.draft_report:
        return "ERROR: Draft report not generated yet"

    ic.critique = await generate_critique(ic.draft_report)
    if ic.critique:
        return f"OK: Critique generated ({len(ic.critique)} chars)"
    return "WARNING: Critique generation failed (editor will use draft as-is)"


@function_tool
async def revise_report_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Revise draft report incorporating critique and narrative into final version."""
    ic = ctx.context
    if not ic.draft_report:
        return "ERROR: Draft report not generated yet"

    ic.professional_report = await generate_final_report(
        ic.ticker, ic.draft_report, ic.critique, ic.company_narrative
    )
    return f"OK: Final report generated ({len(ic.professional_report)} chars)"


@function_tool
async def generate_easy_report_tool(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Generate the easy-to-understand version of the report using LLM."""
    ic = ctx.context
    if not ic.professional_report:
        return "ERROR: Professional report not generated yet"

    ic.easy_report = await generate_easy_report(ic.professional_report)
    return f"OK: Easy report generated ({len(ic.easy_report)} chars)"


@function_tool
async def save_to_database(
    ctx: RunContextWrapper[InvestmentContext],
) -> str:
    """Save all analysis results to SQLite database."""
    ic = ctx.context
    saved = []

    try:
        # 리포트 저장
        if ic.professional_report:
            await save_report(ic.ticker, "professional", ic.professional_report)
            saved.append("professional_report")
        if ic.easy_report:
            await save_report(ic.ticker, "easy", ic.easy_report)
            saved.append("easy_report")

        # 밸류에이션 저장
        if ic.price_data and not ic.price_data.get("error"):
            await save_valuation(ic.ticker, ic.price_data)
            saved.append("valuation")

        # 재무제표 저장
        if ic.financials:
            annual = ic.financials.get("annual", [])
            if annual:
                await save_financials(ic.ticker, "annual", annual)
                saved.append(f"annual({len(annual)})")
            quarterly = ic.financials.get("quarterly", [])
            if quarterly:
                await save_financials(ic.ticker, "quarterly", quarterly)
                saved.append(f"quarterly({len(quarterly)})")

        # 어닝콜 저장
        if ic.earnings_call and not ic.earnings_call.get("error"):
            await save_earnings_call(
                ic.ticker,
                ic.earnings_call.get("year", 0),
                ic.earnings_call.get("quarter", 0),
                ic.earnings_call.get("guidance", {}),
                ic.earnings_call.get("qa_summary", []),
                ic.earnings_call.get("metrics", {}),
            )
            saved.append("earnings_call")

        return f"OK: Saved [{', '.join(saved)}]"

    except Exception as e:
        logger.error(f"DB 저장 실패: {e}")
        return f"ERROR: DB save failed — {e}"
