"""`kse` command line. Quick actions and rule management arrive in M4."""

from typing import Annotated

import typer

from kse import __version__

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
