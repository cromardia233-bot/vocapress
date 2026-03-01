"""OpenRouter API를 통한 Q&A 요약 정리"""

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a financial earnings call analyst. Summarize each Q&A pair into concise Korean bullet points.

Rules:
- For each Q&A pair, output 2-4 bullet points capturing the KEY details only
- Write in Korean, but keep English for: company/product names (Blackwell, Rubin, CUDA), ticker symbols, proper nouns
- Use "·" as bullet marker
- Be concise — no filler words, no repetition
- Do NOT include speaker names like (Jensen), (Colette) in bullet points — just state the content directly

Number & unit formatting (MUST follow strictly):
- Dollar amounts: use $B for billions, $M for millions (e.g., $57B, $500M). Never write "570억 달러" — always "$57B"
- Growth rates: use YoY for year-over-year, QoQ for quarter-over-quarter (e.g., YoY +62%, QoQ +22%)
- Margins: use GPM, OPM, NPM abbreviations (e.g., GPM 73.5%)
- Percentages: keep as-is with +/- sign (e.g., +62%, -3.2%)
- EPS: $0.89 format

Preserve the exact format below for each QA pair:

=== QA n ===
[Firm - Analyst Name]
Q) 질문 주제를 한 줄로 요약 (10-20자)
· 핵심 포인트 1
· 핵심 포인트 2
· 핵심 포인트 3

The Q) line MUST be a very short topic summary of the analyst's question — like a headline.

Example output:
=== QA 1 ===
[Morgan Stanley - Joseph Moore]
Q) Blackwell 수요 궤적 및 공급 정상화 시점?
· Blackwell+Rubin 합산 $500B 매출 목표 순항 중, 이번 분기 GPU 100만 대+ 출하
· 수요가 공급을 크게 초과, CSP 인프라 YoY +62% 확장 지속"""


_GUIDANCE_PROMPT = """You are a financial earnings call analyst. Extract the company's forward guidance from the prepared remarks.

Rules:
- Extract explicitly stated guidance/outlook numbers
- Separate into two sections: [NEXT QUARTER] and [FULL YEAR]
- Output in the exact format below — one line per metric under each section header
- If a range is given, use "~" (e.g., $37.5B~$38.5B)
- If ± tolerance is given, use "±" (e.g., $37.5B ±2%)
- Dollar amounts: $B for billions, $M for millions
- If a metric is not mentioned, do NOT include it
- Omit a section header entirely if no guidance exists for that period
- If no guidance is found at all, output exactly: NO_GUIDANCE

Available metrics (include only if explicitly stated):
Revenue: <amount>
GPM: <percentage>
OPEX: <amount>
Tax Rate: <percentage>
EPS: <amount>
CAPEX: <amount>
Other: <any other notable guidance item>

Example output:
[NEXT QUARTER]
Revenue: $37.5B ±2%
GPM: 73.0% ±50bps

[FULL YEAR]
Revenue: $130B~$135B
CAPEX: $12B~$14B"""


_METRICS_PROMPT = """You are a financial analyst. Extract key QUARTERLY financial metrics from this earnings call transcript.

Rules:
- Extract ONLY the QUARTERLY (single quarter) numbers — NOT full-year/annual/cumulative figures
- Earnings calls often mention both quarterly AND annual results. You MUST pick the QUARTERLY figures only.
  e.g. "Q4 revenue of $1.4 billion" and "full-year revenue of $5.3 billion" → extract 1400000000
  e.g. "EPS of $1.24 for the quarter" and "$7.14 for the full year" → extract 1.24
- Output raw numeric values in USD (not billions/millions abbreviations)
- Use the EXACT format below — one line per metric
- If a metric is not mentioned, do NOT include it
- For revenue/profit/income: output in raw dollars (e.g., 1400000000 for $1.4B)
- For EPS: output the dollar amount (e.g., 1.24)
- For margins (GPM, OPM, NPM): output percentage number (e.g., 73.5)
- If no quarterly financial data found, output exactly: NO_DATA

