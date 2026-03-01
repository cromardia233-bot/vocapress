"""SQLite 스키마 + CRUD — aiosqlite 기반 비동기 DB 관리"""

import json
import logging
from datetime import datetime

import aiosqlite

from .config import DB_PATH

logger = logging.getLogger(__name__)

# 스키마 정의
_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    report_type TEXT NOT NULL,  -- 'professional' 또는 'easy'
    report_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    period_type TEXT NOT NULL,  -- 'annual' 또는 'quarterly'
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,
    end_date TEXT,
    revenue REAL,
    gross_profit REAL,
    op_income REAL,
    net_income REAL,
    eps REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS valuation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price REAL,
    market_cap REAL,
    per REAL,
    pbr REAL,
    psr REAL,
    ev_ebitda REAL,
    week52_high REAL,
    week52_low REAL,
    dividend_yield REAL,
    beta REAL,
    snapshot_data TEXT,  -- 전체 JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS earnings_call_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,
    guidance_json TEXT,
    qa_summary_json TEXT,
    metrics_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reports_ticker ON analysis_reports(ticker);
CREATE INDEX IF NOT EXISTS idx_financials_ticker ON financials(ticker);
CREATE INDEX IF NOT EXISTS idx_valuation_ticker ON valuation_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_call_data(ticker);
"""


async def init_db():
    """DB 초기화 — 테이블 생성."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info(f"DB 초기화 완료: {DB_PATH}")


async def save_report(ticker: str, report_type: str, report_text: str):
    """리포트 저장."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO analysis_reports (ticker, report_type, report_text, created_at) VALUES (?, ?, ?, ?)",
            (ticker.upper(), report_type, report_text, datetime.now().isoformat()),
        )
        await db.commit()


async def save_financials(ticker: str, period_type: str, records: list[dict]):
    """재무제표 저장 (연간 또는 분기)."""
    if not records:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO financials
               (ticker, period_type, fiscal_year, fiscal_quarter, end_date,
                revenue, gross_profit, op_income, net_income, eps, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    ticker.upper(), period_type,
                    r.get("fiscal_year"), r.get("fiscal_quarter"), r.get("end_date"),
                    r.get("revenue"), r.get("gross_profit"),
                    r.get("op_income"), r.get("net_income"), r.get("eps"),
                    datetime.now().isoformat(),
                )
                for r in records
            ],
        )
        await db.commit()


async def save_valuation(ticker: str, data: dict):
    """밸류에이션 스냅샷 저장."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO valuation_snapshots
               (ticker, price, market_cap, per, pbr, psr, ev_ebitda,
                week52_high, week52_low, dividend_yield, beta, snapshot_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker.upper(),
                data.get("price"), data.get("market_cap"),
                data.get("per"), data.get("pbr"), data.get("psr"), data.get("ev_ebitda"),
                data.get("week52_high"), data.get("week52_low"),
                data.get("dividend_yield"), data.get("beta"),
                json.dumps(data, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        await db.commit()


async def save_earnings_call(ticker: str, year: int, quarter: int,
                             guidance: dict, qa_summary: list, metrics: dict):
    """어닝콜 분석 결과 저장."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO earnings_call_data
               (ticker, fiscal_year, fiscal_quarter,
                guidance_json, qa_summary_json, metrics_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker.upper(), year, quarter,
                json.dumps(guidance, ensure_ascii=False),
                json.dumps(qa_summary, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        await db.commit()


async def get_latest_reports(ticker: str, limit: int = 5) -> list[dict]:
    """최근 리포트 조회."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT id, ticker, report_type, report_text, created_at
               FROM analysis_reports
               WHERE ticker = ?
               ORDER BY created_at DESC LIMIT ?""",
            (ticker.upper(), limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_latest_valuation(ticker: str) -> dict | None:
    """최근 밸류에이션 스냅샷 조회."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM valuation_snapshots
               WHERE ticker = ?
               ORDER BY created_at DESC LIMIT 1""",
            (ticker.upper(),),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
