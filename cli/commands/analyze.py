"""
cli/commands/analyze.py
The `querysense analyze` command — calls /analyze, prints formatted result.
"""

import sys
import httpx
import typer
from typing import Optional

from cli.utils.formatter import console, format_full_response, print_error

app = typer.Typer(help="Analyze a SQL query and get AI-powered optimization advice.")

DEFAULT_API_URL = "http://localhost:8000"


def _api_url(ctx: typer.Context) -> str:
    return ctx.obj.get("api_url", DEFAULT_API_URL) if ctx.obj else DEFAULT_API_URL


@app.callback(invoke_without_command=True)
def analyze(
    ctx: typer.Context,
    query: str = typer.Argument(..., help='SQL query to analyze, e.g. "SELECT * FROM orders WHERE user_id = 5"'),
    database_url: Optional[str] = typer.Option(
        None, "--db", "-d",
        envvar="DATABASE_URL",
        help="Postgres connection string (overrides .env)",
        show_default=False,
    ),
    no_benchmark: bool = typer.Option(
        False, "--no-benchmark",
        help="Skip before/after benchmarking (faster)",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache",
        help="Bypass Redis cache and force a fresh analysis",
    ),
    api_url: str = typer.Option(
        DEFAULT_API_URL, "--api",
        envvar="QUERYSENSE_API_URL",
        help="QuerySense API base URL",
    ),
    timeout: int = typer.Option(
        60, "--timeout", "-t",
        help="Request timeout in seconds",
    ),
) -> None:
    """
    Analyze a PostgreSQL query and print a plain-English optimization report.

    Examples:\n
      querysense analyze "SELECT * FROM orders WHERE user_id = 5"\n
      querysense analyze "SELECT * FROM orders" --no-benchmark\n
      querysense analyze "SELECT * FROM orders" --db postgresql://user:pass@localhost/mydb
    """
    payload: dict = {"query": query}
    if database_url:
        payload["database_url"] = database_url
    if no_benchmark:
        payload["skip_benchmark"] = True
    if no_cache:
        payload["skip_cache"] = True

    endpoint = f"{api_url.rstrip('/')}/api/v1/analyze"

    with console.status("[cyan]Analyzing query…[/cyan]", spinner="dots"):
        try:
            response = httpx.post(endpoint, json=payload, timeout=timeout)
        except httpx.ConnectError:
            print_error(
                f"Cannot connect to QuerySense API at {api_url}.\n"
                "  Make sure the server is running:  uvicorn api.main:app --port 8000"
            )
            raise typer.Exit(code=1)
        except httpx.TimeoutException:
            print_error(f"Request timed out after {timeout}s. Try --timeout 120.")
            raise typer.Exit(code=1)
        except httpx.RequestError as exc:
            print_error(f"Request failed: {exc}")
            raise typer.Exit(code=1)

    if response.status_code == 429:
        print_error("Rate limit exceeded. Try again later or run your own instance.")
        raise typer.Exit(code=1)

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print_error(f"API error {response.status_code}: {detail}")
        raise typer.Exit(code=1)

    try:
        data = response.json()
    except Exception as exc:
        print_error(f"Failed to parse API response: {exc}")
        raise typer.Exit(code=1)

    format_full_response(data)