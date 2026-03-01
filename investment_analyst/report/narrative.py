"""Acquired 스타일 기업 내러티브 생성 (LLM 기반)"""

import logging

import httpx

from ..config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .prompts import NARRATIVE_SYSTEM, NARRATIVE_PROMPT

logger = logging.getLogger(__name__)


async def generate_narrative(ticker: str, price_data: dict) -> str:
    """Acquired 팟캐스트 스타일의 기업 소개를 LLM으로 생성.

    실패 시 빈 문자열 반환 (최종 리포트에서 내러티브 섹션 생략됨).
    """
    name = price_data.get("name", ticker.upper())
    sector = price_data.get("sector", "N/A")
    industry = price_data.get("industry", "N/A")
    market_cap = price_data.get("market_cap", "N/A")
    price = price_data.get("price", "N/A")
    currency = price_data.get("currency", "USD")

    prompt = NARRATIVE_PROMPT.replace("{ticker}", ticker.upper())
    prompt = prompt.replace("{name}", name)
    prompt = prompt.replace("{sector}", sector)
    prompt = prompt.replace("{industry}", industry)
    prompt = prompt.replace("{market_cap}", str(market_cap))
    prompt = prompt.replace("{price}", str(price))
    prompt = prompt.replace("{currency}", currency)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": NARRATIVE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices")
        if not choices:
            logger.error(f"내러티브 LLM 응답 비어 있음: {data}")
            return ""

        result = choices[0].get("message", {}).get("content", "").strip()
        if result:
            logger.info(f"기업 내러티브 생성 완료 ({len(result)}자)")
        return result

    except Exception as e:
        logger.error(f"내러티브 생성 실패: {e}")
        return ""