Available metrics:
revenue: <raw USD amount>
gross_profit: <raw USD amount>
op_income: <raw USD amount>
net_income: <raw USD amount>
eps_diluted: <dollar amount>
gpm: <percentage>
opm: <percentage>
npm: <percentage>

Example output:
revenue: 1400000000
net_income: 340000000
eps_diluted: 1.24
gpm: 73.5"""


_CONFERENCE_PROMPT = """You are a financial analyst. Summarize this conference/keynote/fireside chat transcript.

Rules:
- Output 5-10 bullet points in Korean
- Focus on: new product announcements, strategy updates, partnerships, market outlook, competitive positioning
- Keep English for: company/product names (Blackwell, Rubin, CUDA), ticker symbols, proper nouns
- Use "·" as bullet marker
- Dollar amounts: $B for billions, $M for millions. Never write "570억 달러" — always "$57B"
- Growth rates: YoY, QoQ with +/- sign
- Be concise — each bullet should be 1-2 sentences max
- Do NOT include speaker names — just state the content directly
"""


class Translator:
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash",
                 base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def _call_llm(self, text: str, system_prompt: str | None = None) -> str:
        """OpenRouter API 호출."""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt or _SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def extract_guidance(self, prepared_remarks: list[dict]) -> dict:
        """Prepared remarks에서 가이던스 추출.

        Returns:
            {"next_quarter": ["Revenue: $37.5B ±2%", ...],
             "full_year": ["Revenue: $130B~$135B", ...]}
        """
        text = "\n\n".join(
            f"{b.get('speaker_name', '')}: {b.get('content', '')}"
            for b in prepared_remarks if b.get("content", "").strip()
        )
        if not text:
            return {"next_quarter": [], "full_year": []}

        result = await self._call_llm(text, system_prompt=_GUIDANCE_PROMPT)
        if "NO_GUIDANCE" in result:
            return {"next_quarter": [], "full_year": []}

        return _parse_guidance_sections(result)

    async def extract_metrics_from_remarks(self, prepared_remarks: list[dict]) -> dict[str, float]:
        """EDGAR 데이터 없을 때 prepared remarks에서 재무 지표 추출 (fallback).

        Returns:
            {"revenue": 35200000000.0, "eps_diluted": 0.89, ...}
        """
        text = "\n\n".join(
            f"{b.get('speaker_name', '')}: {b.get('content', '')}"
            for b in prepared_remarks if b.get("content", "").strip()
        )
        if not text:
            return {}

        if len(text) > 30000:
            text = text[:30000]

        result = await self._call_llm(text, system_prompt=_METRICS_PROMPT)
        if "NO_DATA" in result:
            return {}

        metrics = {}
        for line in result.split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key in ("revenue", "gross_profit", "op_income", "net_income",
                       "eps_diluted", "gpm", "opm", "npm"):
                try:
                    metrics[key] = float(val.replace(",", ""))
                except ValueError:
                    continue
        return metrics

    async def summarize_conference(self, blocks: list[dict]) -> str:
        """컨퍼런스/키노트 트랜스크립트를 한국어 bullet points로 요약.

        Args:
            blocks: [{speaker_name, content}, ...]

        Returns:
            "· 포인트 1\n· 포인트 2\n..." 형식의 요약 문자열
        """
        text = "\n\n".join(
            f"{b.get('speaker_name', '')}: {b.get('content', '')}"
            for b in blocks if b.get("content", "").strip()
        )
        if not text:
            return ""

        # 너무 길면 앞부분만 사용 (토큰 제한)
        if len(text) > 50000:
            text = text[:50000] + "\n\n[... 이후 생략 ...]"

        result = await self._call_llm(text, system_prompt=_CONFERENCE_PROMPT)
        return result.strip()

    async def summarize_qa_pairs(self, qa_pairs: list[dict]) -> list[dict]:
        """Q&A 쌍을 한국어 요약 bullet points로 변환."""
        if not qa_pairs:
            return qa_pairs

        combined = _combine_qa(qa_pairs)

        # 전체를 한 번에 보내되, 너무 길면 분할
        chunks = _split_into_chunks(combined, max_chars=15000)

        summarized_chunks = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Q&A 요약 중... ({i+1}/{len(chunks)}, {len(chunk)} chars)")
            result = await self._call_llm(chunk)
            summarized_chunks.append(result)
            if i < len(chunks) - 1:
                await asyncio.sleep(1)

        full_result = "\n\n".join(summarized_chunks)
        return _parse_summarized_qa(full_result, qa_pairs)


def _parse_guidance_sections(text: str) -> dict:
    """LLM 응답을 [NEXT QUARTER] / [FULL YEAR] 섹션으로 파싱."""
    next_q = []
    full_y = []
    current = next_q  # 섹션 헤더 없으면 next_quarter로 간주

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if "[NEXT QUARTER]" in upper or "NEXT QUARTER" in upper:
            current = next_q
            continue
        if "[FULL YEAR]" in upper or "FULL YEAR" in upper:
            current = full_y
            continue
        if ":" in line and not line.startswith("["):
            current.append(line)

    return {"next_quarter": next_q, "full_year": full_y}


def _combine_qa(qa_pairs: list[dict]) -> str:
    """Q&A 쌍을 LLM 입력용 텍스트로 합침."""
    parts = []
    for i, pair in enumerate(qa_pairs):
        firm = pair.get("analyst_firm", "")
        name = pair.get("analyst_name", "")
        header = f"[{firm} - {name}]" if firm else f"[{name}]"
        q = pair.get("question", "")
        a = pair.get("answer", "")
        parts.append(f"=== QA {i+1} ===\n{header}\nQ: {q}\n\nA: {a}")
    return "\n\n".join(parts)


def _split_into_chunks(text: str, max_chars: int = 15000) -> list[str]:
    """=== QA n === 경계에서 분할."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    sections = text.split("=== QA ")
    current = ""

    for section in sections:
        if not section.strip():
            continue
        piece = f"=== QA {section}"
        if len(current) + len(piece) > max_chars and current:
            chunks.append(current.strip())
            current = piece
        else:
            current += ("\n\n" if current else "") + piece

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]


