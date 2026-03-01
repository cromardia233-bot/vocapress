"""SEC EDGAR Company Facts API를 통한 재무제표 수집

1회 API 호출로 전체 XBRL 데이터를 가져온 뒤,
연간 3년 + 분기 8개 재무제표를 추출한다.
분기 단독 수치는 누적값 차감으로 계산.
"""

import logging
from collections import defaultdict

import httpx

from ..config import SEC_USER_AGENT

logger = logging.getLogger(__name__)

_EDGAR_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

# Revenue XBRL 태그 (우선순위 순서: ASC 606 → 일반 → 구식)
_REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]

# 기타 XBRL 태그 → 내부 키 매핑
_OTHER_TAGS = {
    "GrossProfit": "gross_profit",
    "OperatingIncomeLoss": "op_income",
    "NetIncomeLoss": "net_income",
    "EarningsPerShareDiluted": "eps",
}


_CIK_CACHE: dict[str, str] = {}
_TICKERS_DATA: dict | None = None


async def _get_cik(ticker: str) -> str | None:
    """티커 → CIK 번호 변환 (캐싱 적용)."""
    global _TICKERS_DATA

    ticker_upper = ticker.upper()
    if ticker_upper in _CIK_CACHE:
        return _CIK_CACHE[ticker_upper]

    if _TICKERS_DATA is None:
        url = "https://www.sec.gov/files/company_tickers.json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT})
            resp.raise_for_status()
            _TICKERS_DATA = resp.json()

    for entry in _TICKERS_DATA.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            _CIK_CACHE[ticker_upper] = cik
            return cik
    return None


async def _fetch_company_facts(cik: str) -> dict:
    """Company Facts API 호출 — 전체 XBRL 데이터."""
    url = f"{_EDGAR_BASE}/CIK{cik}.json"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT})
        resp.raise_for_status()
        return resp.json()


def _make_entry(entry: dict) -> dict:
    """XBRL 엔트리를 내부 포맷으로 변환."""
    return {
        "end": entry.get("end", ""),
        "start": entry.get("start", ""),
        "val": entry.get("val"),
        "fp": entry.get("fp", ""),
        "fy": entry.get("fy"),
        "form": entry.get("form", ""),
    }


