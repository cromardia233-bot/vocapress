"""OpenRouter LLM을 이용한 밸류체인 분석

주어진 티커에 대해 밸류체인 관련 기업을 분석하여
구조화된 JSON으로 반환.
"""

import json
import logging

import httpx

from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .models import Company

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a financial analyst specializing in supply chain and value chain analysis.
Given a US stock ticker, analyze its value chain and identify the most important related companies.

Rules:
- Include key suppliers, customers, competitors, and strategic partners
- Only include publicly traded US companies (with valid US stock tickers)
- Focus on the most significant relationships (aim for 5-10 companies total)
- For each company, provide a brief description of the relationship

Respond ONLY with a valid JSON array. No markdown, no explanation.
Each element must have these exact fields:
- "ticker": US stock ticker (string)
- "name": company name (string)
- "role": one of "supplier", "customer", "competitor", "partner" (string)
- "description": brief description of the relationship (string)

Example:
[{"ticker": "TSM", "name": "TSMC", "role": "supplier", "description": "Primary chip foundry manufacturing advanced GPUs"}]"""


async def analyze_valuechain(ticker: str) -> list[Company]:
    """밸류체인 분석 실행.

    Args:
        ticker: 분석 대상 미국 주식 티커

    Returns:
        관련 기업 Company 목록 (target 제외)
    """
    ticker = ticker.upper()
    user_prompt = (
        f"Analyze the value chain for {ticker}. "
        f"Identify the most important suppliers, customers, competitors, and partners. "
        f"Return ONLY a JSON array."
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    companies = _parse_companies(content, ticker)
    logger.info(f"[LLM] {ticker} 밸류체인 분석 완료: {len(companies)}개 기업")
    return companies


def _parse_companies(content: str, target_ticker: str) -> list[Company]:
    """LLM 응답에서 Company 목록 파싱.

    JSON 배열 추출 시 마크다운 코드블록도 처리.
    """
    # 마크다운 코드블록 제거
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # 첫 줄(```json)과 마지막 줄(```) 제거
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    # JSON 배열 시작/끝 추출
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        logger.error(f"[LLM] JSON 배열 파싱 실패: {content[:200]}")
        return []

    try:
        items = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        logger.error(f"[LLM] JSON 디코딩 실패: {e}")
        return []

    companies = []
    for item in items:
        t = item.get("ticker", "").upper()
        # target 자체는 제외
        if t == target_ticker.upper():
            continue
        companies.append(Company(
            ticker=t,
            name=item.get("name", ""),
            role=item.get("role", "unknown"),
            description=item.get("description", ""),
        ))

    return companies
