import json
import anthropic
from api.core.config import get_settings
from api.core.prompts import EXPLAIN_ANALYSIS_PROMPT, build_prompt

settings = get_settings()

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def analyze_with_claude(
    query: str,
    parsed_plan: dict,
    schema: str,
    known_issues: list,
) -> dict:
    """
    Sends the execution plan + schema + known issues to Claude.
    Returns structured JSON diagnosis.
    """
    user_prompt = build_prompt(
        query=query,
        plan_summary=parsed_plan,
        schema=schema,
        known_issues=known_issues,
    )

    try:
        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=EXPLAIN_ANALYSIS_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
        )

        raw_text = message.content[0].text.strip()
        return _parse_claude_response(raw_text)

    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude API connection failed: {str(e)}")
    except anthropic.RateLimitError:
        raise RuntimeError("Claude API rate limit reached. Try again in a moment.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error {e.status_code}: {e.message}")


def _parse_claude_response(raw: str) -> dict:
    """
    Parses Claude's JSON response.
    Handles cases where Claude wraps output in markdown code blocks.
    """
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude returned invalid JSON: {str(e)}\nRaw: {raw[:200]}")

    # Validate required fields are present
    required = ["explanation", "bottleneck", "fix_type", "fix_sql", "confidence"]
    missing = [f for f in required if f not in data]
    if missing:
        raise RuntimeError(f"Claude response missing fields: {missing}")

    return {
        "explanation": data.get("explanation", ""),
        "bottleneck": data.get("bottleneck", ""),
        "fix_type": data.get("fix_type", "index"),
        "fix_sql": data.get("fix_sql", ""),
        "optimized_query": data.get("optimized_query"),
        "confidence": data.get("confidence", "medium"),
        "reasoning": data.get("reasoning", ""),
    }


import json
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClaudeResponse:
    explanation: str
    bottleneck: str
    fix_type: str        # "index" | "rewrite" | "both" | "statistics"
    fix_sql: str
    confidence: str      # "high" | "medium" | "low"
    reasoning: str
    optimized_query: Optional[str] = None


def parse_claude_response(raw_text: str) -> ClaudeResponse:
    """Parse the JSON string Claude returns into a ClaudeResponse."""
    text = raw_text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    data = json.loads(text)  # raises json.JSONDecodeError if invalid

    # Validate required fields
    required = {"explanation", "bottleneck", "fix_type", "fix_sql", "confidence"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Claude response missing required fields: {missing}")

    return ClaudeResponse(
        explanation=data["explanation"],
        bottleneck=data["bottleneck"],
        fix_type=data["fix_type"],
        fix_sql=data["fix_sql"],
        confidence=data["confidence"],
        reasoning=data.get("reasoning", ""),
        optimized_query=data.get("optimized_query"),
    )


def build_prompt_context(
    query: str,
    plan_summary: dict,
    schema: str,
    rule_issues: list[dict],
) -> str:
    """Assemble the user message content sent to Claude."""
    issues_text = (
        json.dumps(rule_issues, indent=2)
        if rule_issues
        else "None detected."
    )
    return f"""SQL Query:
{query}

Table Schema:
{schema}

EXPLAIN Plan Summary:
- Top node: {plan_summary.get('top_node_type')}
- Total cost: {plan_summary.get('total_cost')}
- Execution time: {plan_summary.get('execution_time_ms')} ms
- Sequential scans on: {plan_summary.get('seq_scan_tables')}
- Has nested loop: {plan_summary.get('has_nested_loop')}

Rule Engine Findings:
{issues_text}
"""


class ClaudeService:
    """Thin wrapper around the Anthropic client — testable and mockable."""

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def analyze(
        self,
        query: str,
        plan_summary: dict,
        schema: str,
        rule_issues: list[dict],
    ) -> ClaudeResponse:
        from api.core.prompts import EXPLAIN_ANALYSIS_PROMPT
        from api.core.config import settings

        user_content = build_prompt_context(query, plan_summary, schema, rule_issues)

        message = self._client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=EXPLAIN_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = message.content[0].text
        return parse_claude_response(raw_text)