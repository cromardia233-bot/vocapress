"""전문 투자분석 리포트 생성 (LLM 기반)

수집된 데이터를 구조화된 컨텍스트로 변환 → LLM이 애널리스트 스타일 리포트 생성
"""

import logging
import sys
from pathlib import Path

import httpx

# format_helpers 재사용
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from earnings_call_agent.format_helpers import fmt_dollar, fmt_pct, fmt_eps

from ..config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from .prompts import (
    PROFESSIONAL_REPORT_SYSTEM, PROFESSIONAL_REPORT_PROMPT,
    FINAL_REPORT_SYSTEM, FINAL_REPORT_PROMPT,
)

logger = logging.getLogger(__name__)


# ── 데이터 컨텍스트 빌더 ──

def _fmt_val(value, formatter=fmt_dollar) -> str:
    if value is None:
        return "N/A"
    return formatter(value)


def _fmt_ratio(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}x"


def _calc_yoy(current, previous) -> str:
    if current is None or previous is None or previous == 0:
        return "N/A"
    growth = (current - previous) / abs(previous) * 100
    return fmt_pct(growth, sign=True)


def _build_data_context(ticker: str, price_data: dict,
                        financials: dict, earnings_call: dict) -> str:
    """수집된 데이터를 LLM 컨텍스트 문자열로 변환."""
    parts: list[str] = []
    name = price_data.get("name", ticker.upper())

    parts.append(f"종목: {ticker.upper()} ({name})")

    # 주가 데이터
    parts.append("\n=== 주가 데이터 ===")
    price = price_data.get("price")
    currency = price_data.get("currency", "USD")
    parts.append(f"현재가: {_fmt_val(price, fmt_eps)} {currency}")
    parts.append(f"시가총액: {_fmt_val(price_data.get('market_cap'))}")
    w52h = price_data.get("week52_high")
    w52l = price_data.get("week52_low")
    if w52h and w52l:
        parts.append(f"52주 범위: {fmt_eps(w52l)} ~ {fmt_eps(w52h)}")
        if price and w52h:
            pct = (price - w52h) / w52h * 100
            parts.append(f"52주 고점 대비: {fmt_pct(pct, sign=True)}")
    parts.append(f"섹터: {price_data.get('sector', 'N/A')}")
    parts.append(f"산업: {price_data.get('industry', 'N/A')}")

    # 밸류에이션
    parts.append("\n=== 밸류에이션 ===")
    parts.append(f"PER (Trailing): {_fmt_ratio(price_data.get('per'))}")
    parts.append(f"PER (Forward): {_fmt_ratio(price_data.get('forward_per'))}")
    parts.append(f"PBR: {_fmt_ratio(price_data.get('pbr'))}")
    parts.append(f"PSR: {_fmt_ratio(price_data.get('psr'))}")
    parts.append(f"EV/EBITDA: {_fmt_ratio(price_data.get('ev_ebitda'))}")
    if price_data.get("dividend_yield") is not None:
        dy = price_data["dividend_yield"] * 100
        parts.append(f"배당수익률: {fmt_pct(dy, sign=False)}")
    if price_data.get("beta") is not None:
        parts.append(f"베타: {price_data['beta']:.2f}")

    # 분기 재무제표
    quarterly = financials.get("quarterly", [])
    if quarterly:
        parts.append("\n=== 분기 재무제표 (최근 4분기) ===")
        for q in quarterly[:4]:
            fy = q.get("fiscal_year", "")
            fq = q.get("fiscal_quarter", "")
            line = f"FY{fy} Q{fq}: "
            items = []
            if q.get("revenue") is not None:
                items.append(f"Revenue {fmt_dollar(q['revenue'])}")
            if q.get("op_income") is not None:
                items.append(f"Op Income {fmt_dollar(q['op_income'])}")
            if q.get("net_income") is not None:
                items.append(f"Net Income {fmt_dollar(q['net_income'])}")
            if q.get("eps") is not None:
                items.append(f"EPS {fmt_eps(q['eps'])}")
            parts.append(line + " | ".join(items))

        # YoY
        if len(quarterly) >= 5:
            curr, prev = quarterly[0], quarterly[4]
            yoy_items = []
            if curr.get("revenue") and prev.get("revenue"):
                yoy_items.append(f"Revenue YoY: {_calc_yoy(curr['revenue'], prev['revenue'])}")
            if curr.get("net_income") and prev.get("net_income"):
                yoy_items.append(f"Net Income YoY: {_calc_yoy(curr['net_income'], prev['net_income'])}")
            if yoy_items:
                parts.append(f"최신 분기 YoY: {' | '.join(yoy_items)}")

    # 연간 재무제표
    annual = financials.get("annual", [])
    if annual:
        parts.append("\n=== 연간 재무제표 (최근 3년) ===")
        for a in annual[:3]:
            fy = a.get("fiscal_year", "")
            line = f"FY{fy}: "
            items = []
            if a.get("revenue") is not None:
                items.append(f"Revenue {fmt_dollar(a['revenue'])}")
            if a.get("op_income") is not None:
                items.append(f"Op Income {fmt_dollar(a['op_income'])}")
            if a.get("net_income") is not None:
                items.append(f"Net Income {fmt_dollar(a['net_income'])}")
            if a.get("eps") is not None:
                items.append(f"EPS {fmt_eps(a['eps'])}")
            parts.append(line + " | ".join(items))

        if len(annual) >= 2:
            curr, prev = annual[0], annual[1]
            yoy_items = []
            if curr.get("revenue") and prev.get("revenue"):
                yoy_items.append(f"Revenue YoY: {_calc_yoy(curr['revenue'], prev['revenue'])}")
            if curr.get("net_income") and prev.get("net_income"):
                yoy_items.append(f"Net Income YoY: {_calc_yoy(curr['net_income'], prev['net_income'])}")
            if yoy_items:
                parts.append(f"최신 연도 YoY: {' | '.join(yoy_items)}")

    # 어닝콜
    if earnings_call and not earnings_call.get("error"):
        ec_year = earnings_call.get("year", 0)
        ec_quarter = earnings_call.get("quarter", 0)
        parts.append(f"\n=== 어닝콜 — FY{ec_year} Q{ec_quarter} ===")

        guidance = earnings_call.get("guidance", {})
        if guidance:
            if guidance.get("next_quarter"):
                parts.append("[다음 분기 가이던스]")
                for item in guidance["next_quarter"]:
                    parts.append(f"  - {item}")
            if guidance.get("full_year"):
                parts.append("[연간 가이던스]")
                for item in guidance["full_year"]:
                    parts.append(f"  - {item}")

        qa_summary = earnings_call.get("qa_summary", [])
        if qa_summary:
            parts.append(f"[Q&A 요약 — {len(qa_summary)}개 토픽]")
            for i, qa in enumerate(qa_summary, 1):
                firm = qa.get("analyst_firm", "")
                topic = qa.get("question_topic", "")
                summary = qa.get("summary", "")
                header = f"{firm}" if firm else "Unknown"
                parts.append(f"  {i}. [{header}] {topic}")
                if summary:
                    # 요약을 2줄 이내로 압축
                    lines = summary.strip().split("\n")
                    for line in lines[:3]:
                        parts.append(f"     {line.strip()}")

        metrics = earnings_call.get("metrics", {})
        if metrics:
            parts.append("[주요 경영지표]")
            for k, v in metrics.items():
                parts.append(f"  - {k}: {v}")

    return "\n".join(parts)


