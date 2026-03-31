from dataclasses import dataclass
from typing import Optional


@dataclass
class Issue:
    rule: str
    severity: str          # "critical" | "warning" | "info"
    title: str
    detail: str
    fix_hint: str
    table: Optional[str] = None
    column: Optional[str] = None


class SequentialScanRule:
    """
    Flags sequential scans on large tables.
    A Seq Scan means Postgres is reading every single row.
    Fine for small tables, devastating for large ones.
    """
    LARGE_TABLE_ROW_THRESHOLD = 1000

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            if (
                node["type"] == "Seq Scan"
                and node["rows_actual"] > self.LARGE_TABLE_ROW_THRESHOLD
            ):
                issues.append(Issue(
                    rule="SequentialScanRule",
                    severity="critical",
                    title=f"Sequential scan on {node['relation']} ({node['rows_actual']:,} rows scanned)",
                    detail=(
                        f"Postgres scanned all {node['rows_actual']:,} rows in '{node['relation']}' "
                        f"instead of using an index. This gets exponentially worse as the table grows."
                    ),
                    fix_hint=(
                        f"Add an index on the column(s) used in your WHERE clause on '{node['relation']}'."
                    ),
                    table=node["relation"],
                ))
        return issues


class MissingIndexRule:
    """
    Detects when a filter exists on a Seq Scan node —
    meaning there's a WHERE condition but no index to serve it.
    """

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            if (
                node["type"] == "Seq Scan"
                and node.get("filter")
                and node["rows_actual"] > 500
            ):
                # Extract column name from filter string if possible
                column = self._extract_column(node["filter"])
                issues.append(Issue(
                    rule="MissingIndexRule",
                    severity="critical",
                    title=f"Missing index on filter column in '{node['relation']}'",
                    detail=(
                        f"Filter: {node['filter']}. "
                        f"Postgres is applying this filter after scanning all rows, "
                        f"not before. An index would let Postgres skip directly to matching rows."
                    ),
                    fix_hint=(
                        f"CREATE INDEX idx_{node['relation']}_{column or 'col'} "
                        f"ON {node['relation']} ({column or '<column>'});"
                    ),
                    table=node["relation"],
                    column=column,
                ))
        return issues

    def _extract_column(self, filter_str: str) -> Optional[str]:
        """Best-effort extraction of column name from filter string."""
        import re
        match = re.match(r'\(?([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>]', filter_str)
        return match.group(1) if match else None


class NestedLoopLargeTableRule:
    """
    Nested loop joins are O(n*m) — fine for small tables,
    catastrophic when both sides are large.
    """
    ROW_THRESHOLD = 10000

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            if (
                node["type"] == "Nested Loop"
                and node["rows_actual"] > self.ROW_THRESHOLD
            ):
                issues.append(Issue(
                    rule="NestedLoopLargeTableRule",
                    severity="warning",
                    title=f"Nested loop join producing {node['rows_actual']:,} rows",
                    detail=(
                        f"A nested loop join was used and produced {node['rows_actual']:,} rows. "
                        f"This is O(n×m) — each row on one side scans the other side. "
                        f"For large datasets, Hash Join or Merge Join is far more efficient."
                    ),
                    fix_hint=(
                        "Ensure join columns are indexed on both sides. "
                        "Postgres will switch to Hash Join automatically if statistics are up to date."
                    ),
                ))
        return issues


class HighCostNodeRule:
    """
    Flags any single node whose cost dominates the entire query.
    Cost is Postgres's internal estimate — not milliseconds,
    but relative units. A node costing 10000+ is worth examining.
    """
    COST_THRESHOLD = 10000

    def check(self, nodes: list[dict], total_cost: float) -> list[Issue]:
        issues = []
        for node in nodes:
            if (
                node["cost"] > self.COST_THRESHOLD
                and total_cost > 0
                and node["cost"] / total_cost > 0.5  # node is >50% of total cost
            ):
                issues.append(Issue(
                    rule="HighCostNodeRule",
                    severity="warning",
                    title=f"High cost node: {node['type']} (cost={node['cost']:,.0f})",
                    detail=(
                        f"The '{node['type']}' node accounts for most of the query cost "
                        f"({node['cost']:,.0f} out of {total_cost:,.0f} total). "
                        f"This is Postgres's estimate of how expensive this operation is."
                    ),
                    fix_hint="Focus optimization efforts on this node first.",
                ))
        return issues


