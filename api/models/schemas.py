from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ─── Request Models ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    query: str = Field(
        ...,
        description="The SQL SELECT query to analyze",
        example="SELECT * FROM orders WHERE user_id = 5"
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Optional custom database URL. Uses server default if not provided."
    )


# ─── Response Models ──────────────────────────────────────────────────────────

class RuleIssue(BaseModel):
    rule: str
    severity: str
    title: str
    detail: str
    fix_hint: str
    table: Optional[str] = None
    column: Optional[str] = None


class PlanSummary(BaseModel):
    plan_type: str
    total_cost: float
    actual_time_ms: float
    execution_time_ms: float
    planning_time_ms: float
    rows_estimated: int
    rows_actual: int


class AIAnalysis(BaseModel):
    explanation: str
    bottleneck: str
    fix_type: str
    fix_sql: str
    optimized_query: Optional[str] = None
    confidence: str
    reasoning: str


class BenchmarkSnapshot(BaseModel):
    plan_type: str
    total_cost: float
    actual_time_ms: float
    rows_scanned: int


class BenchmarkSummary(BaseModel):
    before: BenchmarkSnapshot
    after: Optional[BenchmarkSnapshot] = None
    improvement_pct: float
    cost_reduction_pct: float
    plan_changed: bool
    improvement_confirmed: bool
    summary: str
    error: Optional[str] = None


class EvaluationSummary(BaseModel):
    improvement_confirmed: bool
    original_cost: float
    optimized_cost: float
    cost_reduction_pct: float
    plan_changed: bool
    original_plan_type: str
    optimized_plan_type: str
    confidence: str
    details: list[str]
    error: Optional[str] = None


class AnalyzeResponse(BaseModel):
    query: str
    plan_summary: PlanSummary
    rule_issues: list[RuleIssue]
    ai_analysis: AIAnalysis
    benchmark: Optional[BenchmarkSummary] = None
    evaluation: Optional[EvaluationSummary] = None
    cached: bool = False
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Health Check ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    postgres: str
    redis: str
    version: str = "1.0.0"