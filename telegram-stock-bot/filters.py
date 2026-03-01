import json
import logging
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger(__name__)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

CHUNK_SIZE = 30


def keyword_filter(message_text: str, keywords: list[str]) -> list[str]:
    """메시지에 포함된 키워드 목록 반환. 없으면 빈 리스트."""
    if not message_text:
        return []
    text_lower = message_text.lower()
    matched = []
    for kw in keywords:
        if kw.lower() in text_lower:
            matched.append(kw)
    return matched


async def llm_summarize(messages: list[dict], stock_map: dict[str, str] | None = None) -> str:
    """
    키워드 매칭된 메시지들을 LLM으로 종목별 분류 요약.
    대량 메시지는 CHUNK_SIZE 단위로 분할하여 처리 후 최종 통합 요약.

    입력 messages 형식:
        [{"channel": str, "text": str, "matched_keywords": list[str], "date": str}]
    stock_map: {"종목명": "키워드1,키워드2,..."}

    반환: HTML 포맷 요약 텍스트
    """
    if not messages:
        return "요약할 메시지가 없습니다."

    stock_map = stock_map or {}

    # 청크 분할
    chunks = [messages[i:i + CHUNK_SIZE] for i in range(0, len(messages), CHUNK_SIZE)]
    logger.info("LLM 요약: 총 %d건, %d개 청크로 분할", len(messages), len(chunks))

    chunk_summaries = []
    for idx, chunk in enumerate(chunks):
        logger.info("청크 %d/%d 처리 중 (%d건)", idx + 1, len(chunks), len(chunk))
        summary = await _summarize_chunk(chunk, stock_map)
        chunk_summaries.append(summary)

    # 청크가 1개면 바로 반환
    if len(chunk_summaries) == 1:
        return chunk_summaries[0]

    # 여러 청크의 결과를 최종 통합
    return await _merge_summaries(chunk_summaries, stock_map)


async def _summarize_chunk(messages: list[dict], stock_map: dict[str, str]) -> str:
    """단일 청크의 메시지를 LLM으로 종목별 분류 요약."""
    # 종목명 → 키워드 목록 표시
    stock_list_text = "\n".join(
        f"  - {name}: {kws}" for name, kws in stock_map.items()
    )

    messages_text = ""
    for i, msg in enumerate(messages, 1):
        link = msg.get("link", "")
        messages_text += (
            f"[{i}] 채널: {msg['channel']}\n"
            f"    시간: {msg['date']}\n"
            f"    링크: {link}\n"
            f"    매칭 키워드: {', '.join(msg['matched_keywords'])}\n"
            f"    내용: {msg['text'][:1000]}\n\n"
        )

    prompt = f"""당신은 주식 투자 정보 요약 전문가입니다.

관심 종목 목록 (종목명: 관련 키워드):
{stock_list_text}

아래는 지난 24시간 동안 텔레그램 채널에서 수집된 메시지들입니다.
종목별로 분류된 상세한 일일 요약 리포트를 작성해주세요.

출력 양식 (이 형식을 정확히 따라주세요):

📌 <b>종목명</b> 🟢 긍정 / 🔴 부정 / 🟡 중립

▸ <b>소제목 (뉴스/이슈 요약)</b>
상세 내용을 3~5문장으로 충분히 설명해주세요. 구체적인 수치, 배경, 맥락, 시장 영향 등을 포함해주세요.
📡 <a href="원본링크">@채널명</a>

규칙:
1. 매칭 키워드 기반으로 종목을 분류하세요
2. 종목명 옆에 해당 종목의 오늘 뉴스 종합 방향성을 🟢(긍정) / 🔴(부정) / 🟡(중립·혼재) 중 하나로 표시하세요
3. 각 포인트는 소제목 + 상세 설명(3~5문장) 구조로 작성하세요
4. 원본 메시지의 핵심 정보(수치, 날짜, 인물, 구체적 사실)를 최대한 포함하세요
5. 각 포인트 마지막에 반드시 📡 <a href="링크">@채널명</a> 형태로 출처를 표시하세요 (채널명은 메시지 데이터의 채널 필드를 사용)
6. 중복 내용은 합치되, 정보량은 유지하세요. 잡담/광고만 제외하세요
7. 종목 간 구분은 빈 줄로 하세요
8. HTML 태그만 사용하세요 (<b>, <i>, <a href>)
9. 마크다운 문법(**, ## 등)은 절대 사용하지 마세요
10. ```html, ``` 같은 코드블록 표시도 절대 포함하지 마세요. 순수 텍스트+HTML 태그만 출력하세요

메시지 목록:
{messages_text}

위 양식대로 HTML 포맷 리포트를 작성해주세요."""

    response = await openai_client.chat.completions.create(
        model="google/gemini-3-flash-preview",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return _strip_codeblock(response.choices[0].message.content or "(요약 결과 없음)")


def _strip_codeblock(text: str) -> str:
    """LLM 응답에서 ```html ... ``` 코드블록 감싸기를 제거."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def _merge_summaries(summaries: list[str], stock_map: dict[str, str]) -> str:
    """여러 청크 요약을 하나의 최종 요약으로 통합."""
    stock_names = ", ".join(stock_map.keys())
    combined = "\n\n---\n\n".join(
        f"[파트 {i+1}]\n{s}" for i, s in enumerate(summaries)
    )

    prompt = f"""아래는 여러 파트로 나뉘어 요약된 주식 투자 정보입니다.
하나의 통합된 리포트로 재구성해주세요.

관심 종목: {stock_names}

출력 양식:

📌 <b>종목명</b> 🟢/🔴/🟡

▸ <b>소제목</b>
상세 설명 3~5문장
📡 <a href="원본링크">@채널명</a>

규칙:
1. 종목별 섹션으로 분류, 중복 합치기
2. 종목명 옆에 뉴스 종합 방향성 🟢(긍정) / 🔴(부정) / 🟡(중립·혼재) 표시
3. 각 포인트는 소제목 + 상세 설명(3~5문장) 유지
4. 출처는 📡 <a href="링크">@채널명</a> 형태를 반드시 유지
5. HTML 태그만 사용 (<b>, <i>, <a href>)
6. 마크다운 문법(**, ## 등)은 절대 사용하지 마세요
7. ```html, ``` 같은 코드블록 표시도 절대 포함하지 마세요. 순수 텍스트+HTML 태그만 출력하세요

파트별 요약:
{combined}

위 양식대로 통합 리포트를 작성해주세요."""

    response = await openai_client.chat.completions.create(
        model="google/gemini-3-flash-preview",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return _strip_codeblock(response.choices[0].message.content or "(통합 요약 결과 없음)")