class StaleStatisticsRule:
    """
    Detects when Postgres's row estimate is wildly off from reality.
    This means ANALYZE hasn't been run recently and the planner
    is making decisions based on outdated statistics.
    """
    ESTIMATION_RATIO_THRESHOLD = 10  # estimated vs actual differs by 10x

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            estimated = node["rows_estimated"]
            actual = node["rows_actual"]

            if estimated == 0 or actual == 0:
                continue

            ratio = max(estimated, actual) / min(estimated, actual)

            if ratio > self.ESTIMATION_RATIO_THRESHOLD and actual > 100:
                issues.append(Issue(
                    rule="StaleStatisticsRule",
                    severity="warning",
                    title=f"Stale statistics on '{node.get('relation', 'unknown')}' — estimate off by {ratio:.0f}x",
                    detail=(
                        f"Postgres estimated {estimated:,} rows but found {actual:,} rows "
                        f"(off by {ratio:.0f}x). This means the query planner is working with "
                        f"outdated statistics and may be choosing a suboptimal plan."
                    ),
                    fix_hint=(
                        f"Run: ANALYZE {node.get('relation', '<table>')}; "
                        f"Or: VACUUM ANALYZE {node.get('relation', '<table>')};"
                    ),
                    table=node.get("relation"),
                ))
        return issues


class MissingJoinIndexRule:
    """
    Detects Hash Join or Merge Join nodes where the join condition
    columns likely lack indexes — causing full scans on both sides.
    """

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            if (
                node["type"] in ("Hash Join", "Merge Join")
                and node["rows_actual"] > 1000
                and not node.get("index_cond")
            ):
                issues.append(Issue(
                    rule="MissingJoinIndexRule",
                    severity="warning",
                    title=f"{node['type']} on large dataset without index condition",
                    detail=(
                        f"A {node['type']} is processing {node['rows_actual']:,} rows. "
                        f"If the join columns lack indexes, Postgres must scan both full tables."
                    ),
                    fix_hint=(
                        "Add indexes on the JOIN columns for both tables involved in this join."
                    ),
                ))
        return issues


class PartialIndexOpportunityRule:
    """
    Detects filters on constant values (e.g. WHERE status = 'active')
    that are perfect candidates for partial indexes.
    A partial index only indexes rows matching the condition —
    much smaller and faster than a full index.
    """

    def check(self, nodes: list[dict]) -> list[Issue]:
        issues = []
        for node in nodes:
            if node["type"] == "Seq Scan" and node.get("filter"):
                if self._has_constant_filter(node["filter"]) and node["rows_actual"] > 500:
                    issues.append(Issue(
                        rule="PartialIndexOpportunityRule",
                        severity="info",
                        title=f"Partial index opportunity on '{node.get('relation')}'",
                        detail=(
                            f"Filter: {node['filter']}. "
                            f"This filter uses a constant value, which is ideal for a partial index. "
                            f"A partial index is smaller and faster than a full index."
                        ),
                        fix_hint=(
                            f"CREATE INDEX idx_{node.get('relation')}_partial "
                            f"ON {node.get('relation')} (<column>) WHERE {node['filter']};"
                        ),
                        table=node.get("relation"),
                    ))
        return issues

    def _has_constant_filter(self, filter_str: str) -> bool:
        """Checks if filter compares a column to a constant value."""
        import re
        return bool(re.search(r"=\s*'[^']*'|=\s*\d+", filter_str))


class RuleEngine:
    """
    Runs all rules against a parsed EXPLAIN plan.
    Returns a list of Issues sorted by severity.
    """

    SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

    def __init__(self):
        self.sequential_scan = SequentialScanRule()
        self.missing_index = MissingIndexRule()
        self.nested_loop = NestedLoopLargeTableRule()
        self.high_cost = HighCostNodeRule()
        self.stale_stats = StaleStatisticsRule()
        self.missing_join_index = MissingJoinIndexRule()
        self.partial_index = PartialIndexOpportunityRule()

    def analyze(self, parsed_plan: dict) -> list[Issue]:
        nodes = parsed_plan.get("nodes", [])
        total_cost = parsed_plan.get("total_cost", 0)

        issues = []
        issues.extend(self.sequential_scan.check(nodes))
        issues.extend(self.missing_index.check(nodes))
        issues.extend(self.nested_loop.check(nodes))
        issues.extend(self.high_cost.check(nodes, total_cost))
        issues.extend(self.stale_stats.check(nodes))
        issues.extend(self.missing_join_index.check(nodes))
        issues.extend(self.partial_index.check(nodes))

        # Sort: critical first, then warning, then info
        issues.sort(key=lambda i: self.SEVERITY_ORDER.get(i.severity, 99))

        return issues