# ── LLM 기반 리포트 생성 ──

async def generate_professional_report(
    ticker: str, price_data: dict,
    financials: dict, earnings_call: dict,
) -> str:
    """LLM을 활용한 전문 투자분석 리포트 생성.

    수집된 데이터를 컨텍스트로 구성 → LLM이 애널리스트 스타일로 작성.
    LLM 호출 실패 시 데이터 요약 폴백 반환.
    """
    name = price_data.get("name", ticker.upper())
    data_context = _build_data_context(ticker, price_data, financials, earnings_call)

    # 모든 치환을 replace로 통일 (data_context에 중괄호가 있어도 안전)
    prompt = PROFESSIONAL_REPORT_PROMPT.replace("{data_context}", data_context)
    prompt = prompt.replace("{{ticker}}", ticker.upper())
    prompt = prompt.replace("{{name}}", name)

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": PROFESSIONAL_REPORT_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 4096,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices")
        if not choices:
            logger.error(f"LLM 응답 비어 있음: {data}")
            return _fallback_report(ticker, data_context)

        result = choices[0].get("message", {}).get("content", "").strip()
        if not result:
            return _fallback_report(ticker, data_context)

        logger.info(f"전문 리포트 생성 완료 ({len(result)}자)")
        return result

    except Exception as e:
        logger.error(f"전문 리포트 LLM 호출 실패: {e}")
        return _fallback_report(ticker, data_context)


def _fallback_report(ticker: str, data_context: str) -> str:
    """LLM 실패 시 데이터 요약 폴백."""
    return (
        f"━━ {ticker.upper()} 투자분석 리포트 ━━\n\n"
        f"⚠️ LLM 리포트 생성에 실패하여 수집된 데이터를 표시합니다.\n\n"
        f"{data_context}\n\n"
        f"📊 분기/연간 상세 수치는 차트 이미지를 참조하세요."
    )


# ── 비평 반영 최종 리포트 생성 ──

async def generate_final_report(
    ticker: str,
    draft_report: str,
    critique: str,
    narrative: str,
) -> str:
    """Writer 초안 + Critic 비평 + 내러티브를 종합한 최종 리포트 생성.

    비평이 비어있으면 초안을 그대로 반환.
    """
    # 비평이 없으면 내러티브만 붙여서 반환
    if not critique:
        if narrative:
            return f"{narrative}\n\n{draft_report}"
        return draft_report

    name = ticker.upper()
    prompt = FINAL_REPORT_PROMPT.replace("{narrative}", narrative or "(내러티브 없음)")
    prompt = prompt.replace("{draft_report}", draft_report)
    prompt = prompt.replace("{critique}", critique)
    prompt = prompt.replace("{{ticker}}", name)

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": FINAL_REPORT_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 5000,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices")
        if not choices:
            logger.error(f"최종 리포트 LLM 응답 비어 있음: {data}")
            # 폴백: 내러티브 + 초안
            if narrative:
                return f"{narrative}\n\n{draft_report}"
            return draft_report

        result = choices[0].get("message", {}).get("content", "").strip()
        if not result:
            if narrative:
                return f"{narrative}\n\n{draft_report}"
            return draft_report

        logger.info(f"최종 리포트 생성 완료 ({len(result)}자)")
        return result

    except Exception as e:
        logger.error(f"최종 리포트 LLM 호출 실패: {e}")
        if narrative:
            return f"{narrative}\n\n{draft_report}"
        return draft_report