def _parse_summarized_qa(summarized: str, original_pairs: list[dict]) -> list[dict]:
    """요약된 텍스트를 Q&A 쌍 구조로 재구성.

    출력 포맷이 bullet point이므로 question/answer 대신
    question에 요약 bullet을 넣고 answer는 비움.
    """
    sections = re.split(r"===\s*QA\s*\d+\s*===", summarized)
    sections = [s.strip() for s in sections if s.strip()]

    result = []
    for i, pair in enumerate(original_pairs):
        new_pair = {
            "analyst_name": pair.get("analyst_name", ""),
            "analyst_firm": pair.get("analyst_firm", ""),
        }

        if i < len(sections):
            section = sections[i]
            lines = section.split("\n")
            question_topic = ""
            bullets = []
            for line in lines:
                line = line.strip()
                if line.upper().startswith("Q)") or line.upper().startswith("Q）"):
                    question_topic = line[2:].strip().lstrip(")").strip()
                elif line.startswith("·") or line.startswith("-") or line.startswith("•"):
                    bullets.append(line)
                elif line.startswith("["):
                    continue  # 헤더 스킵
                elif line:
                    bullets.append(f"· {line}")

            if question_topic:
                new_pair["question_topic"] = question_topic
            new_pair["summary"] = "\n".join(bullets) if bullets else section
        else:
            # 요약 실패 시 원본 질문 사용
            new_pair["summary"] = pair.get("question", "")

        result.append(new_pair)

    return result
