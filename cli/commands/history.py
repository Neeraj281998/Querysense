"""
cli/commands/history.py
The `querysense history` command — lists past analyses stored in the DB.
"""

import httpx
import typer
from typing import Optional

from cli.utils.formatter import console, print_history_table, print_error

app = typer.Typer(help="Browse past QuerySense analyses.")

DEFAULT_API_URL = "http://localhost:8000"


@app.callback(invoke_without_command=True)
def history(
    ctx: typer.Context,
    limit: int = typer.Option(
        20, "--limit", "-n",
        help="Number of records to show",
        min=1,
        max=100,
    ),
    api_url: str = typer.Option(
        DEFAULT_API_URL, "--api",
        envvar="QUERYSENSE_API_URL",
        help="QuerySense API base URL",
    ),
    timeout: int = typer.Option(30, "--timeout", "-t", help="Request timeout in seconds"),
) -> None:
    """
    Show the most recent query analyses.

    Examples:\n
      querysense history\n
      querysense history --limit 50
    """
    endpoint = f"{api_url.rstrip('/')}/api/v1/history"

    with console.status("[cyan]Fetching history…[/cyan]", spinner="dots"):
        try:
            response = httpx.get(endpoint, params={"limit": limit}, timeout=timeout)
        except httpx.ConnectError:
            print_error(
                f"Cannot connect to QuerySense API at {api_url}.\n"
                "  Make sure the server is running:  uvicorn api.main:app --port 8000"
            )
            raise typer.Exit(code=1)
        except httpx.RequestError as exc:
            print_error(f"Request failed: {exc}")
            raise typer.Exit(code=1)

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        print_error(f"API error {response.status_code}: {detail}")
        raise typer.Exit(code=1)

    try:
        records = response.json()  # expects a list of history dicts
    except Exception as exc:
        print_error(f"Failed to parse API response: {exc}")
        raise typer.Exit(code=1)

    print_history_table(records)