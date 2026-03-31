EXPLAIN_ANALYSIS_PROMPT = """
You are a senior database administrator with 15 years of experience optimizing
PostgreSQL queries in high-traffic production systems.

You will be given:
1. A SQL query
2. The EXPLAIN ANALYZE output (execution plan)
3. The relevant table schemas
4. Known issues already detected by our rule engine (may be empty)

Your job is to:
1. Explain in plain English what the execution plan means (2-3 sentences max)
2. Identify the PRIMARY bottleneck (the single biggest performance problem)
3. Give ONE specific, actionable fix (index creation, query rewrite, or both)
4. Provide the exact SQL for the fix

Rules:
- Be specific. Never say "consider adding an index" — say exactly which index on which table and column
- If the rule engine already found issues, confirm or correct them, do not repeat them verbatim
- If you see multiple problems, fix the worst one only
- Output ONLY valid JSON matching the schema below — no preamble, no markdown, no explanation outside the JSON

Output schema:
{
  "explanation": "plain English explanation of what the plan shows (2-3 sentences)",
  "bottleneck": "the single biggest performance problem in one sentence",
  "fix_type": "index" | "rewrite" | "both" | "statistics",
  "fix_sql": "exact SQL to run — must be copy-pasteable",
  "optimized_query": "rewritten query if applicable, else null",
  "confidence": "high" | "medium" | "low",
  "reasoning": "why this specific fix will work"
}
"""


def build_prompt(
    query: str,
    plan_summary: dict,
    schema: str,
    known_issues: list,
) -> str:
    """
    Builds the full prompt to send to Claude.
    Combines the system context with the specific query details.
    """

    issues_text = ""
    if known_issues:
        issues_text = "\n\nKnown issues detected by rule engine:\n"
        for issue in known_issues:
            issues_text += (
                f"- [{issue.severity.upper()}] {issue.title}\n"
                f"  Detail: {issue.detail}\n"
                f"  Suggested fix: {issue.fix_hint}\n"
            )
    else:
        issues_text = "\n\nKnown issues detected by rule engine: None detected."

    prompt = f"""
SQL Query:
{query}

Execution Plan Summary:
- Plan type: {plan_summary.get('plan_type')}
- Total cost: {plan_summary.get('total_cost')}
- Actual execution time: {plan_summary.get('actual_time_ms')} ms
- Rows estimated: {plan_summary.get('rows_estimated')}
- Rows actual: {plan_summary.get('rows_actual')}
- Planning time: {plan_summary.get('planning_time_ms')} ms

Node breakdown:
{_format_nodes(plan_summary.get('nodes', []))}

Table Schema:
{schema}
{issues_text}

Respond with valid JSON only. No markdown. No preamble.
"""
    return prompt


def _format_nodes(nodes: list) -> str:
    if not nodes:
        return "  No nodes available."

    lines = []
    for node in nodes:
        indent = "  " * node.get("depth", 0)
        relation = f" on '{node['relation']}'" if node.get("relation") else ""
        index = f" using '{node['index_name']}'" if node.get("index_name") else ""
        lines.append(
            f"{indent}- {node['type']}{relation}{index} "
            f"(cost={node['cost']:.1f}, actual={node['actual_time_ms']:.2f}ms, "
            f"rows estimated={node['rows_estimated']}, actual={node['rows_actual']})"
        )
        if node.get("filter"):
            lines.append(f"{indent}  filter: {node['filter']}")
        if node.get("index_cond"):
            lines.append(f"{indent}  index cond: {node['index_cond']}")

    return "\n".join(lines)