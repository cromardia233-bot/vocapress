"""분기/연간 재무 차트 PNG 생성

matplotlib으로 그룹 바 차트를 만들어 bytes로 반환한다.
"""

import asyncio
import io

import matplotlib
matplotlib.use("Agg")  # 비-GUI 백엔드
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── 스타일 상수 ──

COLORS = {
    "revenue": "#4FC3F7",    # 밝은 파랑
    "op_income": "#81C784",  # 밝은 초록
    "net_income": "#FFB74D", # 밝은 주황
}
BG_COLOR = "#1E1E2E"
TEXT_COLOR = "#E0E0E0"
GRID_COLOR = "#3A3A4A"

# matplotlib 전역 상태 보호용 Lock
_chart_lock = asyncio.Lock()


def _fmt_billions(value: float | None) -> str:
    """금액을 $B/$M 포맷."""
    if value is None:
        return ""
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1e9:.1f}B"
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1e6:.0f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1e3:.0f}K"
    return f"{sign}${abs_val:.0f}"


def _setup_dark_style(ax, fig):
    """어두운 배경 스타일 적용."""
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.3, linestyle="--")


def _create_quarterly_chart(ticker: str, quarterly: list[dict]) -> bytes | None:
    """최근 4분기 그룹 바 차트 생성 (동기 내부 함수)."""
    if not quarterly:
        return None

    recent = quarterly[:4][::-1]  # 오래된 순 → 최근 순

    labels = []
    revenues = []
    op_incomes = []
    net_incomes = []

    for q in recent:
        fy = q.get("fiscal_year", "")
        fq = q.get("fiscal_quarter", "")
        labels.append(f"FY{fy}Q{fq}")
        revenues.append(q.get("revenue") or 0)
        op_incomes.append(q.get("op_income") or 0)
        net_incomes.append(q.get("net_income") or 0)

    if not any(revenues):
        return None

    x = np.arange(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    try:
        _setup_dark_style(ax, fig)

        bars1 = ax.bar(x - width, revenues, width, label="Revenue",
                       color=COLORS["revenue"], alpha=0.9)
        bars2 = ax.bar(x, op_incomes, width, label="Op Income",
                       color=COLORS["op_income"], alpha=0.9)
        bars3 = ax.bar(x + width, net_incomes, width, label="Net Income",
                       color=COLORS["net_income"], alpha=0.9)

        # 바 위에 금액 표시
        for bars in [bars1, bars2, bars3]:
            for bar in bars:
                height = bar.get_height()
                if height != 0:
                    va = "bottom" if height > 0 else "top"
                    ax.text(
                        bar.get_x() + bar.get_width() / 2, height,
                        _fmt_billions(height),
                        ha="center", va=va,
                        fontsize=7, color=TEXT_COLOR, fontweight="bold",
                    )

        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(
            f"{ticker.upper()} — Quarterly Financials",
            fontsize=14, fontweight="bold", pad=15,
        )
        ax.legend(
            loc="upper left", fontsize=9,
            facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR,
        )
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda val, pos: _fmt_billions(val))
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor=BG_COLOR)
        buf.seek(0)
        return buf.read()
    finally:
        plt.close(fig)


def _create_annual_chart(ticker: str, annual: list[dict]) -> bytes | None:
    """최근 3년 그룹 바 차트 생성 (동기 내부 함수)."""
    if not annual:
        return None

    recent = annual[:3][::-1]  # 오래된 순 → 최근 순

    labels = []
    revenues = []
    op_incomes = []
    net_incomes = []

    for a in recent:
        fy = a.get("fiscal_year", "")
        labels.append(f"FY{fy}")
        revenues.append(a.get("revenue") or 0)
        op_incomes.append(a.get("op_income") or 0)
        net_incomes.append(a.get("net_income") or 0)

    if not any(revenues):
        return None

    x = np.arange(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    try:
        _setup_dark_style(ax, fig)

        bars1 = ax.bar(x - width, revenues, width, label="Revenue",
                       color=COLORS["revenue"], alpha=0.9)
        bars2 = ax.bar(x, op_incomes, width, label="Op Income",
                       color=COLORS["op_income"], alpha=0.9)
        bars3 = ax.bar(x + width, net_incomes, width, label="Net Income",
                       color=COLORS["net_income"], alpha=0.9)

        # 바 위에 금액 + YoY 성장률 표시
        all_series = [revenues, op_incomes, net_incomes]
        for i, bars in enumerate([bars1, bars2, bars3]):
            values = all_series[i]
            for j, bar in enumerate(bars):
                height = bar.get_height()
                if height != 0:
                    text = _fmt_billions(height)
                    # 2번째 막대부터 YoY 표시
                    if j > 0 and values[j - 1] != 0:
                        yoy = (values[j] - values[j - 1]) / abs(values[j - 1]) * 100
                        yoy_sign = "+" if yoy > 0 else ""
                        text += f"\n({yoy_sign}{yoy:.0f}%)"
                    va = "bottom" if height > 0 else "top"
                    ax.text(
                        bar.get_x() + bar.get_width() / 2, height,
                        text, ha="center", va=va,
                        fontsize=7, color=TEXT_COLOR, fontweight="bold",
                    )

        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(
            f"{ticker.upper()} — Annual Trend",
            fontsize=14, fontweight="bold", pad=15,
        )
        ax.legend(
            loc="upper left", fontsize=9,
            facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR,
        )
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda val, pos: _fmt_billions(val))
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor=BG_COLOR)
        buf.seek(0)
        return buf.read()
    finally:
        plt.close(fig)


# ── 비동기 공개 API (matplotlib thread-safety 보장) ──

async def create_quarterly_chart(ticker: str, quarterly: list[dict]) -> bytes | None:
    """최근 4분기 그룹 바 차트 생성 (async, Lock 보호)."""
    async with _chart_lock:
        return _create_quarterly_chart(ticker, quarterly)


async def create_annual_chart(ticker: str, annual: list[dict]) -> bytes | None:
    """최근 3년 그룹 바 차트 생성 (async, Lock 보호)."""
    async with _chart_lock:
        return _create_annual_chart(ticker, annual)
