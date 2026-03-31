"""
cli/main.py
QuerySense CLI entry point.

Usage:
    python -m cli.main analyze "SELECT * FROM orders WHERE user_id = 5"
    python -m cli.main history
    python -m cli.main --help

Or, after `pip install -e .` (with pyproject.toml entry point):
    querysense analyze "SELECT * FROM orders WHERE user_id = 5"
    querysense history
"""

import typer
from rich.console import Console
from rich.text import Text

from cli.commands.analyze import app as analyze_app
from cli.commands.history import app as history_app

console = Console()

# ── Root app ─────────────────────────────────────────────────────────────────
app = typer.Typer(
    name="querysense",
    help=(
        "QuerySense — AI-powered PostgreSQL query optimizer.\n\n"
        "Paste a slow SQL query and get a plain-English diagnosis + fix in seconds.\n\n"
        "  [bold cyan]querysense analyze[/bold cyan] \"SELECT * FROM orders WHERE user_id = 5\"\n"
        "  [bold cyan]querysense history[/bold cyan]"
    ),
    rich_markup_mode="rich",
    add_completion=False,
    no_args_is_help=True,
)

# ── Sub-commands ──────────────────────────────────────────────────────────────
app.add_typer(analyze_app, name="analyze", invoke_without_command=True)
app.add_typer(history_app, name="history", invoke_without_command=True)


# ── Version flag ──────────────────────────────────────────────────────────────
def _version_callback(value: bool) -> None:
    if value:
        console.print(Text("QuerySense v0.1.0", style="bold cyan"))
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        None, "--version", "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """QuerySense — AI-powered PostgreSQL query optimizer."""
    pass



# ── Standalone entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    app()