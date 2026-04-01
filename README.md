# QuerySense

**PostgreSQL query optimizer powered by a deterministic rule engine + Claude AI.**

Paste a slow SQL query. Get back in plain English: what's slow, why, and exactly how to fix it — with before/after proof in under 5 seconds.

**Live demo:** https://neeraj281998.github.io/Querysense  
**API:** https://querysense-production.up.railway.app  
**API docs:** https://querysense-production.up.railway.app/docs

---

## The Problem

`EXPLAIN ANALYZE` has existed for 30 years. It prints scary numbers and node types like `Seq Scan`, `Hash Join`, `cost=3240.00`. Most developers have no idea what it means. Existing tools (pgAdmin, TablePlus, DBngin) show the raw plan but don't explain it.

QuerySense fills this gap. It runs `EXPLAIN ANALYZE`, passes the output through a deterministic rule engine, then sends everything to Claude AI which reads it like a senior DBA would.

---

## Demo

```
$ querysense analyze "SELECT * FROM orders WHERE user_id = 5"

───────────────── QuerySense ─────────────────

  Plan type     Seq Scan
  Total cost    1,018.00
  Execution     48.211 ms
  Rows actual   6

  ■ CRITICAL  SequentialScanRule
    Sequential scan on orders (50,000 rows scanned)
    → Add an index on user_id

  AI Analysis — HIGH confidence
  The query performs a full sequential scan of 50,000 rows
  to find 6 matching rows for user_id = 5.

  Bottleneck: Missing index on user_id forces a full table scan.

  Fix SQL:
  CREATE INDEX idx_orders_user_id ON orders(user_id);

  ╭──────────────┬────────────┬──────────────────╮
  │ Metric       │   Before   │      After       │
  ├──────────────┼────────────┼──────────────────┤
  │ Exec time    │  46.8 ms   │    0.032 ms      │
  │ Plan type    │  Seq Scan  │ Bitmap Heap Scan │
  │ Cost         │  1,018.00  │    22.70         │
  │ Improvement  │            │   ↓ 98.8% faster │
  ╰──────────────┴────────────┴──────────────────╯

  ✓ Improvement confirmed — HIGH confidence
```

---

## Architecture

The key architectural decision: **the rule engine runs before Claude AI**, not after.

```
User submits SQL query
        │
        ▼
┌──────────────────┐
│   Redis Cache    │ ──── cache hit? Return instantly (free)
└──────────────────┘
        │ cache miss
        ▼
┌──────────────────┐
│  EXPLAIN ANALYZE │  Runs the query plan in Postgres
│  (asyncpg)       │  Returns cost, rows, plan nodes
└──────────────────┘
        │
        ▼
┌──────────────────┐
│   Rule Engine    │  7 deterministic rules
│   (free, fast)   │  Runs in < 1ms, always correct
│                  │  Catches: Seq Scans, missing indexes,
│                  │  nested loops, stale stats, join issues
└──────────────────┘
        │
        ▼
┌──────────────────┐
│   Claude AI      │  Reads plan + rule results
│   (Haiku)        │  Explains in plain English
│                  │  Gives exact fix SQL
└──────────────────┘
        │
        ▼
┌──────────────────┐
│   Benchmark      │  Applies fix in a test transaction
│                  │  Measures before/after timing
│                  │  Rolls back — DB never modified
└──────────────────┘
        │
        ▼
┌──────────────────┐
│   Evaluator      │  Compares plan structure (not timing)
│                  │  Confirms improvement using cost estimates
│                  │  Generates honest verdict
└──────────────────┘
        │
        ▼
  Structured JSON response
  → CLI renders with Rich
  → Web UI renders with vanilla JS
  → Saved to history in Postgres
```

Why rule engine first? Rules handle known patterns instantly — free, deterministic, always correct. Claude only runs for explanation and nuance. Every senior engineer will ask "what if the LLM is wrong?" — this answers that question.

---

## Features

