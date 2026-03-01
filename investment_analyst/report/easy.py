"""쉬운 리포트 생성 — LLM으로 전문 리포트를 초보자용으로 변환"""

import logging

import httpx

from ..config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .prompts import EASY_REPORT_PROMPT

logger = logging.getLogger(__name__)


async def generate_easy_report(professional_report: str) -> str:
    """전문 리포트를 LLM으로 쉬운 버전으로 변환.

    Args:
        professional_report: 전문 리포트 텍스트

    Returns:
        초보자용 쉬운 리포트 텍스트
    """
    if not professional_report:
        return "분석 리포트가 없어 쉬운 버전을 생성할 수 없습니다."

    prompt = EASY_REPORT_PROMPT.replace("{report}", professional_report)

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
                        {
                            "role": "system",
                            "content": "당신은 투자 초보자를 위한 친절한 주식 분석 전문가입니다. 한국어로 작성합니다.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.5,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices")
        if not choices:
            logger.error(f"LLM 응답에 choices가 비어 있음: {data}")
            return "쉬운 리포트 생성 실패: LLM이 빈 응답을 반환했습니다."

        result = choices[0].get("message", {}).get("content", "").strip()
        if not result:
            return "쉬운 리포트 생성 실패: LLM 응답에 내용이 없습니다."

        logger.info(f"쉬운 리포트 생성 완료 ({len(result)}자)")
        return result

    except Exception as e:
        logger.error(f"쉬운 리포트 생성 실패: {e}")
        return f"쉬운 리포트 생성 실패: {e}"
