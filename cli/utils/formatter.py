"""
cli/utils/formatter.py
All Rich-formatted terminal output for QuerySense.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich import box
from rich.rule import Rule
from rich.padding import Padding
from typing import Optional

console = Console()

# ── Colour palette ──────────────────────────────────────────────────────────
GOOD    = "green"
BAD     = "red"
WARN    = "yellow"
INFO    = "cyan"
MUTED   = "dim white"
HEADING = "bold white"
ACCENT  = "bold cyan"

# ── Confidence badge ─────────────────────────────────────────────────────────
CONFIDENCE_COLOUR = {"high": GOOD, "medium": WARN, "low": BAD}
FIX_TYPE_LABEL    = {
    "index":      "🔍 Index",
    "rewrite":    "✏️  Rewrite",
    "both":       "🔍✏️  Index + Rewrite",
    "statistics": "📊 Statistics",
}


def _badge(text: str, colour: str) -> Text:
    t = Text(f" {text} ", style=f"bold {colour} on {colour}4")
    return t


def print_header(query: str) -> None:
    """Print the opening banner with the submitted query."""
    console.print()
    console.print(Rule("[bold cyan]QuerySense[/bold cyan]", style="cyan"))
    console.print()
    query_panel = Panel(
        Text(query, style="bold white"),
        title="[dim]SQL Query[/dim]",
        border_style="dim cyan",
        padding=(0, 1),
    )
    console.print(query_panel)
    console.print()


def print_plan_summary(plan: dict) -> None:
    """Print the raw EXPLAIN ANALYZE summary metrics."""
    console.print(Rule("[bold]Execution Plan[/bold]", style="dim"))
    console.print()

    plan_type = plan.get("plan_type", "Unknown")
    colour = BAD if "Seq Scan" in plan_type else GOOD

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Metric", style="dim white", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Plan type",        Text(plan_type, style=f"bold {colour}"))
    table.add_row("Total cost",       f"{plan.get('total_cost', 0):,.2f}")
    table.add_row("Execution time",   f"{plan.get('execution_time_ms', 0):.3f} ms")
    table.add_row("Planning time",    f"{plan.get('planning_time_ms', 0):.3f} ms")
    table.add_row("Rows estimated",   f"{plan.get('rows_estimated', 0):,}")
    table.add_row("Rows actual",      f"{plan.get('rows_actual', 0):,}")

    console.print(Padding(table, (0, 2)))
    console.print()


def print_rule_issues(issues: list) -> None:
    """Print any issues flagged by the deterministic rule engine."""
    if not issues:
        console.print(
            Panel(
                Text("✓ No rule-engine issues detected", style=GOOD),
                title="[dim]Rule Engine[/dim]",
                border_style="dim green",
                padding=(0, 1),
            )
        )
        console.print()
        return

    console.print(Rule("[bold yellow]Rule Engine — Issues Detected[/bold yellow]", style="yellow"))
    console.print()
    for issue in issues:
        severity = issue.get("severity", "warning").upper()
        sev_colour = BAD if severity == "ERROR" else WARN
        rule_name  = issue.get("rule", "unknown")
        message    = issue.get("message", "")
        detail     = issue.get("detail", "")

        console.print(
            f"  [{sev_colour}]■[/{sev_colour}] [{sev_colour}]{severity}[/{sev_colour}]"
            f"  [dim]{rule_name}[/dim]"
        )
        console.print(f"    {message}")
        if detail:
            console.print(f"    [dim]{detail}[/dim]")
        console.print()


def print_ai_analysis(ai: dict) -> None:
    """Print the Claude AI diagnosis and fix recommendation."""
    console.print(Rule("[bold cyan]AI Analysis[/bold cyan]", style="cyan"))
    console.print()

    # Explanation paragraph
    explanation = ai.get("explanation", "")
    console.print(Panel(explanation, title="[dim]Explanation[/dim]", border_style="dim", padding=(0, 1)))
    console.print()

    # Bottleneck
    bottleneck = ai.get("bottleneck", "")
    console.print(f"  [bold yellow]⚠  Bottleneck:[/bold yellow]  {bottleneck}")
    console.print()

    # Fix metadata row
    fix_type   = ai.get("fix_type", "")
    confidence = ai.get("confidence", "medium")
    conf_col   = CONFIDENCE_COLOUR.get(confidence, WARN)
    fix_label  = FIX_TYPE_LABEL.get(fix_type, fix_type)

    console.print(
        f"  [dim]Fix type:[/dim]  {fix_label}    "
        f"[dim]Confidence:[/dim]  [{conf_col}]{confidence.upper()}[/{conf_col}]"
    )
    console.print()

    # Fix SQL
    fix_sql = ai.get("fix_sql", "")
    if fix_sql:
        console.print(
            Panel(
                Text(fix_sql, style="bold green"),
                title="[dim]Fix SQL[/dim]",
                border_style="green",
                padding=(0, 1),
            )
        )
        console.print()

    # Optimised query (if present)
    optimized_query = ai.get("optimized_query")
    if optimized_query:
        console.print(
            Panel(
                Text(optimized_query, style="cyan"),
                title="[dim]Optimised Query[/dim]",
                border_style="dim cyan",
                padding=(0, 1),
            )
        )
        console.print()

    # Reasoning
    reasoning = ai.get("reasoning", "")
    if reasoning:
        console.print(f"  [dim]Reasoning:[/dim] {reasoning}")
        console.print()


def print_benchmark(bench: dict) -> None:
    """Print the before/after benchmark table."""
    if not bench:
        return

    console.print(Rule("[bold green]Before vs After[/bold green]", style="green"))
    console.print()

    before = bench.get("before", {})
    after  = bench.get("after",  {})

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold white", padding=(0, 2))
    table.add_column("Metric",        style="dim white", no_wrap=True)
    table.add_column("Before",        style="red",    justify="right")
    table.add_column("After",         style="green",  justify="right")
    table.add_column("Δ",             style="bold",   justify="right")

    # Execution time
    b_time = before.get("actual_time_ms", 0)
    a_time = after.get("actual_time_ms", 0)
    imp_pct = bench.get("improvement_pct", 0)
    table.add_row(
        "Execution time",
        f"{b_time:.3f} ms",
        f"{a_time:.3f} ms",
        Text(f"↓ {imp_pct:.1f}%", style="bold green") if imp_pct > 0 else "—",
    )

    # Plan type
    b_plan = before.get("plan_type", "—")
    a_plan = after.get("plan_type",  "—")
    table.add_row(
        "Plan type",
        Text(b_plan, style="red"   if "Seq Scan" in b_plan else "white"),
        Text(a_plan, style="green" if "Seq Scan" not in a_plan else "red"),
        "→",
    )

    # Cost
    b_cost = before.get("total_cost", 0)
    a_cost = after.get("total_cost",  0)
    cost_red = bench.get("cost_reduction_pct", 0)
    table.add_row(
        "Cost estimate",
        f"{b_cost:,.2f}",
        f"{a_cost:,.2f}",
        Text(f"↓ {cost_red:.1f}%", style="bold green") if cost_red > 0 else "—",
    )

    # Rows scanned
    b_rows = before.get("rows_scanned", 0)
    a_rows = after.get("rows_scanned", 0)
    table.add_row(
        "Rows scanned",
        f"{b_rows:,}",
        f"{a_rows:,}",
        "—",
    )

    console.print(Padding(table, (0, 2)))
    console.print()

    # Summary banner
    summary = bench.get("summary", "")
    confirmed = bench.get("improvement_confirmed", False)
    banner_colour = "green" if confirmed else "yellow"
    console.print(
        Panel(
            Text(summary, style=f"bold {banner_colour}"),
            border_style=banner_colour,
            padding=(0, 1),
        )
    )
    console.print()


def print_evaluation(evl: dict) -> None:
    """Print the evaluation layer result (plan verification)."""
    if not evl:
        return

    console.print(Rule("[bold]Evaluation[/bold]", style="dim"))
    console.print()

    confirmed = evl.get("improvement_confirmed", False)
    icon = "✓" if confirmed else "✗"
    col  = GOOD if confirmed else BAD

    console.print(
        f"  [{col}]{icon}[/{col}] Improvement confirmed: [{col}]{confirmed}[/{col}]"
        f"   [{col}]Confidence: {evl.get('confidence','?').upper()}[/{col}]"
    )
    console.print()

    details = evl.get("details", [])
    for d in details:
        console.print(f"  [dim]•[/dim] {d}")
    if details:
        console.print()


def print_cached_notice() -> None:
    console.print(f"  [dim cyan]⚡ Result served from cache[/dim cyan]")
    console.print()


def print_footer(analyzed_at: Optional[str] = None) -> None:
    console.print(Rule(style="dim"))
    if analyzed_at:
        console.print(f"  [dim]Analyzed at {analyzed_at}[/dim]")
    console.print()


def print_error(message: str) -> None:
    console.print()
    console.print(
        Panel(
            Text(f"✗ {message}", style="bold red"),
            border_style="red",
            padding=(0, 1),
        )
    )
    console.print()


def print_history_table(records: list) -> None:
    """Print a table of past analyses."""
    if not records:
        console.print("\n  [dim]No history found.[/dim]\n")
        return

    console.print()
    console.print(Rule("[bold]Analysis History[/bold]", style="cyan"))
    console.print()

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold white", padding=(0, 1))
    table.add_column("#",           style="dim",        width=4,  no_wrap=True)
    table.add_column("Query",       style="white",      max_width=55)
    table.add_column("Plan",        style="white",      width=18)
    table.add_column("Improvement", style="green",      width=12, justify="right")
    table.add_column("Confidence",  style="white",      width=10)
    table.add_column("Analyzed",    style="dim white",  width=20)

    for i, r in enumerate(records, 1):
        query   = r.get("query", "")[:52] + ("…" if len(r.get("query","")) > 52 else "")
        plan    = r.get("plan_type", "—")
        imp     = r.get("improvement_pct")
        conf    = r.get("confidence", "—")
        at      = r.get("analyzed_at", "—")

        # Shorten ISO timestamp
        if "T" in at:
            at = at.replace("T", " ")[:19]

        imp_str = f"{imp:.1f}%" if imp is not None else "—"
        plan_col = "red" if "Seq Scan" in plan else "green"
        conf_col = CONFIDENCE_COLOUR.get(conf, "white")

        table.add_row(
            str(i),
            query,
            Text(plan, style=plan_col),
            Text(imp_str, style="bold green" if imp and imp > 50 else "yellow"),
            Text(conf.upper(), style=conf_col),
            at,
        )

    console.print(Padding(table, (0, 2)))
    console.print()


def format_full_response(data: dict) -> None:
    """Top-level function — render the complete /analyze response."""
    print_header(data.get("query", ""))

    if data.get("cached"):
        print_cached_notice()

    plan = data.get("plan_summary")
    if plan:
        print_plan_summary(plan)

    rule_issues = data.get("rule_issues", [])
    print_rule_issues(rule_issues)

    ai = data.get("ai_analysis")
    if ai:
        print_ai_analysis(ai)

    bench = data.get("benchmark")
    if bench:
        print_benchmark(bench)

    evl = data.get("evaluation")
    if evl:
        print_evaluation(evl)

    print_footer(data.get("analyzed_at"))