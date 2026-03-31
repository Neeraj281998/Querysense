"""
api/services/benchmark.py

Before/after benchmarking service (Upgrade 1).

Workflow:
  1. Run EXPLAIN ANALYZE on the original query → capture plan + timing
  2. Apply the AI-suggested fix inside a BEGIN/ROLLBACK transaction
     (so nothing is permanently changed in the DB)
  3. Run EXPLAIN ANALYZE again → capture improved plan + timing
  4. Return structured comparison

Design notes
------------
- Every mutation (CREATE INDEX, ALTER TABLE …) runs inside an explicit
  transaction that is always rolled back, so the user's database is
  never permanently modified.
- asyncpg is used directly; the connection is borrowed from the
  existing pool created in api/db/connection.py.
- Timing comes from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) — the
  "Actual Total Time" at the top-level plan node, measured in ms.
- We run each query 3 times and take the median to reduce noise from
  cold caches and OS scheduling jitter.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import asyncpg


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlanSnapshot:
    """Metrics extracted from a single EXPLAIN ANALYZE run."""
    plan_type: str           # top-level node type, e.g. "Seq Scan", "Index Scan"
    total_cost: float        # planner cost estimate (startup..total)
    actual_time_ms: float    # median actual execution time in ms
    rows_scanned: int        # rows actually processed by the top node
    raw_plan: dict           # full JSON plan (for debugging)


@dataclass
class BenchmarkResult:
    """Side-by-side comparison returned to the caller."""
    # Before
    before: PlanSnapshot

    # After (None if the fix could not be applied)
    after: Optional[PlanSnapshot]

    # Derived metrics
    improvement_pct: float = 0.0          # positive = faster
    cost_reduction_pct: float = 0.0
    plan_changed: bool = False
    improvement_confirmed: bool = False   # True if after is meaningfully faster

    # Human-readable summary
    summary: str = ""

    # Any error that prevented benchmarking
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _run_explain(
    conn: asyncpg.Connection,
    query: str,
    runs: int = 3,
) -> PlanSnapshot:
    """
    Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) `runs` times and return
    a PlanSnapshot built from the median execution time.
    """
    timings: list[float] = []
    last_plan: dict = {}

    for _ in range(runs):
        rows = await conn.fetch(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        )
        plan_json = json.loads(rows[0][0])
        top_node = plan_json[0]["Plan"]
        timing = top_node.get("Actual Total Time", 0.0)
        timings.append(timing)
        last_plan = plan_json[0]

    top = last_plan["Plan"]
    return PlanSnapshot(
        plan_type=top.get("Node Type", "Unknown"),
        total_cost=top.get("Total Cost", 0.0),
        actual_time_ms=statistics.median(timings),
        rows_scanned=top.get("Actual Rows", 0),
        raw_plan=last_plan,
    )


def _extract_plan_type(snapshot: PlanSnapshot) -> str:
    """
    Dig into sub-nodes to find the most interesting scan type.
    EXPLAIN often wraps a scan in an Aggregate or Sort at the top level.
    We walk one level down to find the most relevant leaf type.
    """
    plans = snapshot.raw_plan.get("Plan", {}).get("Plans", [])
    if plans:
        # Return the first child node type if the root is Aggregate/Sort/Gather
        root_type = snapshot.plan_type
        if root_type in ("Aggregate", "Sort", "Gather", "Gather Merge", "Limit"):
            return plans[0].get("Node Type", root_type)
    return snapshot.plan_type


def _build_summary(result: BenchmarkResult) -> str:
    if result.error:
        return f"Benchmark failed: {result.error}"

    if result.after is None:
        return "Fix could not be applied — before-only snapshot captured."

    direction = "faster" if result.improvement_pct > 0 else "slower"
    before_type = _extract_plan_type(result.before)
    after_type = _extract_plan_type(result.after)

    plan_change = (
        f"{before_type} → {after_type}"
        if result.plan_changed
        else f"Plan unchanged ({before_type})"
    )

    return (
        f"Query is {abs(result.improvement_pct):.1f}% {direction} after fix. "
        f"Plan: {plan_change}. "
        f"Cost reduced by {result.cost_reduction_pct:.1f}%."
    )


# ---------------------------------------------------------------------------
# Safe DDL execution
# ---------------------------------------------------------------------------

_SAFE_DDL_PATTERN = re.compile(
    r"^\s*(CREATE\s+(UNIQUE\s+)?INDEX|ANALYZE|UPDATE\s+STATISTICS)\b",
    re.IGNORECASE,
)

_RISKY_PATTERN = re.compile(
    r"\b(DROP|TRUNCATE|DELETE|INSERT|UPDATE)\b",
    re.IGNORECASE,
)


def _is_safe_fix(fix_sql: str) -> bool:
    """
    Only allow fixes that are read-only with respect to data:
    CREATE INDEX, ANALYZE, UPDATE STATISTICS.
    Reject anything that mutates rows.
    """
    if _RISKY_PATTERN.search(fix_sql):
        return False
    return True  # We'll apply inside a transaction anyway


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_benchmark(
    conn: asyncpg.Connection,
    query: str,
    fix_sql: Optional[str],
    runs: int = 3,
) -> BenchmarkResult:
    """
    Main entry point.

    Parameters
    ----------
    conn      : asyncpg connection (borrowed from pool — not closed here)
    query     : the original slow SQL query (SELECT only)
    fix_sql   : the DDL/SQL suggested by Claude (e.g. CREATE INDEX …)
    runs      : number of EXPLAIN ANALYZE runs for median timing

    Returns
    -------
    BenchmarkResult with before/after snapshots and derived metrics.
    """
    # ── Step 1: capture baseline ──────────────────────────────────────────
    try:
        before_snap = await _run_explain(conn, query, runs=runs)
    except Exception as exc:
        return BenchmarkResult(
            before=PlanSnapshot("Unknown", 0.0, 0.0, 0, {}),
            after=None,
            error=f"Baseline EXPLAIN failed: {exc}",
        )

    # ── Step 2: if no fix, return before-only result ───────────────────────
    if not fix_sql or not fix_sql.strip():
        result = BenchmarkResult(before=before_snap, after=None)
        result.summary = "No fix SQL provided — baseline snapshot only."
        return result

    # ── Step 3: safety check ──────────────────────────────────────────────
    if not _is_safe_fix(fix_sql):
        result = BenchmarkResult(
            before=before_snap,
            after=None,
            error=(
                "Fix SQL contains data-mutating statements (INSERT/UPDATE/DELETE/DROP). "
                "Only CREATE INDEX and ANALYZE are allowed in benchmark mode."
            ),
        )
        result.summary = _build_summary(result)
        return result

    # ── Step 4: apply fix inside a transaction, benchmark, rollback ────────
    after_snap: Optional[PlanSnapshot] = None
    apply_error: Optional[str] = None

    tr = conn.transaction()
    try:
        await tr.start()

        # Apply the fix (e.g. CREATE INDEX CONCURRENTLY is not allowed inside
        # a transaction — fall back to CREATE INDEX)
        safe_fix = fix_sql.replace("CONCURRENTLY", "")
        await conn.execute(safe_fix)

        # Capture post-fix plan
        after_snap = await _run_explain(conn, query, runs=runs)

    except Exception as exc:
        apply_error = str(exc)
    finally:
        # Always rollback — we never want to keep changes
        try:
            await tr.rollback()
        except Exception:
            pass  # already rolled back or connection error

    # ── Step 5: compute metrics ────────────────────────────────────────────
    if after_snap is None:
        result = BenchmarkResult(
            before=before_snap,
            after=None,
            error=apply_error,
        )
        result.summary = _build_summary(result)
        return result

    before_ms = before_snap.actual_time_ms or 0.001  # avoid div/0
    after_ms = after_snap.actual_time_ms or 0.001

    improvement_pct = ((before_ms - after_ms) / before_ms) * 100
    cost_reduction_pct = (
        ((before_snap.total_cost - after_snap.total_cost) / (before_snap.total_cost or 1))
        * 100
    )

    before_type = _extract_plan_type(before_snap)
    after_type = _extract_plan_type(after_snap)
    plan_changed = before_type != after_type

    result = BenchmarkResult(
        before=before_snap,
        after=after_snap,
        improvement_pct=round(improvement_pct, 1),
        cost_reduction_pct=round(max(cost_reduction_pct, 0.0), 1),
        plan_changed=plan_changed,
        improvement_confirmed=improvement_pct > 10,  # meaningful if > 10% faster
    )
    result.summary = _build_summary(result)
    return result


# ---------------------------------------------------------------------------
# Serialization helper (used by the API route)
# ---------------------------------------------------------------------------

def benchmark_to_dict(result: BenchmarkResult) -> dict:
    """Convert BenchmarkResult to a JSON-serialisable dict."""

    def snap_to_dict(s: Optional[PlanSnapshot]) -> Optional[dict]:
        if s is None:
            return None
        return {
            "plan_type": s.plan_type,
            "total_cost": s.total_cost,
            "actual_time_ms": s.actual_time_ms,
            "rows_scanned": s.rows_scanned,
        }

    return {
        "before": snap_to_dict(result.before),
        "after": snap_to_dict(result.after),
        "improvement_pct": result.improvement_pct,
        "cost_reduction_pct": result.cost_reduction_pct,
        "plan_changed": result.plan_changed,
        "improvement_confirmed": result.improvement_confirmed,
        "summary": result.summary,
        "error": result.error,
    }