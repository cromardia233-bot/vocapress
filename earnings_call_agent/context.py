"""EarningsCallContext — 에이전트 파이프라인 전체에서 공유되는 상태"""

from dataclasses import dataclass, field

from playwright.async_api import Browser, Playwright


@dataclass
class EarningsCallContext:
    ticker: str = ""
    year: int = 0
    quarter: int = 0

    # 트랜스크립트 원본 블록 [{speaker_name, content}]
    raw_blocks: list[dict] = field(default_factory=list)

    # 역할 분류된 prepared remarks [{role, speaker_name, speaker_firm, content}]
    prepared_remarks: list[dict] = field(default_factory=list)

    # 역할 분류된 Q&A 블록
    qa_blocks: list[dict] = field(default_factory=list)

    # 구조화된 Q&A 쌍 [{analyst_name, analyst_firm, question, answer, ...}]
    qa_pairs: list[dict] = field(default_factory=list)

    # LLM 요약된 Q&A [{analyst_name, analyst_firm, question_topic, summary}]
    qa_summary: list[dict] = field(default_factory=list)

    # 가이던스 {next_quarter: [...], full_year: [...]}
    guidance: dict = field(default_factory=dict)

    # 재무지표 {revenue: float, eps_diluted: float, ...}
    metrics: dict = field(default_factory=dict)

    # 최종 리포트 텍스트
    final_report: str = ""

    # Playwright 인스턴스 (공유)
    pw: Playwright | None = None
    browser: Browser | None = None
