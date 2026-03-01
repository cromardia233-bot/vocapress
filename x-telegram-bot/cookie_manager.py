import logging
import browser_cookie3

logger = logging.getLogger(__name__)

_cookie_cache: dict[str, str] | None = None


def _extract_cookies() -> dict[str, str]:
    """Extract X/Twitter cookies from Chrome browser."""
    try:
        cj = browser_cookie3.chrome(domain_name=".x.com")
    except Exception as e:
        logger.warning("Failed to read .x.com cookies: %s", e)
        cj = []

    cookies: dict[str, str] = {}
    for cookie in cj:
        cookies[cookie.name] = cookie.value

    # Also try .twitter.com if auth_token not found
    if "auth_token" not in cookies:
        try:
            cj2 = browser_cookie3.chrome(domain_name=".twitter.com")
            for cookie in cj2:
                if cookie.name not in cookies:
                    cookies[cookie.name] = cookie.value
        except Exception as e:
            logger.warning("Failed to read .twitter.com cookies: %s", e)

    return cookies


def get_x_cookies(force_refresh: bool = False) -> dict[str, str]:
    """Get cached X cookies, refreshing if needed.

    Returns dict with at least 'auth_token' and 'ct0' keys if valid.
    """
    global _cookie_cache
    if _cookie_cache is None or force_refresh:
        _cookie_cache = _extract_cookies()
    return _cookie_cache


def validate_cookies(cookies: dict[str, str]) -> tuple[bool, str]:
    """Check if cookies contain the required keys."""
    if not cookies.get("auth_token"):
        return False, "auth_token missing — make sure you are logged in to x.com in Chrome"
    if not cookies.get("ct0"):
        return False, "ct0 (CSRF token) missing — try visiting x.com in Chrome first"
    return True, "OK"


def invalidate_cache() -> None:
    """Clear the cookie cache so next call re-extracts from Chrome."""
    global _cookie_cache
    _cookie_cache = None
