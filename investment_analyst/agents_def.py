"""에이전트 정의 — Orchestrator → DataCollector → Analysis → Writer → Critic → Reporter

OpenRouter API를 OpenAIChatCompletionsModel로 연결하여
6단계 멀티 에이전트 파이프라인을 구성한다.
Writer → Critic → Reporter 토론 구조로 리포트 품질 향상.
"""

from openai import AsyncOpenAI
from agents import Agent, handoff
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .context import InvestmentContext
from .tools import (
    collect_price_data,
    collect_financials,
    collect_earnings_call,
    write_narrative_tool,
    write_draft_tool,
    critique_report_tool,
    revise_report_tool,
    generate_charts_tool,
    generate_easy_report_tool,
    save_to_database,
)

# ── OpenRouter 클라이언트 ──

_client = AsyncOpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY or "sk-placeholder",
)

_model = OpenAIChatCompletionsModel(
    model=OPENROUTER_MODEL,
    openai_client=_client,
)


# ── Reporter Agent (Editor — 최종 수정 + 차트 + 쉬운버전 + DB저장) ──

reporter_agent = Agent[InvestmentContext](
    name="Reporter",
    instructions=(
        "You are the Reporter (Editor) agent. "
        "Revise the draft using the critique, generate charts and easy report, "
        "then save everything to the database.\n\n"
        "Steps:\n"
        "1. Call revise_report_tool to create the final report "
        "(incorporating narrative + critique into the draft)\n"
        "2. Call generate_charts_tool to create quarterly/annual chart images\n"
        "3. Call generate_easy_report_tool to create the easy version\n"
        "4. Call save_to_database to persist all data\n"
        "5. Return a brief confirmation as your final response"
    ),
    tools=[
        revise_report_tool,
        generate_charts_tool,
        generate_easy_report_tool,
        save_to_database,
    ],
    model=_model,
)


# ── Critic Agent (비평) ──

critic_agent = Agent[InvestmentContext](
    name="Critic",
    instructions=(
        "You are the Critic agent — a senior CIO at a global hedge fund.\n"
        "Your job: critique the draft report for logical gaps and biases.\n\n"
        "Steps:\n"
        "1. Call critique_report_tool to generate the critique\n"
        "2. IMMEDIATELY transfer to the Reporter agent using the transfer_to_reporter handoff. "
        "Do NOT produce any text response — you MUST hand off."
    ),
    tools=[critique_report_tool],
    handoffs=[handoff(reporter_agent)],
    model=_model,
)


# ── Writer Agent (내러티브 + 초안 작성) ──

writer_agent = Agent[InvestmentContext](
    name="Writer",
    instructions=(
        "You are the Writer agent. Generate the company narrative and draft report.\n\n"
        "Steps:\n"
        "1. Call write_narrative_tool to create the Acquired-style company narrative\n"
        "2. Call write_draft_tool to create the draft investment analysis report\n"
        "3. IMMEDIATELY transfer to the Critic agent using the transfer_to_critic handoff. "
        "Do NOT produce any text response — you MUST hand off."
    ),
    tools=[write_narrative_tool, write_draft_tool],
    handoffs=[handoff(critic_agent)],
    model=_model,
)


# ── Analysis Agent (어닝콜 분석) ──

analysis_agent = Agent[InvestmentContext](
    name="Analysis",
    instructions=(
        "You are the Analysis agent. Collect earnings call data.\n\n"
        "Steps:\n"
        "1. Call collect_earnings_call to get guidance, Q&A summary, and metrics\n"
        "   - If it returns a WARNING (no transcript), that's OK — continue anyway\n"
        "2. IMMEDIATELY transfer to the Writer agent using the transfer_to_writer handoff. "
        "Do NOT produce any text response — you MUST hand off."
    ),
    tools=[collect_earnings_call],
    handoffs=[handoff(writer_agent)],
    model=_model,
)


# ── DataCollector Agent (데이터 수집) ──

data_collector_agent = Agent[InvestmentContext](
    name="DataCollector",
    instructions=(
        "You are the DataCollector agent. Gather financial data from multiple sources.\n\n"
        "Steps:\n"
        "1. Call collect_price_data to get stock price and valuation from yfinance\n"
        "2. Call collect_financials to get financial statements from SEC EDGAR\n"
        "   - If EDGAR returns a WARNING, that's OK — continue with available data\n"
        "3. IMMEDIATELY transfer to the Analysis agent using the transfer_to_analysis handoff. "
        "Do NOT produce any text response — you MUST hand off."
    ),
    tools=[collect_price_data, collect_financials],
    handoffs=[handoff(analysis_agent)],
    model=_model,
)


# ── Orchestrator Agent (엔트리 포인트) ──

orchestrator_agent = Agent[InvestmentContext](
    name="Orchestrator",
    instructions=(
        "You are the Orchestrator agent for investment analysis.\n"
        "The user will provide a stock ticker.\n\n"
        "Your only job: immediately hand off to the DataCollector agent.\n"
        "Do not call any tools — just hand off."
    ),
    handoffs=[handoff(data_collector_agent)],
    model=_model,
)
