"""최종 한국어 리포트 포맷 생성

context 데이터를 읽어 텔레그램 전송용 한국어 리포트를 생성한다.
섹션: [1] 주요 재무지표, [2] 가이던스, [3] Q&A 요약
"""

from .format_helpers import fmt_dollar, fmt_pct, fmt_eps


def format_report(
    ticker: str,
    year: int,
    quarter: int,
    metrics: dict,
    guidance: dict,
    qa_summary: list[dict],
) -> str:
    """최종 한국어 리포트 생성."""
    lines: list[str] = []
    lines.append(f"{ticker.upper()} FY{year} Q{quarter} Earnings Call Summary")
    lines.append("=" * 40)

    # ── [1] 주요 재무지표 ──
    if metrics:
        lines.append("")
        lines.append("[1] Key Financial Metrics")
        lines.append("-" * 30)
        _metric_line(lines, metrics, "revenue", "Revenue", fmt_dollar)
        _metric_line(lines, metrics, "gross_profit", "Gross Profit", fmt_dollar)
        _metric_line(lines, metrics, "op_income", "Op Income", fmt_dollar)
        _metric_line(lines, metrics, "net_income", "Net Income", fmt_dollar)
        _metric_line(lines, metrics, "eps_diluted", "EPS", fmt_eps)
        if "gpm" in metrics:
            lines.append(f"  GPM: {fmt_pct(metrics['gpm'], sign=False)}")
        if "opm" in metrics:
            lines.append(f"  OPM: {fmt_pct(metrics['opm'], sign=False)}")
        if "npm" in metrics:
            lines.append(f"  NPM: {fmt_pct(metrics['npm'], sign=False)}")

    # ── [2] 가이던스 ──
    if guidance and (guidance.get("next_quarter") or guidance.get("full_year")):
        lines.append("")
        lines.append("[2] Guidance")
        lines.append("-" * 30)
        if guidance.get("next_quarter"):
            lines.append("  [Next Quarter]")
            for item in guidance["next_quarter"]:
                lines.append(f"    {item}")
        if guidance.get("full_year"):
            lines.append("  [Full Year]")
            for item in guidance["full_year"]:
                lines.append(f"    {item}")

    # ── [3] Q&A 요약 ──
    if qa_summary:
        lines.append("")
        lines.append("[3] Q&A Summary")
        lines.append("-" * 30)
        for i, qa in enumerate(qa_summary, 1):
            firm = qa.get("analyst_firm", "")
            name = qa.get("analyst_name", "")
            header = f"[{firm} - {name}]" if firm else f"[{name}]"
            topic = qa.get("question_topic", "")
            summary = qa.get("summary", "")

            lines.append(f"\n  Q{i}. {header}")
            if topic:
                lines.append(f"  Q) {topic}")
            if summary:
                for bullet in summary.split("\n"):
                    lines.append(f"  {bullet}")

    return "\n".join(lines)


def _metric_line(
    lines: list[str],
    metrics: dict,
    key: str,
    label: str,
    formatter,
) -> None:
    """지표가 존재하면 포맷 후 lines에 추가."""
    if key in metrics:
        lines.append(f"  {label}: {formatter(metrics[key])}")


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """텔레그램 메시지 길이 제한(4096자)에 맞게 분할."""
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    lines = text.split("\n")
    current = ""

    for line in lines:
        # +1 for the newline character
        if current and len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        parts.append(current)

    return parts
