from fastapi import APIRouter, HTTPException, Depends
from api.models.schemas import (
    AnalyzeRequest, AnalyzeResponse, PlanSummary,
    RuleIssue, AIAnalysis, BenchmarkSummary, BenchmarkSnapshot,
    EvaluationSummary,
)
from api.db.connection import get_connection
from api.services.explain import run_explain_analyze, get_schema_for_query
from api.services.rule_engine import RuleEngine
from api.services.claude import analyze_with_claude
from api.services.benchmark import run_benchmark, benchmark_to_dict
from api.services.evaluator import evaluate_fix, evaluation_to_dict
from api.core.cache import make_cache_key, get_cached, set_cached
from api.core.config import get_settings

settings = get_settings()
router = APIRouter()
rule_engine = RuleEngine()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_query(
    request: AnalyzeRequest,
    connection=Depends(get_connection),
):
    """
    Main endpoint — takes a SQL query and returns a full diagnosis.

    Flow:
    1. Check cache — return instantly if seen before
    2. Run EXPLAIN ANALYZE on the query
    3. Fetch table schema
    4. Run rule engine (deterministic, free, fast)
    5. Send to Claude (adds human explanation on top)
    6. Run benchmark (before/after timing with fix applied + rolled back)
    7. Run evaluator (plan-level verification of improvement)
    8. Cache and return
    """

    database_url = request.database_url or settings.database_url

    # ── Step 1: Cache check ──────────────────────────────────────────────────
    cache_key = make_cache_key(request.query, database_url)
    cached = await get_cached(cache_key)
    if cached:
        cached["cached"] = True
        return AnalyzeResponse(**cached)

    # ── Step 2: Run EXPLAIN ANALYZE ──────────────────────────────────────────
    try:
        parsed_plan = await run_explain_analyze(request.query, connection)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── Step 3: Fetch schema ─────────────────────────────────────────────────
    schema = await get_schema_for_query(request.query, connection)

    # ── Step 4: Rule engine ──────────────────────────────────────────────────
    issues = rule_engine.analyze(parsed_plan)

    # ── Step 5: Claude analysis ──────────────────────────────────────────────
    try:
        ai_result = await analyze_with_claude(
            query=request.query,
            parsed_plan=parsed_plan,
            schema=schema,
            known_issues=issues,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    fix_sql = ai_result.get("fix_sql", "")

    # ── Step 6: Benchmark (before/after timing) ──────────────────────────────
    benchmark_result = await run_benchmark(
        conn=connection,
        query=request.query,
        fix_sql=fix_sql,
        runs=3,
    )
    benchmark_dict = benchmark_to_dict(benchmark_result)

    # ── Step 7: Evaluator (plan-level verification) ──────────────────────────
    evaluation_result = await evaluate_fix(
        conn=connection,
        query=request.query,
        fix_sql=fix_sql,
    )
    evaluation_dict = evaluation_to_dict(evaluation_result)

    # ── Step 8: Build response ───────────────────────────────────────────────
    benchmark_summary = None
    if benchmark_dict.get("before"):
        before = benchmark_dict["before"]
        after = benchmark_dict.get("after")
        benchmark_summary = BenchmarkSummary(
            before=BenchmarkSnapshot(**before),
            after=BenchmarkSnapshot(**after) if after else None,
            improvement_pct=benchmark_dict["improvement_pct"],
            cost_reduction_pct=benchmark_dict["cost_reduction_pct"],
            plan_changed=benchmark_dict["plan_changed"],
            improvement_confirmed=benchmark_dict["improvement_confirmed"],
            summary=benchmark_dict["summary"],
            error=benchmark_dict.get("error"),
        )

    evaluation_summary = EvaluationSummary(**evaluation_dict)

    response = AnalyzeResponse(
        query=request.query,
        plan_summary=PlanSummary(
            plan_type=parsed_plan["plan_type"],
            total_cost=parsed_plan["total_cost"],
            actual_time_ms=parsed_plan["actual_time_ms"],
            execution_time_ms=parsed_plan["execution_time_ms"],
            planning_time_ms=parsed_plan["planning_time_ms"],
            rows_estimated=parsed_plan["rows_estimated"],
            rows_actual=parsed_plan["rows_actual"],
        ),
        rule_issues=[
            RuleIssue(
                rule=i.rule,
                severity=i.severity,
                title=i.title,
                detail=i.detail,
                fix_hint=i.fix_hint,
                table=i.table,
                column=i.column,
            )
            for i in issues
        ],
        ai_analysis=AIAnalysis(**ai_result),
        benchmark=benchmark_summary,
        evaluation=evaluation_summary,
        cached=False,
    )

    # ── Step 9: Cache result ─────────────────────────────────────────────────
    await set_cached(cache_key, response.dict())

    return response