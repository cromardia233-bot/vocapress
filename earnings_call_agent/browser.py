"""Playwright 브라우저 관리 (단순 헤드리스 모드)

로그인 불필요 — 페이지 렌더링만 수행.
persistent context / 파일 잠금 / PID 관리 불필요.
"""

import logging

from playwright.async_api import async_playwright, Browser, Playwright

logger = logging.getLogger(__name__)


async def create_browser(headless: bool = True) -> tuple[Playwright, Browser]:
    """단순 Playwright 브라우저 생성 (로그인 불필요).

    Edge headless에서 열린 페이지가 모두 닫히면 브라우저 프로세스가 종료되므로,
    keepalive context+page를 미리 생성하여 브라우저를 유지한다.
    browser.close() 호출 시 keepalive도 함께 정리된다.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ],
    )
    # Edge headless keepalive: 빈 context+page를 유지하여 프로세스 종료 방지
    _ctx = await browser.new_context()
    await _ctx.new_page()
    logger.debug("브라우저 생성 완료")
    return pw, browser


async def close_browser(pw: Playwright, browser: Browser):
    """브라우저 리소스 정리."""
    try:
        await browser.close()
    except Exception as e:
        logger.warning(f"브라우저 닫기 실패: {e}")
    try:
        await pw.stop()
    except Exception as e:
        logger.warning(f"Playwright 종료 실패: {e}")
