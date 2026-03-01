"""YoY, QoQ, 마진율, Beat/Miss 분석"""

import logging

from ..storage.db import Database
from ..parser.financial_parser import compute_beat_miss
from ..parser.quarter_utils import get_prev_quarter, get_prev_year_same_quarter

logger = logging.getLogger(__name__)


def compute_growth_metrics(db: Database, ticker: str,
                           calendar_year: int, calendar_quarter: int) -> dict:
    """YoY, QoQ 성장률 및 마진율 계산.

    Returns:
        {
            "revenue": float, "gross_profit": float, ...,
            "gpm": float, "opm": float, "npm": float,
            "yoy_revenue": float, "yoy_op_income": float,
            "qoq_revenue": float, "qoq_op_income": float,
            "estimates": {
                "revenue": {"consensus": float, "actual": float, "beat_miss": str},
                "eps": {"consensus": float, "actual": float, "beat_miss": str},
            },
            "after_hours_pct": float | None,
        }
    """
    current = db.get_financials(ticker, calendar_year, calendar_quarter)
    result = dict(current)

    # 마진율 계산
    rev = current.get("revenue")
    if rev and rev > 0:
        gp = current.get("gross_profit")
        op = current.get("op_income")
        ni = current.get("net_income")
        if gp is not None:
            result["gpm"] = round(gp / rev * 100, 1)
        if op is not None:
            result["opm"] = round(op / rev * 100, 1)
        if ni is not None:
            result["npm"] = round(ni / rev * 100, 1)

    # YoY 계산
    yoy_year, yoy_q = get_prev_year_same_quarter(calendar_year, calendar_quarter)
    prev_yoy = db.get_financials(ticker, yoy_year, yoy_q)
    for key in ["revenue", "op_income"]:
        curr_val = current.get(key)
        prev_val = prev_yoy.get(key)
        if curr_val is not None and prev_val is not None and prev_val != 0:
            result[f"yoy_{key}"] = round((curr_val - prev_val) / abs(prev_val) * 100, 1)

    # QoQ 계산
    qoq_year, qoq_q = get_prev_quarter(calendar_year, calendar_quarter)
    prev_qoq = db.get_financials(ticker, qoq_year, qoq_q)
    for key in ["revenue", "op_income"]:
        curr_val = current.get(key)
        prev_val = prev_qoq.get(key)
        if curr_val is not None and prev_val is not None and prev_val != 0:
            result[f"qoq_{key}"] = round((curr_val - prev_val) / abs(prev_val) * 100, 1)

    # Beat/Miss 판정
    estimates = db.get_estimates(ticker, calendar_year, calendar_quarter)
    result["estimates"] = {}
    for metric in ["revenue", "eps"]:
        est_data = estimates.get(metric)
        if est_data:
            consensus = est_data.get("consensus")
            # financials 테이블 actual 우선, 없으면 analyst_estimates.actual fallback
            actual = current.get(metric) if metric == "revenue" else current.get("eps_diluted")
            if actual is None:
                actual = est_data.get("actual")
            if consensus is not None and actual is not None:
                beat_miss = compute_beat_miss(actual, consensus)
                result["estimates"][metric] = {
                    "consensus": consensus,
                    "actual": actual,
                    "beat_miss": beat_miss,
                }
                # DB에도 업데이트
                db.upsert_estimate(
                    ticker, calendar_year, calendar_quarter,
                    metric, consensus=consensus, actual=actual, beat_miss=beat_miss,
                )

    # After Hours
    ec = db.get_earnings_call(ticker, calendar_year, calendar_quarter)
    if ec:
        ah = db.get_price_reaction(ec["id"])
        result["after_hours_pct"] = ah
    else:
        result["after_hours_pct"] = None

    return result
