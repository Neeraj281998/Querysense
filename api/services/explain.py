import asyncpg
import json
import re
from typing import Any


async def run_explain_analyze(query: str, connection: asyncpg.Connection) -> dict:
    """
    Runs EXPLAIN ANALYZE on the query and returns structured result.
    """
    # Security check — only allow SELECT statements
    clean = query.strip().upper()
    if not clean.startswith("SELECT"):
        raise ValueError("Only SELECT queries are supported")

    explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"

    try:
        result = await connection.fetchval(explain_query)
        plan_json = json.loads(result)
        return parse_plan(plan_json[0])
    except asyncpg.PostgresError as e:
        raise RuntimeError(f"EXPLAIN ANALYZE failed: {str(e)}")


def parse_plan(raw: dict) -> dict:
    """
    Extracts the most useful fields from the raw EXPLAIN JSON.
    """
    plan = raw.get("Plan", {})

    return {
        "raw_plan": raw,
        "plan_type": plan.get("Node Type", "Unknown"),
        "total_cost": plan.get("Total Cost", 0),
        "actual_time_ms": plan.get("Actual Total Time", 0),
        "rows_estimated": plan.get("Plan Rows", 0),
        "rows_actual": plan.get("Actual Rows", 0),
        "shared_blocks_hit": raw.get("Shared Hit Blocks", 0),
        "shared_blocks_read": raw.get("Shared Read Blocks", 0),
        "execution_time_ms": raw.get("Execution Time", 0),
        "planning_time_ms": raw.get("Planning Time", 0),
        "nodes": extract_nodes(plan),
    }


def extract_nodes(plan: dict, depth: int = 0) -> list[dict]:
    """
    Recursively extracts all nodes from the plan tree.
    """
    nodes = []

    node = {
        "type": plan.get("Node Type", "Unknown"),
        "depth": depth,
        "cost": plan.get("Total Cost", 0),
        "actual_time_ms": plan.get("Actual Total Time", 0),
        "rows_estimated": plan.get("Plan Rows", 0),
        "rows_actual": plan.get("Actual Rows", 0),
        "relation": plan.get("Relation Name"),
        "index_name": plan.get("Index Name"),
        "join_type": plan.get("Join Type"),
        "filter": plan.get("Filter"),
        "index_cond": plan.get("Index Cond"),
    }
    nodes.append(node)

    # Recurse into child plans
    for child in plan.get("Plans", []):
        nodes.extend(extract_nodes(child, depth + 1))

    return nodes


def get_table_schema(tables: list[str], rows: list) -> str:
    """
    Formats table schema rows into a readable string for Claude.
    """
    if not rows:
        return "No schema information available."

    schema_lines = []
    current_table = None

    for row in rows:
        table_name = row["table_name"]
        if table_name != current_table:
            current_table = table_name
            schema_lines.append(f"\nTable: {table_name}")
            schema_lines.append("-" * 40)

        nullable = "NULL" if row["is_nullable"] == "YES" else "NOT NULL"
        default = f" DEFAULT {row['column_default']}" if row["column_default"] else ""
        schema_lines.append(f"  {row['column_name']:25} {row['data_type']:20} {nullable}{default}")

    return "\n".join(schema_lines)


async def get_schema_for_query(query: str, connection: asyncpg.Connection) -> str:
    """
    Extracts table names from query and fetches their schemas from Postgres.
    """
    # Simple regex to find table names after FROM and JOIN
    tables = re.findall(
        r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        query,
        re.IGNORECASE
    )
    tables = list(set(tables))  # deduplicate

    if not tables:
        return "No tables detected in query."

    placeholders = ", ".join(f"${i+1}" for i in range(len(tables)))

    rows = await connection.fetch(f"""
        SELECT
            table_name,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_name IN ({placeholders})
        AND table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """, *tables)

    # Also fetch indexes
    index_rows = await connection.fetch(f"""
        SELECT
            tablename,
            indexname,
            indexdef
        FROM pg_indexes
        WHERE tablename IN ({placeholders})
        AND schemaname = 'public'
    """, *tables)

    schema_str = get_table_schema(tables, rows)

    if index_rows:
        schema_str += "\n\nExisting Indexes:\n" + "-" * 40
        for idx in index_rows:
            schema_str += f"\n  [{idx['tablename']}] {idx['indexname']}: {idx['indexdef']}"

    return schema_str