def _extract_facts(facts: dict) -> dict[str, list[dict]]:
    """XBRL facts에서 필요한 재무 데이터를 태그별로 추출.

    Revenue는 여러 태그 중 가장 최신 데이터를 가진 태그를 선택.
    (기업마다 사용하는 태그가 다르고, 태그 전환 시 구 태그에 오래된 데이터만 남음)

    Returns:
        {"revenue": [{"end": "2024-01-31", "val": 123456, "fp": "FY", ...}, ...], ...}
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    result = defaultdict(list)

    # Revenue: 가장 최신 데이터를 가진 태그 선택
    best_revenue_entries = []
    best_latest_fy = 0
    for xbrl_tag in _REVENUE_TAGS:
        tag_data = us_gaap.get(xbrl_tag, {})
        entries = tag_data.get("units", {}).get("USD", [])
        if not entries:
            continue
        # 태그 내 최신 fiscal year 확인
        max_fy = max((e.get("fy") or 0) for e in entries)
        if max_fy > best_latest_fy:
            best_latest_fy = max_fy
            best_revenue_entries = entries

    if best_revenue_entries:
        result["revenue"] = [_make_entry(e) for e in best_revenue_entries]

    # 기타 태그
    for xbrl_tag, internal_key in _OTHER_TAGS.items():
        tag_data = us_gaap.get(xbrl_tag, {})
        units = tag_data.get("units", {})
        entries = units.get("USD", []) or units.get("USD/shares", [])
        for entry in entries:
            result[internal_key].append(_make_entry(entry))

    return dict(result)


def _build_annual(raw: dict[str, list[dict]], n_years: int = 3) -> list[dict]:
    """연간 재무제표 추출 (최근 n_years년).

    같은 FY에 비교 데이터(prior year)와 실제 데이터가 혼재하므로,
    각 (fy, key) 조합에서 가장 최신 end 날짜의 값을 사용.
    """
    # annual_data[fy][key] = (end_date, value) 형태로 최신 end 기준 선택
    annual_data: dict[int, dict] = {}
    annual_end: dict[int, dict[str, str]] = {}  # fy -> key -> end_date

    for key, entries in raw.items():
        for e in entries:
            if e["fp"] != "FY" and e["form"] != "10-K":
                continue
            fy = e.get("fy")
            if not fy:
                continue
            if fy not in annual_data:
                annual_data[fy] = {"fiscal_year": fy, "end_date": e["end"]}
                annual_end[fy] = {}

            # 같은 FY/key에 대해 가장 최신 end_date의 값을 선택
            prev_end = annual_end.get(fy, {}).get(key, "")
            if e["end"] >= prev_end:
                annual_data[fy][key] = e["val"]
                annual_end[fy][key] = e["end"]
                # end_date도 가장 최신으로 갱신
                if e["end"] > annual_data[fy].get("end_date", ""):
                    annual_data[fy]["end_date"] = e["end"]

    # 최근 n_years년 정렬
    sorted_years = sorted(annual_data.keys(), reverse=True)[:n_years]
    return [annual_data[y] for y in sorted_years]


def _period_days(start: str, end: str) -> int:
    """start/end 문자열(YYYY-MM-DD)에서 기간(일수) 계산."""
    if not start or not end or len(start) < 10 or len(end) < 10:
        return 999  # 알 수 없으면 긴 기간으로 취급 (비선호)
    try:
        from datetime import date
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10])
        return (e - s).days
    except ValueError:
        return 999


def _build_quarterly(raw: dict[str, list[dict]], n_quarters: int = 8) -> list[dict]:
    """분기 재무제표 추출 (최근 n_quarters개).

    같은 (fy, fp)에 누적(9개월)과 단독(3개월) 엔트리가 공존하므로,
    가장 짧은 기간(~90일)의 엔트리를 우선 선택.
    """
    # (fy, fp, key) 별로 가장 짧은 기간의 값을 선택
    quarterly_data: dict[str, dict] = {}
    quarterly_periods: dict[str, dict[str, int]] = {}  # qkey -> key -> period_days

    for key, entries in raw.items():
        q_entries = [
            e for e in entries
            if e["fp"] in ("Q1", "Q2", "Q3", "Q4") and e.get("fy")
        ]

        for e in q_entries:
            qkey = f"{e['fy']}-{e['fp']}"
            if qkey not in quarterly_data:
                quarter_num = int(e["fp"][1])
                quarterly_data[qkey] = {
                    "fiscal_year": e["fy"],
                    "fiscal_quarter": quarter_num,
                    "end_date": e["end"],
                    "fp": e["fp"],
                }
                quarterly_periods[qkey] = {}

            # 이 엔트리의 기간
            days = _period_days(e.get("start", ""), e.get("end", ""))
            prev_days = quarterly_periods.get(qkey, {}).get(key, 999)

            # 더 짧은 기간(단독 분기 ~90일)을 우선 선택
            if key not in quarterly_data[qkey] or quarterly_data[qkey].get(key) is None or days < prev_days:
                quarterly_data[qkey][key] = e["val"]
                quarterly_periods[qkey][key] = days

    # 정렬 후 최근 n_quarters개
    sorted_keys = sorted(quarterly_data.keys(), reverse=True)[:n_quarters]
    return [quarterly_data[k] for k in sorted_keys]


async def fetch_financials(ticker: str) -> dict:
    """SEC EDGAR에서 연간 + 분기 재무제표 수집.

    Returns:
        {"annual": [{fiscal_year, revenue, ...}], "quarterly": [{...}]}
        에러 시: {"error": "..."}
    """
    try:
        cik = await _get_cik(ticker)
        if not cik:
            logger.warning(f"[EDGAR] {ticker} CIK 찾기 실패")
            return {"annual": [], "quarterly": [], "error": f"CIK not found for {ticker}"}

        facts = await _fetch_company_facts(cik)
        raw = _extract_facts(facts)

        if not raw:
            return {"annual": [], "quarterly": [], "error": "No XBRL data found"}

        annual = _build_annual(raw, n_years=3)
        quarterly = _build_quarterly(raw, n_quarters=8)

        logger.info(f"[EDGAR] {ticker} 수집 완료: 연간 {len(annual)}개, 분기 {len(quarterly)}개")
        return {"annual": annual, "quarterly": quarterly}

    except Exception as e:
        logger.error(f"[EDGAR] {ticker} 수집 실패: {e}")
        return {"annual": [], "quarterly": [], "error": str(e)}
