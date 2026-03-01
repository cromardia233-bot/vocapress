"""$B/$M 표기, % 포맷 등 표시 유틸리티"""


def fmt_dollar(value: float | None) -> str:
    """금액을 $B 또는 $M 포맷으로 변환."""
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:.1f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.1f}K"
    return f"{sign}${abs_val:.2f}"


def fmt_pct(value: float | None, sign: bool = True) -> str:
    """퍼센트 포맷. sign=True이면 +/- 표시."""
    if value is None:
        return "N/A"
    if sign and value > 0:
        return f"+{value:.1f}%"
    return f"{value:.1f}%"


def fmt_eps(value: float | None) -> str:
    """EPS 포맷."""
    if value is None:
        return "N/A"
    return f"${value:.2f}"


def fmt_date_header(date_str: str) -> str:
    """YYYY-MM-DD → YYMMDD 변환."""
    if not date_str or len(date_str) < 10:
        return date_str or ""
    return date_str[2:4] + date_str[5:7] + date_str[8:10]