- **Plain-English diagnosis** — explains what the execution plan means in 2-3 sentences
- **7-rule detection engine** — catches sequential scans, missing indexes, nested loops, stale statistics, join issues, and partial index opportunities
- **Before/after benchmarking** — proves the fix works with real numbers (98.8% improvement confirmed on test queries)
- **Evaluation layer** — applies fix in a rollback transaction, verifies the plan actually changed
- **Redis caching** — same query never hits Claude API twice
- **CLI tool** — `querysense analyze "SELECT ..."` with Rich-formatted terminal output
- **History** — every analysis saved to Postgres, browsable with `querysense history`
- **Web demo** — single-file, zero framework, professional dark UI
- **GitHub Actions CI** — runs on every push

---

## The 7 Rules

| Rule | What it detects | Severity |
|------|----------------|----------|
| `SequentialScanRule` | Full table scans on tables > 1,000 rows | Critical |
| `MissingIndexRule` | WHERE filter applied after full scan, no index | Critical |
| `NestedLoopLargeTableRule` | Nested loop join producing > 10,000 rows | Warning |
| `HighCostNodeRule` | Single node accounting for > 50% of total cost | Warning |
| `StaleStatisticsRule` | Row estimate off by > 10x from actual | Warning |
| `MissingJoinIndexRule` | Hash/Merge join without index condition | Warning |
| `PartialIndexOpportunityRule` | Filter on constant value (e.g. `status = 'active'`) | Info |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker + docker-compose
- Anthropic API key ([get one here](https://console.anthropic.com))

### 1. Clone and install

```bash
git clone https://github.com/Neeraj281998/Querysense.git
cd querysense
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```bash
ANTHROPIC_API_KEY=your_key_here
CLAUDE_MODEL=claude-haiku-4-5-20251001
DATABASE_URL=postgresql://querysense:querysense@localhost:5432/querysense
REDIS_URL=redis://localhost:6379
RATE_LIMIT_ENABLED=false
DEBUG=true
API_HOST=0.0.0.0
API_PORT=8000
```

### 3. Start infrastructure

```bash
docker-compose up -d
```

This starts Postgres 15 and Redis 7 with named volumes.

### 4. Seed the database

```bash
python scripts/seed_db.py
```

Creates an e-commerce schema with 261,010 rows and **no indexes intentionally** so QuerySense can demonstrate finding and fixing slow queries:

```
users          10,000 rows
categories         10 rows
products        1,000 rows
orders         50,000 rows   ← no index on user_id
order_items   200,000 rows   ← no index on order_id
```

### 5. Start the API

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 6. Run your first analysis

```bash
python -m cli.main analyze "SELECT * FROM orders WHERE user_id = 5"
```

Or open `web/index.html` in your browser.

---

## CLI Usage

```bash
# Analyze a query
python -m cli.main analyze "SELECT * FROM orders WHERE user_id = 5"

# Analyze with custom database
python -m cli.main analyze "SELECT * FROM orders" --db postgresql://user:pass@host/db

# Skip benchmarking (faster)
python -m cli.main analyze "SELECT * FROM orders" --no-benchmark

# View history
python -m cli.main history

# View last 50 analyses
python -m cli.main history --limit 50

# Help
python -m cli.main --help
```

---

## API Reference

**Base URL:** `https://querysense-production.up.railway.app`

### POST /api/v1/analyze

Analyze a SQL query and return a full diagnosis.

**Request:**
```json
{
  "query": "SELECT * FROM orders WHERE user_id = 5",
  "database_url": "optional — uses server default if not provided"
}
```

**Response:**
```json
{
  "query": "SELECT * FROM orders WHERE user_id = 5",
  "plan_summary": {
    "plan_type": "Seq Scan",
    "total_cost": 1018.0,
    "execution_time_ms": 48.211,
    "planning_time_ms": 10.875,
    "rows_estimated": 5,
    "rows_actual": 6
  },
  "rule_issues": [
    {
      "rule": "SequentialScanRule",
      "severity": "critical",
      "title": "Sequential scan on orders (50,000 rows scanned)",
      "detail": "Postgres scanned all 50,000 rows instead of using an index.",
      "fix_hint": "Add an index on the column(s) used in your WHERE clause."
    }
  ],
  "ai_analysis": {
    "explanation": "The query performs a full sequential scan...",
    "bottleneck": "Missing index on user_id forces a full table scan.",
    "fix_type": "index",
    "fix_sql": "CREATE INDEX idx_orders_user_id ON orders(user_id);",
    "confidence": "high",
    "reasoning": "Adding a B-tree index on user_id will allow PostgreSQL..."
  },
  "benchmark": {
    "before": { "plan_type": "Seq Scan", "actual_time_ms": 46.8, "total_cost": 1018.0 },
    "after":  { "plan_type": "Bitmap Heap Scan", "actual_time_ms": 0.032, "total_cost": 22.7 },
    "improvement_pct": 98.8,
    "cost_reduction_pct": 97.8,
    "improvement_confirmed": true,
    "summary": "Query is 98.8% faster after fix."
  },
  "evaluation": {
    "improvement_confirmed": true,
    "original_plan_type": "Seq Scan",
    "optimized_plan_type": "Bitmap Heap Scan",
    "cost_reduction_pct": 97.8,
    "confidence": "high",
    "details": [
      "Sequential scan eliminated: Seq Scan → Bitmap Heap Scan",
      "Cost estimate: 1018.00 → 22.70 (97.8% reduction)"
    ]
  },
  "cached": false,
  "analyzed_at": "2026-03-31T21:04:57.667477"
}
```

### GET /api/v1/history

Returns the most recent analyses, newest first.

```bash
GET /api/v1/history?limit=20
```

### GET /api/v1/history/{id}

Returns the full response for a single past analysis.

### GET /health

```json
{ "status": "ok", "postgres": "ok", "redis": "ok", "version": "1.0.0" }
```

---

## Demo Queries

These queries work against the seeded database and demonstrate different issues:

```sql
-- 1. Missing index (most dramatic — 98.8% improvement)
SELECT * FROM orders WHERE user_id = 5;

-- 2. Date range scan
SELECT * FROM orders WHERE created_at > '2024-01-01';

-- 3. JOIN query (detects unindexed join columns, nested loops)
SELECT o.id, u.email, SUM(oi.quantity * oi.price) AS total
FROM orders o
JOIN users u ON u.id = o.user_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.status = 'completed'
GROUP BY o.id, u.email
ORDER BY total DESC
LIMIT 10;

-- 4. GROUP BY aggregation
SELECT user_id, COUNT(*) as order_count, SUM(total) as spent
FROM orders
GROUP BY user_id
ORDER BY spent DESC
LIMIT 20;
```

---

## Project Structure

```
querysense/
│
├── api/                          # FastAPI backend
│   ├── core/
│   │   ├── config.py             # Environment variables via pydantic-settings
│   │   ├── cache.py              # Redis caching layer
│   │   ├── prompts.py            # Claude prompt templates
│   │   └── limiter.py            # Rate limiter
│   ├── db/
│   │   ├── connection.py         # asyncpg connection pool
│   │   └── history.py            # Save/retrieve analyses from Postgres
│   ├── models/
│   │   └── schemas.py            # Pydantic v2 request/response models
│   ├── routes/
│   │   ├── analyze.py            # POST /api/v1/analyze
│   │   ├── history.py            # GET /api/v1/history
│   │   └── health.py             # GET /health
│   ├── services/
│   │   ├── explain.py            # Runs EXPLAIN ANALYZE, parses output
│   │   ├── rule_engine.py        # 7 deterministic detection rules
│   │   ├── claude.py             # Claude API integration
│   │   ├── benchmark.py          # Before/after timing benchmark
│   │   └── evaluator.py          # Plan verification (rollback transaction)
│   └── main.py                   # FastAPI entry point + CORS + lifespan
│
├── cli/                          # Terminal tool
│   ├── commands/
│   │   ├── analyze.py            # querysense analyze "..."
│   │   └── history.py            # querysense history
│   ├── utils/
│   │   └── formatter.py          # Rich-formatted terminal output
│   └── main.py                   # CLI entry point (Typer)
│
├── web/
│   └── index.html                # Single-file web demo (zero framework)
│
├── scripts/
│   ├── seed_db.py                # Seeds 261K rows, no indexes intentionally
│   └── demo_queries.sql          # Pre-built slow queries for demo
│
├── tests/
│   ├── test_explain.py           # Unit tests for EXPLAIN parser
│   ├── test_rule_engine.py       # Tests for each rule
│   ├── test_api.py               # Integration tests for /analyze
│   ├── test_claude.py            # Tests with mocked Claude responses
│   └── fixtures/plans.py         # Sample EXPLAIN ANALYZE outputs
│
├── Dockerfile                    # Production container
├── railway.toml                  # Railway deployment config
├── docker-compose.yml            # Local dev — Postgres 15 + Redis 7
├── .env.example                  # Environment variable template
├── requirements.txt
└── .github/workflows/ci.yml      # GitHub Actions CI
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python 3.13 | Best ecosystem for AI/API work |
| API framework | FastAPI + asyncpg | Async, fast, auto-generates OpenAPI docs |
| AI | Claude Haiku (claude-haiku-4-5) | Fast, cheap, excellent at structured JSON output |
| Cache | Redis 7 | Same query never hits Claude API twice |
| Database | PostgreSQL 15/16 | The database we analyze |
| CLI | Typer + Rich | Clean command interface + beautiful terminal output |
| Infrastructure | Docker + docker-compose | One command dev setup |
| CI | GitHub Actions | Runs tests on every push |
| Hosting | Railway | FastAPI deployed as Docker container |
| Cloud DB | Neon.tech | Serverless Postgres, free tier |
| Cloud Cache | Upstash | Serverless Redis, free tier |
| Frontend hosting | GitHub Pages | Static HTML, zero cost |

---

## Honest Design Decisions

**QuerySense reports honestly when a fix won't help.** The evaluation layer applies the fix in a rollback transaction and checks whether the plan actually changed. If it didn't — because the query returns 99% of rows and an index wouldn't help — QuerySense says so.

Example: `SELECT * FROM orders WHERE created_at > '2024-01-01'` returns 50,000 of 50,000 rows. Claude correctly recommends an index. The evaluator correctly reports no improvement because Postgres ignores the index when selectivity is near 100%. The tool doesn't lie to make itself look better.

---

## Running Tests

```bash
# All tests (uses mocked Claude — no real API calls)
pytest tests/ -v

# Specific test files
pytest tests/test_rule_engine.py -v
pytest tests/test_explain.py -v
pytest tests/test_api.py -v

# Claude tests (mocked)
pytest tests/test_claude.py -v
```

---

## Deployment

### Infrastructure

| Service | Provider | Cost |
|---------|----------|------|
| FastAPI API | Railway | $0 (free credits) |
| PostgreSQL | Neon.tech | $0 (free tier) |
| Redis | Upstash | $0 (free tier) |
| Frontend | GitHub Pages | $0 |
| **Total** | | **$0** |

### Deploy your own

1. Fork this repo
2. Create accounts on [Railway](https://railway.app), [Neon.tech](https://neon.tech), [Upstash](https://upstash.com)
3. Get your Neon and Upstash connection strings
4. Create a Railway project → Deploy from GitHub
5. Add environment variables in Railway (see Environment Variables section below)
6. Seed your Neon database:

```bash
DATABASE_URL=your_neon_url python scripts/seed_db.py
```

7. Enable GitHub Pages on the `web/` folder for the frontend

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | Required |
| `CLAUDE_MODEL` | Claude model to use | `claude-haiku-4-5-20251001` |
| `DATABASE_URL` | Postgres connection string | Required |
| `REDIS_URL` | Redis connection string (use `rediss://` for Upstash) | Required |
| `RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `RATE_LIMIT_PER_DAY` | Requests per IP per day | `5` |
| `DEBUG` | Debug mode | `false` |
| `API_HOST` | API host | `0.0.0.0` |
| `API_PORT` | API port | `8000` |

---

## Portfolio Context

QuerySense is the third project in a portfolio that demonstrates progressively deeper systems knowledge:

- **JavaMem** — visualizes Java memory (Stack, Heap, String Pool). Shows JVM internals knowledge.
- **SQLMem** — visualizes MySQL query execution step by step. Shows SQL internals knowledge.
- **QuerySense** — uses that SQL knowledge + AI to help engineers fix slow queries. Shows AI integration + production deployment.

---

## License

MIT
