"""yfinance를 통한 주가/밸류에이션 데이터 수집

동기 라이브러리이므로 asyncio.to_thread()로 래핑하여 사용.
"""

import asyncio
import logging

import yfinance as yf

logger = logging.getLogger(__name__)


def _fetch_sync(ticker: str) -> dict:
    """yfinance 동기 호출 — 주가, 시가총액, 밸류에이션 지표 수집."""
    stock = yf.Ticker(ticker)
    info = stock.info

    result = {
        "ticker": ticker.upper(),
        "name": info.get("shortName") or info.get("longName", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "previous_close": info.get("previousClose"),
        "market_cap": info.get("marketCap"),
        "per": info.get("trailingPE"),
        "forward_per": info.get("forwardPE"),
        "pbr": info.get("priceToBook"),
        "psr": info.get("priceToSalesTrailing12Months"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_revenue": info.get("enterpriseToRevenue"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "week52_low": info.get("fiftyTwoWeekLow"),
        "avg_volume": info.get("averageVolume"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "currency": info.get("currency", "USD"),
    }

    return result


async def fetch_price_data(ticker: str) -> dict:
    """비동기 래퍼 — yfinance 주가/밸류에이션 데이터 수집.

    Returns:
        {"ticker", "name", "price", "market_cap", "per", "pbr", ...}
    """
    try:
        data = await asyncio.to_thread(_fetch_sync, ticker)
        logger.info(f"[yfinance] {ticker} 데이터 수집 완료: price={data.get('price')}")
        return data
    except Exception as e:
        logger.error(f"[yfinance] {ticker} 수집 실패: {e}")
        return {"ticker": ticker.upper(), "error": str(e)}
