"""InvestmentContext — 에이전트 파이프라인 전체에서 공유되는 상태"""

from dataclasses import dataclass, field


@dataclass
class InvestmentContext:
    ticker: str = ""

    # yfinance 데이터: 현재가, 시가총액, PER, PBR 등
    price_data: dict = field(default_factory=dict)

    # SEC EDGAR 재무제표 (연간/분기)
    # {"annual": [{year, revenue, op_income, net_income, eps}, ...],
    #  "quarterly": [{year, quarter, end_date, revenue, ...}, ...]}
    financials: dict = field(default_factory=dict)

    # 어닝콜 분석 결과
    # {"guidance": {}, "qa_summary": [], "metrics": {}, "year": int, "quarter": int}
    earnings_call: dict = field(default_factory=dict)

    # 에이전트 토론 파이프라인 (Writer → Critic → Reporter)
    company_narrative: str = ""   # Acquired 스타일 기업 소개
    draft_report: str = ""        # Writer의 초안 (비평 전)
    critique: str = ""            # Critic의 비평

    # 생성된 리포트
    professional_report: str = ""
    easy_report: str = ""

    # 차트 이미지 (PNG bytes)
    quarterly_chart: bytes = b""
    annual_chart: bytes = b""

    # 에러 추적
    errors: list[str] = field(default_factory=list)
