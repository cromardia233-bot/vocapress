"""데이터 모델 정의"""

from dataclasses import dataclass, field


@dataclass
class Company:
    """밸류체인 내 기업 정보."""
    ticker: str
    name: str
    role: str  # "target", "supplier", "customer", "competitor", "partner"
    description: str = ""
    cik: str | None = None


@dataclass
class Filing:
    """SEC 공시 파일 정보."""
    ticker: str
    form_type: str  # "10-K", "10-Q"
    filed_date: str
    accession_number: str
    primary_document: str
    local_path: str | None = None


@dataclass
class Transcript:
    """어닝콜 트랜스크립트 정보."""
    ticker: str
    year: int
    quarter: int
    date_text: str = ""
    blocks: list[dict] = field(default_factory=list)
    local_path: str | None = None


@dataclass
class Presentation:
    """IR 프레젠테이션(슬라이드) 정보."""
    ticker: str
    title: str
    url: str
    local_path: str | None = None


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""
    target_ticker: str
    companies: list[Company] = field(default_factory=list)
    filings: list[Filing] = field(default_factory=list)
    transcripts: list[Transcript] = field(default_factory=list)
    presentations: list[Presentation] = field(default_factory=list)
    drive_folder_url: str | None = None
    errors: list[str] = field(default_factory=list)
