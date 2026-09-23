"""`kse` command line. Quick actions and rule management arrive in M4."""

import asyncio
import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from kse import __version__
from kse.doctor import collect
from kse.i18n import _
from kse.platform import dry_run_requested, get_backend

app = typer.Typer(
    name="kse",
    help="KShutdown Evolution: power and task automation driven by persistent rules.",
    no_args_is_help=True,
    add_completion=False,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"kse {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """KShutdown Evolution: power and task automation driven by persistent rules."""


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Check what works on this machine and how to fix what does not."""
    backend = get_backend()
    name = backend.name
    capabilities = asyncio.run(collect(backend))
    if as_json:
        typer.echo(json.dumps([c.model_dump() for c in capabilities], indent=2, ensure_ascii=False))
        return
    console = Console()
    console.print(f"[bold]kse {__version__}[/] · backend [bold]{name}[/]")
    if dry_run_requested():
        console.print(_("[yellow]Dry run:[/] power actions and wake alarms are only logged."))
    table = Table(show_lines=False, header_style="bold")
    table.add_column("", width=1)
    table.add_column(_("Capability"), no_wrap=True)
    table.add_column(_("Detail"))
    table.add_column(_("How to fix"))
    for capability in capabilities:
        mark = "[green]✔[/]" if capability.supported else "[red]✘[/]"
        table.add_row(mark, capability.id, capability.detail, capability.fix_hint or "")
    console.print(table)
