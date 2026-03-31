"""
api/services/evaluator.py

Evaluation layer (Upgrade 3).

This is what separates an AI toy from an AI system. After Claude suggests
a fix, the evaluator:
  1. Captures the original plan (cost, node type, rows)
  2. Applies the fix inside a BEGIN/ROLLBACK transaction
  3. Captures the post-fix plan
  4. Compares them structurally — not just timing
  5. Returns a verdict: improvement_confirmed + confidence level

The key difference from benchmark.py
-------------------------------------
benchmark.py  → timing-focused, uses EXPLAIN ANALYZE (actually executes),
                median of 3 runs, designed for the before/after table shown
                to the user.

evaluator.py  → plan-focused, uses EXPLAIN (FORMAT JSON) without ANALYZE
                so it's instant and deterministic (no row execution needed),
                compares cost estimates and node types structurally, designed
                to generate the honest resume metric across 50 test queries.

Why cost estimates instead of actual timing for evaluation?
-----------------------------------------------------------
When you run evaluator on 50 queries in scripts/benchmark.py, you don't
want to actually execute each query (some take 30+ seconds before the fix).
The planner's cost estimate is a reliable proxy: if the plan flips from
Seq Scan (cost=3240) to Index Scan (cost=0.42), that's a verified win
regardless of wall-clock time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import asyncpg


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH = 50.0    # cost reduced by > 50% → "high"
CONFIDENCE_MEDIUM = 20.0  # cost reduced by > 20% → "medium"
# anything below → "low"

# Plan node types that indicate a full-table scan (always bad on large tables)
SEQ_SCAN_NODES = {"Seq Scan", "Parallel Seq Scan"}

# Plan node types that indicate index usage (good)
INDEX_SCAN_NODES = {
    "Index Scan",
    "Index Only Scan",
    "Bitmap Index Scan",
    "Bitmap Heap Scan",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    """
    Structured verdict on whether the suggested fix actually improves the plan.
    This is what scripts/benchmark.py aggregates across 50 queries to generate
    the resume metric.
    """
    improvement_confirmed: bool

    # Cost metrics
    original_cost: float
    optimized_cost: float
    cost_reduction_pct: float

    # Plan structure
    plan_changed: bool
    original_plan_type: str    # top-level or most relevant scan node
    optimized_plan_type: str

    # Verdict
    confidence: str            # "high" | "medium" | "low" | "none"

    # Optional detail on what changed
    details: list[str] = field(default_factory=list)

    # Error if evaluation could not complete
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Plan parsing helpers
# ---------------------------------------------------------------------------

def _get_top_node(plan_json: list[dict]) -> dict:
    """Extract the top-level Plan node from EXPLAIN JSON output."""
    return plan_json[0]["Plan"]


def _find_primary_scan(node: dict) -> str:
    """
    Walk the plan tree (BFS) and return the first scan node type found.
    This gives us the most meaningful node — e.g. 'Index Scan' buried
    under an Aggregate at the root.
    """
    queue = [node]
    while queue:
        current = queue.pop(0)
        node_type = current.get("Node Type", "")
        if node_type in SEQ_SCAN_NODES or node_type in INDEX_SCAN_NODES:
            return node_type
        queue.extend(current.get("Plans", []))
    # Nothing found — return the root type
    return node.get("Node Type", "Unknown")


def _collect_all_node_types(node: dict, types: Optional[set] = None) -> set[str]:
    """Recursively collect every node type in the plan tree."""
    if types is None:
        types = set()
    types.add(node.get("Node Type", ""))
    for child in node.get("Plans", []):
        _collect_all_node_types(child, types)
    return types


def _total_cost(node: dict) -> float:
    """Get the total cost estimate from the top-level node."""
    return float(node.get("Total Cost", 0.0))


async def _get_plan(conn: asyncpg.Connection, query: str) -> list[dict]:
    """
    Run EXPLAIN (FORMAT JSON) — no ANALYZE, so the query is NOT executed.
    Returns the parsed JSON plan.
    """
    rows = await conn.fetch(f"EXPLAIN (FORMAT JSON) {query}")
    return json.loads(rows[0][0])


# ---------------------------------------------------------------------------
# Safety guard (same logic as benchmark.py — belt and suspenders)
# ---------------------------------------------------------------------------

import re

_RISKY_PATTERN = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+INDEX|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w)\b",
    re.IGNORECASE,
)


def _is_safe_fix(fix_sql: str) -> bool:
    """Reject DDL that could permanently destroy data."""
    return not bool(_RISKY_PATTERN.search(fix_sql))


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

def _compute_confidence(cost_reduction_pct: float, plan_changed: bool) -> str:
    if cost_reduction_pct >= CONFIDENCE_HIGH or plan_changed:
        return "high"
    if cost_reduction_pct >= CONFIDENCE_MEDIUM:
        return "medium"
    if cost_reduction_pct > 0:
        return "low"
    return "none"


def _build_details(
    original_node: dict,
    optimized_node: dict,
    original_type: str,
    optimized_type: str,
    cost_reduction_pct: float,
) -> list[str]:
    """Generate human-readable detail strings for the evaluation report."""
    details = []

    if original_type in SEQ_SCAN_NODES and optimized_type in INDEX_SCAN_NODES:
        details.append(
            f"Sequential scan eliminated: {original_type} → {optimized_type}"
        )
    elif original_type != optimized_type:
        details.append(f"Plan node changed: {original_type} → {optimized_type}")
    else:
        details.append(f"Plan node unchanged: {original_type}")

    orig_cost = _total_cost(original_node)
    opt_cost = _total_cost(optimized_node)
    details.append(
        f"Cost estimate: {orig_cost:.2f} → {opt_cost:.2f} "
        f"({cost_reduction_pct:.1f}% reduction)"
    )

    # Flag if nested loops remain on large row estimates
    orig_types = _collect_all_node_types(original_node)
    opt_types = _collect_all_node_types(optimized_node)
    if "Nested Loop" in opt_types:
        opt_rows = optimized_node.get("Plan Rows", 0)
        if opt_rows > 10_000:
            details.append(
                f"⚠ Nested Loop remains in optimized plan "
                f"({opt_rows:,} estimated rows — may still be slow)"
            )

    if "Hash Join" in opt_types and "Hash Join" not in orig_types:
        details.append("Hash Join introduced — good for large join inputs")

    return details


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def evaluate_fix(
    conn: asyncpg.Connection,
    query: str,
    fix_sql: str,
) -> EvaluationResult:
    """
    Apply fix_sql inside a transaction, compare plans, always rollback.

    Parameters
    ----------
    conn     : asyncpg connection (not closed here)
    query    : the original SELECT query
    fix_sql  : DDL suggested by Claude (e.g. CREATE INDEX …)

    Returns
    -------
    EvaluationResult with verdict, cost metrics, and plan type comparison.
    """
    # ── Step 1: safety check ──────────────────────────────────────────────
    if not _is_safe_fix(fix_sql):
        return EvaluationResult(
            improvement_confirmed=False,
            original_cost=0.0,
            optimized_cost=0.0,
            cost_reduction_pct=0.0,
            plan_changed=False,
            original_plan_type="Unknown",
            optimized_plan_type="Unknown",
            confidence="none",
            error=(
                "fix_sql contains unsafe statements. "
                "Only CREATE INDEX and ANALYZE are permitted."
            ),
        )

    # ── Step 2: capture original plan (outside any transaction) ───────────
    try:
        original_plan_json = await _get_plan(conn, query)
        original_node = _get_top_node(original_plan_json)
    except Exception as exc:
        return EvaluationResult(
            improvement_confirmed=False,
            original_cost=0.0,
            optimized_cost=0.0,
            cost_reduction_pct=0.0,
            plan_changed=False,
            original_plan_type="Unknown",
            optimized_plan_type="Unknown",
            confidence="none",
            error=f"Failed to get original plan: {exc}",
        )

    original_cost = _total_cost(original_node)
    original_type = _find_primary_scan(original_node)

    # ── Step 3: apply fix, get optimized plan, rollback ───────────────────
    optimized_node: Optional[dict] = None
    apply_error: Optional[str] = None

    tr = conn.transaction()
    try:
        await tr.start()

        # Strip CONCURRENTLY — not allowed inside a transaction block
        safe_fix = re.sub(r"\bCONCURRENTLY\b", "", fix_sql, flags=re.IGNORECASE)
        await conn.execute(safe_fix)

        optimized_plan_json = await _get_plan(conn, query)
        optimized_node = _get_top_node(optimized_plan_json)

    except Exception as exc:
        apply_error = str(exc)
    finally:
        try:
            await tr.rollback()
        except Exception:
            pass

    # ── Step 4: handle apply failure ──────────────────────────────────────
    if optimized_node is None:
        return EvaluationResult(
            improvement_confirmed=False,
            original_cost=original_cost,
            optimized_cost=0.0,
            cost_reduction_pct=0.0,
            plan_changed=False,
            original_plan_type=original_type,
            optimized_plan_type="Unknown",
            confidence="none",
            error=f"Failed to apply fix: {apply_error}",
        )

    # ── Step 5: compute metrics ────────────────────────────────────────────
    optimized_cost = _total_cost(optimized_node)
    optimized_type = _find_primary_scan(optimized_node)

    cost_reduction_pct = (
        ((original_cost - optimized_cost) / (original_cost or 1.0)) * 100
    )
    cost_reduction_pct = max(round(cost_reduction_pct, 1), 0.0)

    plan_changed = original_type != optimized_type
    confidence = _compute_confidence(cost_reduction_pct, plan_changed)
    improvement_confirmed = confidence in ("high", "medium")

    details = _build_details(
        original_node,
        optimized_node,
        original_type,
        optimized_type,
        cost_reduction_pct,
    )

    return EvaluationResult(
        improvement_confirmed=improvement_confirmed,
        original_cost=round(original_cost, 2),
        optimized_cost=round(optimized_cost, 2),
        cost_reduction_pct=cost_reduction_pct,
        plan_changed=plan_changed,
        original_plan_type=original_type,
        optimized_plan_type=optimized_type,
        confidence=confidence,
        details=details,
    )


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------

def evaluation_to_dict(result: EvaluationResult) -> dict:
    """Convert EvaluationResult to a JSON-serialisable dict."""
    return {
        "improvement_confirmed": result.improvement_confirmed,
        "original_cost": result.original_cost,
        "optimized_cost": result.optimized_cost,
        "cost_reduction_pct": result.cost_reduction_pct,
        "plan_changed": result.plan_changed,
        "original_plan_type": result.original_plan_type,
        "optimized_plan_type": result.optimized_plan_type,
        "confidence": result.confidence,
        "details": result.details,
        "error": result.error,
    }