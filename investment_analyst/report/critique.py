"""리포트 비평 생성 (LLM 기반)"""

import logging

import httpx

from ..config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .prompts import CRITIQUE_SYSTEM, CRITIQUE_PROMPT

logger = logging.getLogger(__name__)


async def generate_critique(draft_report: str) -> str:
    """리포트 초안에 대한 CIO 비평을 LLM으로 생성.

    실패 시 빈 문자열 반환 (Editor가 초안을 그대로 사용).
    """
    prompt = CRITIQUE_PROMPT.replace("{draft_report}", draft_report)

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
                        {"role": "system", "content": CRITIQUE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices")
        if not choices:
            logger.error(f"비평 LLM 응답 비어 있음: {data}")
            return ""

        result = choices[0].get("message", {}).get("content", "").strip()
        if result:
            logger.info(f"리포트 비평 생성 완료 ({len(result)}자)")
        return result

    except Exception as e:
        logger.error(f"비평 생성 실패: {e}")
        return ""
