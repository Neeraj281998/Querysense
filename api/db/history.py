"""
api/db/history.py
Save and retrieve query analyses from the database.

Table is created on first use (CREATE TABLE IF NOT EXISTS).
"""

import json
import logging
from datetime import datetime
from typing import Optional

from api.db.connection import get_pool

logger = logging.getLogger(__name__)

# ── DDL ───────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_analyses (
    id              SERIAL PRIMARY KEY,
    query           TEXT        NOT NULL,
    plan_type       TEXT,
    total_cost      FLOAT,
    execution_time  FLOAT,
    improvement_pct FLOAT,
    confidence      TEXT,
    fix_type        TEXT,
    fix_sql         TEXT,
    full_response   JSONB,
    analyzed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_analyzed_at ON query_analyses (analyzed_at DESC);
"""


async def ensure_table() -> None:
    """Create the history table if it doesn't exist yet."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)


# ── Write ─────────────────────────────────────────────────────────────────────

async def save_analysis(response_data: dict) -> Optional[int]:
    """
    Persist a full AnalyzeResponse dict to the DB.
    Returns the new row id, or None on failure.
    """
    try:
        await ensure_table()
        pool = await get_pool()

        plan    = response_data.get("plan_summary", {})
        bench   = response_data.get("benchmark")   or {}
        ai      = response_data.get("ai_analysis") or {}

        async with pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO query_analyses
                    (query, plan_type, total_cost, execution_time,
                     improvement_pct, confidence, fix_type, fix_sql, full_response)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                RETURNING id
                """,
                response_data.get("query", ""),
                plan.get("plan_type"),
                plan.get("total_cost"),
                plan.get("execution_time_ms"),
                bench.get("improvement_pct"),
                ai.get("confidence"),
                ai.get("fix_type"),
                ai.get("fix_sql"),
                json.dumps(response_data, default=str),
            )
        return row_id

    except Exception as exc:
        logger.warning("Failed to save analysis to history: %s", exc)
        return None


# ── Read ──────────────────────────────────────────────────────────────────────

async def get_recent_analyses(limit: int = 20) -> list[dict]:
    """
    Return the most recent analyses, newest first.
    Each record is a lightweight summary dict (not the full response).
    """
    try:
        await ensure_table()
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    query,
                    plan_type,
                    total_cost,
                    execution_time,
                    improvement_pct,
                    confidence,
                    fix_type,
                    fix_sql,
                    analyzed_at
                FROM query_analyses
                ORDER BY analyzed_at DESC
                LIMIT $1
                """,
                limit,
            )

        return [
            {
                "id":              r["id"],
                "query":           r["query"],
                "plan_type":       r["plan_type"],
                "total_cost":      r["total_cost"],
                "execution_time":  r["execution_time"],
                "improvement_pct": r["improvement_pct"],
                "confidence":      r["confidence"],
                "fix_type":        r["fix_type"],
                "fix_sql":         r["fix_sql"],
                "analyzed_at":     r["analyzed_at"].isoformat() if r["analyzed_at"] else None,
            }
            for r in rows
        ]

    except Exception as exc:
        logger.warning("Failed to fetch history: %s", exc)
        return []


async def get_analysis_by_id(analysis_id: int) -> Optional[dict]:
    """Return the full response JSON for a single analysis."""
    try:
        await ensure_table()
        pool = await get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT full_response, analyzed_at FROM query_analyses WHERE id = $1",
                analysis_id,
            )

        if not row:
            return None

        data = json.loads(row["full_response"])
        data["analyzed_at"] = row["analyzed_at"].isoformat()
        return data

    except Exception as exc:
        logger.warning("Failed to fetch analysis %d: %s", analysis_id, exc)
        return None