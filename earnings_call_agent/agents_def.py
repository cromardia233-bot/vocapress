"""에이전트 정의 — Orchestrator → Analysis → Reporter

OpenRouter API를 OpenAIChatCompletionsModel로 연결하여
멀티 에이전트 파이프라인을 구성한다.
"""

from openai import AsyncOpenAI
from agents import Agent, handoff
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .context import EarningsCallContext
from .tools import (
    fetch_transcript,
    parse_transcript_blocks,
    analyze_qa,
    extract_guidance_tool,
    extract_metrics_tool,
    generate_report,
    cleanup_browser,
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


# ── Reporter Agent (리프 노드) ──

reporter_agent = Agent[EarningsCallContext](
    name="Reporter",
    instructions=(
        "You are the Reporter agent. Generate the final earnings call report "
        "and clean up resources.\n\n"
        "Steps:\n"
        "1. Call generate_report to create the Korean report\n"
        "2. Call cleanup_browser to release browser resources\n"
        "3. Return the generated report text as your final response"
    ),
    tools=[generate_report, cleanup_browser],
    model=_model,
)


# ── Analysis Agent (중간 노드) ──

analysis_agent = Agent[EarningsCallContext](
    name="Analysis",
    instructions=(
        "You are the Analysis agent. Analyze the parsed earnings call data.\n\n"
        "Steps:\n"
        "1. Call analyze_qa to organize and summarize Q&A pairs\n"
        "2. Call extract_guidance_tool to extract forward guidance\n"
        "3. Call extract_metrics_tool to extract financial metrics\n"
        "4. After all three tools complete, hand off to the Reporter agent\n\n"
        "Call all three tools before handing off."
    ),
    tools=[analyze_qa, extract_guidance_tool, extract_metrics_tool],
    handoffs=[handoff(reporter_agent)],
    model=_model,
)


# ── Orchestrator Agent (엔트리 포인트) ──

orchestrator_agent = Agent[EarningsCallContext](
    name="Orchestrator",
    instructions=(
        "You are the Orchestrator agent. Fetch and parse the earnings call "
        "transcript.\n\n"
        "Steps:\n"
        "1. Call fetch_transcript to scrape the latest transcript\n"
        "2. If fetch_transcript returns an ERROR, report the error and stop\n"
        "3. Call parse_transcript_blocks to classify speakers and split sections\n"
        "4. After both tools succeed, hand off to the Analysis agent"
    ),
    tools=[fetch_transcript, parse_transcript_blocks],
    handoffs=[handoff(analysis_agent)],
    model=_model,
)
