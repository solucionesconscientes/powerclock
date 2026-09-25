"""`powerclock` command line: quick actions, rules, status and the daemon service.

Everything except `doctor` and `service` talks to the daemon's local API.
"""

import asyncio
import contextlib
import getpass
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, NoReturn

import click
import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from powerclock import __version__, recipes
from powerclock.cli import client as api
from powerclock.cli.format import local, relative, span, trigger, watch_detail
from powerclock.config import Paths
from powerclock.doctor import WakeTest, collect, run_wake_test, verdict_message
from powerclock.i18n import _
from powerclock.install.helper import helper_module
from powerclock.install.program import commands as program_commands
from powerclock.install.program import latest_version, newer
from powerclock.install.service import service_module
from powerclock.install.steps import Options, Report, Setup
from powerclock.labels import reason_label
from powerclock.platform import dry_run_requested, get_backend
from powerclock.platform.base import NotSupported, PowerAction

app = typer.Typer(
    name="powerclock",
    help="PowerClock: power and task automation driven by persistent rules.",
    no_args_is_help=True,
    add_completion=False,
)
rules_app = typer.Typer(help="Manage rules.", no_args_is_help=True)
service_app = typer.Typer(help="Run the daemon as a service of your user.", no_args_is_help=True)
helper_app = typer.Typer(
    help="The root helper that programs wake-ups (installed once with sudo).",
    no_args_is_help=True,
)
app.add_typer(rules_app, name="rules")
app.add_typer(service_app, name="service")
app.add_typer(helper_app, name="helper")

console = Console()
errors = Console(stderr=True)

HANDS_OFF = 10  # seconds between confirming a wake test and suspending

STATE_STYLES = {
    "done": "green",
    "failed": "red",
    "cancelled": "yellow",
    "skipped": "dim",
    "warning": "bold yellow",
    "postponed": "yellow",
}


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"powerclock {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Quick actions only log their power actions.")
    ] = False,
) -> None:
    """PowerClock: power and task automation driven by persistent rules."""
    ctx.obj = {"dry_run": dry_run}


@contextlib.contextmanager
def _daemon() -> Iterator[api.Client]:
    """A client of the daemon; its errors become a message and exit code 1."""
    try:
        yield api.connect()
    except api.DaemonUnavailable as exc:
        errors.print(f"[red]✘[/] {escape(str(exc))}")
        errors.print(_("Start it with: powerclock service install   (or run: powerclock-daemon)"))
        raise typer.Exit(1) from None
    except api.ApiError as exc:
        errors.print(f"[red]✘[/] {escape(str(exc))}")
        raise typer.Exit(1) from None


def _fail(message: str) -> NoReturn:
    errors.print(f"[red]✘[/] {escape(message)}")
    raise typer.Exit(1)


def _styled(state: str) -> str:
    style = STATE_STYLES.get(state)
    return f"[{style}]{state}[/]" if style else state


# ── Quick actions ──────────────────────────────────────────────────────────────

InOption = Annotated[str | None, typer.Option("--in", help="After a delay: 30s, 5m, 2h, 1h30m.")]
AtOption = Annotated[
    str | None, typer.Option("--at", help="At a time: 23:30 or '2026-09-24 07:30'.")
]
WhenIdleOption = Annotated[
    str | None,
    typer.Option("--when-idle", help="When nobody has used the computer for this long: 20m."),
]
WhenExitsOption = Annotated[
    str | None,
    typer.Option("--when-exits", help="When this program ends (a process name or a PID)."),
]
WhenCpuOption = Annotated[
    float | None,
    typer.Option("--when-cpu-below", help="When the average CPU usage stays below this %."),
]
WhenNetOption = Annotated[
    float | None,
    typer.Option("--when-net-below", help="When network traffic stays below this many kbit/s."),
]
ForOption = Annotated[
    str | None,
    typer.Option("--for", help="How long CPU or network must stay below (default: 5m)."),
]
LogInOption = Annotated[
    bool,
    typer.Option(
        "--log-in",
        help="With --wake: log in once when that turns the computer on (screen locked).",
    ),
]


def _when(
    payload: dict[str, Any],
    in_: str | None,
    at: str | None,
    when_idle: str | None,
    when_exits: str | None,
    when_cpu_below: float | None,
    when_net_below: float | None,
    for_: str | None,
) -> dict[str, Any]:
    """Add the chosen moment (--in, --at or --when-*) to a /quick request."""
    options = {
        "in": in_,
        "at": at,
        "when_idle": when_idle,
        "when_exits": when_exits,
        "when_cpu_below": when_cpu_below,
        "when_net_below": when_net_below,
        "for": for_,
    }
    payload.update({key: value for key, value in options.items() if value is not None})
    return payload


def _quick(ctx: typer.Context, payload: dict[str, Any]) -> None:
    payload["dry_run"] = bool(ctx.obj and ctx.obj.get("dry_run"))
    with _daemon() as client:
        rule = client.post("/quick", json=payload)
        pending = client.get("/pending")
    when = next((p["at"] for p in pending["next"] if p["rule_id"] == rule["id"]), None)
    line = f"[green]✔[/] {rule['name']}"
    if when:
        line += f" — {local(when)} ({relative(when)})"
    console.print(line)
    watched = rule["trigger"]["type"] not in ("at", "countdown", "manual")
    if watched:
        _show_watch(rule["id"])
    if rule.get("wake") or payload.get("wake_at"):
        _show_wake()
    hint = (
        _("  cancel: powerclock cancel")
        if watched
        else _("  cancel: powerclock cancel · postpone: powerclock postpone 10m")
    )
    console.print(hint, style="dim")


def _show_watch(rule_id: str, wait: float = 3.0) -> None:
    """The daemon checks a new condition right away: show what it sees."""
    deadline = time.monotonic() + wait
    with _daemon() as client:
        while True:
            watching = client.get("/pending")["watching"]
            item = next((w for w in watching if w["rule_id"] == rule_id), None)
            if item is None or item["checked_at"] or time.monotonic() > deadline:
                break
            time.sleep(0.2)
    if item is not None and item["checked_at"]:
        console.print(f"  👁 {watch_detail(item)}")


def _show_wake(wait: float = 3.0) -> None:
    """The planner programs the alarm right after a change: show its result."""
    deadline = time.monotonic() + wait
    with _daemon() as client:
        while True:
            wake = client.get("/pending")["wake"]
            if wake["at"] or wake["error"] or time.monotonic() > deadline:
                break
            time.sleep(0.2)
    if wake["error"]:
        console.print(f"  [red]✘ {_('wake-up alarm')}:[/] {wake['error']}")
    elif wake["at"]:
        console.print(f"  ⏰ {_('wake-up alarm')}: {local(wake['at'])} ({relative(wake['at'])})")


@app.command("wake")
def wake_command(
    at: Annotated[str, typer.Option("--at", help="23:30 or '2026-09-24 07:30'.")],
    log_in: Annotated[
        bool,
        typer.Option("--log-in", help="Log in once if this turns the computer on (screen locked)."),
    ] = False,
) -> None:
    """Wake the computer up (from suspend, or from off if the firmware allows it)."""
    body: dict[str, Any] = {"at": at}
    if log_in:
        body["log_in"] = "locked"
    with _daemon() as client:
        rule = client.post("/wake", json=body)
    console.print(f"[green]✔[/] {rule['name']}")
    _show_wake()


def _power_command(action: PowerAction) -> Callable[..., None]:
    def command(
        ctx: typer.Context,
        in_: InOption = None,
        at: AtOption = None,
        when_idle: WhenIdleOption = None,
        when_exits: WhenExitsOption = None,
        when_cpu_below: WhenCpuOption = None,
        when_net_below: WhenNetOption = None,
        for_: ForOption = None,
        force: Annotated[
            bool, typer.Option("--force", help="Do not let applications ask to save.")
        ] = False,
        warning: Annotated[
            str, typer.Option("--warning", help="Cancellable countdown before acting.")
        ] = "60s",
        wake: Annotated[
            str | None,
            typer.Option("--wake", help="Also wake the computer up at this time (07:30)."),
        ] = None,
        log_in: LogInOption = False,
    ) -> None:
        payload: dict[str, Any] = {
            "action": action.value,
            "mode": "force" if force else "graceful",
            "warning": warning,
        }
        if wake:
            payload["wake_at"] = wake
        if log_in:
            payload["log_in"] = "locked"
        _when(payload, in_, at, when_idle, when_exits, when_cpu_below, when_net_below, for_)
        _quick(ctx, payload)

    return command


# The help of the CLI is in English (typer docstrings); the action names follow it.
HELP_NAMES = {
    PowerAction.SHUTDOWN: "Shut down",
    PowerAction.REBOOT: "Restart",
    PowerAction.SUSPEND: "Suspend",
    PowerAction.HIBERNATE: "Hibernate",
    PowerAction.HYBRID_SLEEP: "Hybrid sleep (suspend + hibernate)",
    PowerAction.LOCK: "Lock the screen",
    PowerAction.LOGOUT: "Log out",
    PowerAction.SCREEN_OFF: "Turn off the screen",
}

for _action in PowerAction:
    app.command(
        name=_action.value.replace("_", "-"),
        help=(
            f"{HELP_NAMES[_action]}: now, after a delay (--in), at a time (--at) "
            "or when a condition is met (--when-idle, --when-exits, --when-cpu-below, "
            "--when-net-below)."
        ),
    )(_power_command(_action))


@app.command("run")
def run_command(
    ctx: typer.Context,
    command: Annotated[list[str], typer.Argument(help="The program and its arguments, after --.")],
    in_: InOption = None,
    at: AtOption = None,
    when_idle: WhenIdleOption = None,
    when_exits: WhenExitsOption = None,
    when_cpu_below: WhenCpuOption = None,
    when_net_below: WhenNetOption = None,
    for_: ForOption = None,
    wake: Annotated[
        bool, typer.Option("--wake", help="Wake the computer up to run it (needs --in/--at).")
    ] = False,
    log_in: LogInOption = False,
) -> None:
    """Run a program now, after a delay, at a time or when a condition is met:
    powerclock run --at 03:00 --wake -- backup.sh"""
    payload: dict[str, Any] = {"command": command, "wake": wake}
    if log_in:
        payload["log_in"] = "locked"
    _when(payload, in_, at, when_idle, when_exits, when_cpu_below, when_net_below, for_)
    _quick(ctx, payload)


@app.command("launch")
def launch_command(
    ctx: typer.Context,
    app_id: Annotated[str, typer.Argument(metavar="APP", help="Its id: see powerclock apps.")],
    args: Annotated[
        list[str] | None, typer.Argument(help="Files, web addresses or options, after --.")
    ] = None,
    recipe: Annotated[
        str | None,
        typer.Option("--recipe", help="Fill the arguments from a recipe: see powerclock recipes."),
    ] = None,
    in_: InOption = None,
    at: AtOption = None,
    when_idle: WhenIdleOption = None,
    when_exits: WhenExitsOption = None,
    when_cpu_below: WhenCpuOption = None,
    when_net_below: WhenNetOption = None,
    for_: ForOption = None,
    wake: Annotated[
        bool, typer.Option("--wake", help="Wake the computer up to open it (needs --in/--at).")
    ] = False,
    log_in: LogInOption = False,
) -> None:
    """Open an installed application now, after a delay, at a time or when a condition is
    met: powerclock launch org.kde.okular --at 09:00 -- ~/informe.pdf"""
    arguments = list(args or [])
    if recipe is not None:
        found = recipes.get(recipe)
        if found is None:
            _fail(_("There is no recipe {recipe!r}: see powerclock recipes.").format(recipe=recipe))
        arguments = [*_fill_inputs(found, arguments), *arguments[len(found.inputs) :]]
    payload: dict[str, Any] = {"app": app_id, "args": arguments, "wake": wake}
    if log_in:
        payload["log_in"] = "locked"
    _when(payload, in_, at, when_idle, when_exits, when_cpu_below, when_net_below, for_)
    _quick(ctx, payload)


def _fill_inputs(recipe: recipes.Recipe, values: list[str]) -> list[str]:
    """A recipe's arguments, its <inputs> taken in order from the command line."""
    keys = list(recipe.inputs)
    if len(values) < len(keys):
        wanted = ", ".join(f"<{key}>" for key in keys)
        _fail(_("The recipe {recipe} needs: {inputs}").format(recipe=recipe.id, inputs=wanted))
    return recipe.fill(dict(zip(keys, values, strict=False)))


@app.command("apps")
def apps_command(
    search: Annotated[str | None, typer.Argument(help="Part of its name or id.")] = None,
) -> None:
    """The installed applications that launch can open, with their recipes."""
    with _daemon() as client:
        found = client.get("/apps")
    if search:
        needle = search.lower()
        found = [a for a in found if needle in a["name"].lower() or needle in a["id"].lower()]
    table = Table(header_style="bold")
    for column in (_("Name"), _("Id"), _("Recipes")):
        table.add_column(column)
    for item in found:
        name = escape(item["name"]) + (" [dim](Flatpak)[/]" if item.get("flatpak") else "")
        table.add_row(name, escape(item["id"]), escape(", ".join(item.get("recipes", []))))
    console.print(table)


@app.command("recipes")
def recipes_command(
    app_id: Annotated[str | None, typer.Argument(metavar="APP", help="Only this app's.")] = None,
) -> None:
    """Ready-made arguments for common applications (use them with launch --recipe)."""
    found = recipes.for_app(app_id) if app_id else list(recipes.recipes())
    table = Table(header_style="bold", show_lines=True)
    for column in (_("Recipe"), _("What it does"), _("Arguments")):
        table.add_column(column)
    for recipe in found:
        table.add_row(recipe.id, escape(recipe.title()), escape(" ".join(recipe.args)))
    console.print(table)


# ── Status, cancel, postpone, history ──────────────────────────────────────────


@app.command()
def status() -> None:
    """What the daemon is doing and what comes next."""
    with _daemon() as client:
        health = client.get("/health")
        pending = client.get("/pending")
    console.print(
        f"[bold]powerclock {health['version']}[/] · {health['backend']} · {health['timezone']}"
        f" · {_('running for')} {span(health['uptime'])}"
    )
    if health["dry_run"]:
        console.print(
            _("[yellow]Test mode:[/] nothing really turns off or on; actions are only noted down.")
        )
    for problem in health["rules_errors"]:
        console.print(f"[red]✘ rules.json:[/] {problem}")
    wake = pending["wake"]
    if wake["error"]:
        console.print(f"[red]✘ {_('wake-up alarm')}:[/] {wake['error']}")
    elif wake["at"]:
        console.print(f"⏰ {_('wake-up alarm')}: {local(wake['at'])} ({relative(wake['at'])})")
    active, upcoming, watching = pending["active"], pending["next"], pending["watching"]
    if active:
        table = Table(title=_("Running"), title_justify="left", header_style="bold")
        for column in (_("Rule"), _("State"), _("Detail"), _("Run")):
            table.add_column(column)
        for run in active:
            detail = (
                _("acts {when}").format(when=relative(run["deadline"]))
                if run.get("deadline")
                else escape(reason_label(run.get("reason")))
            )
            table.add_row(escape(run["rule_name"]), _styled(run["state"]), detail, run["id"])
        console.print(table)
    if upcoming:
        table = Table(title=_("Next"), title_justify="left", header_style="bold")
        for column in (_("When"), _("In"), _("Rule"), _("Id")):
            table.add_column(column)
        for item in upcoming:
            table.add_row(local(item["at"]), relative(item["at"]), item["name"], item["rule_id"])
        console.print(table)
    if watching:
        table = Table(title=_("Watching"), title_justify="left", header_style="bold")
        for column in (_("Rule"), _("Now"), _("Id")):
            table.add_column(column)
        for item in watching:
            table.add_row(item["name"], watch_detail(item), item["rule_id"])
        console.print(table)
    if not active and not upcoming and not watching:
        console.print(_("Nothing scheduled."))


@app.command()
def cancel(
    run_id: Annotated[
        str | None,
        typer.Argument(
            help="A run id (see powerclock status); default: the countdown or quick action."
        ),
    ] = None,
) -> None:
    """Cancel the countdown in progress or the next quick action."""
    with _daemon() as client:
        result = client.post(f"/runs/{run_id}/cancel") if run_id else client.post("/cancel")
    console.print(f"[green]✔[/] {_('Cancelled')}: {result.get('name') or result['rule_id']}")


@app.command()
def postpone(
    delay: Annotated[str, typer.Argument(help="How long: 10m, 1h…")] = "10m",
    run_id: Annotated[str | None, typer.Option("--run", help="A specific run.")] = None,
) -> None:
    """Postpone the countdown in progress or the next quick action."""
    with _daemon() as client:
        path = f"/runs/{run_id}/postpone" if run_id else "/postpone"
        result = client.post(path, json={"delay": delay})
    console.print(
        f"[green]✔[/] {_('Postponed')}: {result.get('name')} → "
        f"{local(result.get('at'))} ({relative(result.get('at'))})"
    )


@app.command()
def history(
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many runs.")] = 20,
    rule_id: Annotated[str | None, typer.Option("--rule", help="Only this rule.")] = None,
) -> None:
    """Past runs: done, failed, cancelled, skipped… and why."""
    params: dict[str, Any] = {"limit": limit}
    if rule_id:
        params["rule_id"] = rule_id
    with _daemon() as client:
        data = client.get("/history", params=params)
    if not data["runs"]:
        console.print(_("No runs yet."))
        return
    table = Table(header_style="bold")
    for column in (_("Finished"), _("Rule"), _("State"), _("Reason")):
        table.add_column(column)
    for run in data["runs"]:
        table.add_row(
            local(run["finished_at"]),
            escape(run["rule_name"]),
            _styled(run["state"]),
            escape(reason_label(run["reason"])),
        )
    console.print(table)
    console.print(
        _("{shown} of {total} runs").format(shown=len(data["runs"]), total=data["total"]),
        style="dim",
    )


# ── Rules ──────────────────────────────────────────────────────────────────────


def _read_rules(file: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{file}: {exc}")
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return list(data["rules"])
    if isinstance(data, list):
        return data
    return [data]


@rules_app.command("list")
def rules_list() -> None:
    """All rules and when they fire next."""
    with _daemon() as client:
        rules = client.get("/rules")
        pending = client.get("/pending")
    upcoming = {item["rule_id"]: item["at"] for item in pending["next"]}
    watched = {item["rule_id"]: item for item in pending["watching"]}
    if not rules:
        console.print(_("No rules yet: powerclock rules add FILE.json (see examples/)."))
        return
    table = Table(header_style="bold")
    for column in (_("Id"), _("Name"), _("When"), _("On"), _("Next")):
        table.add_column(column)
    for rule in rules:
        when, watch = upcoming.get(rule["id"]), watched.get(rule["id"])
        if when:
            next_ = f"{local(when)} ({relative(when)})"
        else:
            next_ = f"👁 {watch_detail(watch)}" if watch else ""
        table.add_row(
            rule["id"],
            rule["name"],
            trigger(rule),
            "[green]✔[/]" if rule["enabled"] else "[dim]✘[/]",
            next_,
        )
    console.print(table)


@rules_app.command("show")
def rules_show(rule_id: str) -> None:
    """A rule as JSON."""
    with _daemon() as client:
        rule = client.get(f"/rules/{rule_id}")
    typer.echo(json.dumps(rule, indent=2, ensure_ascii=False))


@rules_app.command("add")
def rules_add(file: Annotated[Path, typer.Argument(help="JSON with one rule or a list.")]) -> None:
    """Add the rules in a JSON file."""
    with _daemon() as client:
        for data in _read_rules(file):
            rule = client.post("/rules", json=data)
            console.print(f"[green]✔[/] {_('Added')}: {rule['id']} — {rule['name']}")


@rules_app.command("edit")
def rules_edit(rule_id: str) -> None:
    """Edit a rule in your $EDITOR."""
    with _daemon() as client:
        rule = client.get(f"/rules/{rule_id}")
        text = click.edit(json.dumps(rule, indent=2, ensure_ascii=False), extension=".json")
        if text is None:
            console.print(_("No changes."))
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            _fail(_("invalid JSON: {error}").format(error=exc))
        rule = client.put(f"/rules/{rule_id}", json=data)
    console.print(f"[green]✔[/] {_('Saved')}: {rule['id']} — {rule['name']}")


@rules_app.command("enable")
def rules_enable(rule_id: str) -> None:
    """Enable a rule."""
    with _daemon() as client:
        rule = client.post(f"/rules/{rule_id}/enable")
    console.print(f"[green]✔[/] {_('Enabled')}: {rule['id']} — {rule['name']}")


@rules_app.command("disable")
def rules_disable(rule_id: str) -> None:
    """Disable a rule (it stays saved)."""
    with _daemon() as client:
        rule = client.post(f"/rules/{rule_id}/disable")
    console.print(f"[green]✔[/] {_('Disabled')}: {rule['id']} — {rule['name']}")


@rules_app.command("rm")
def rules_rm(rule_id: str) -> None:
    """Delete a rule."""
    with _daemon() as client:
        client.delete(f"/rules/{rule_id}")
    console.print(f"[green]✔[/] {_('Deleted')}: {rule_id}")


@rules_app.command("run")
def rules_run(rule_id: str) -> None:
    """Run a rule now (its conditions, guards and countdown still apply)."""
    with _daemon() as client:
        run = client.post(f"/rules/{rule_id}/run")
    console.print(f"[green]✔[/] {_('Started')}: {run['rule_name']} ({run['id']})")


@rules_app.command("export")
def rules_export(
    file: Annotated[Path | None, typer.Argument(help="Where to write; default: stdout.")] = None,
) -> None:
    """Export every rule as JSON."""
    with _daemon() as client:
        rules = client.get("/rules")
    text = json.dumps({"version": 1, "rules": rules}, indent=2, ensure_ascii=False) + "\n"
    if file is None:
        typer.echo(text, nl=False)
    else:
        file.write_text(text, encoding="utf-8")
        message = _("Exported {count} rule(s) to {file}").format(count=len(rules), file=file)
        console.print(f"[green]✔[/] {message}")


@rules_app.command("import")
def rules_import(
    file: Path,
    replace: Annotated[
        bool, typer.Option("--replace", help="Overwrite rules with the same id.")
    ] = False,
) -> None:
    """Import rules from a JSON file (an export or a list)."""
    with _daemon() as client:
        existing = {rule["id"] for rule in client.get("/rules")}
        for data in _read_rules(file):
            rule_id = data.get("id")
            if rule_id in existing and not replace:
                console.print(f"[yellow]•[/] {_('Skipped (already exists)')}: {rule_id}")
                continue
            if rule_id in existing:
                rule = client.put(f"/rules/{rule_id}", json=data)
            else:
                rule = client.post("/rules", json=data)
            console.print(f"[green]✔[/] {_('Imported')}: {rule['id']} — {rule['name']}")


# ── Service ────────────────────────────────────────────────────────────────────


def _service() -> ModuleType:
    try:
        return service_module()
    except NotSupported as exc:
        _fail(str(exc))


@service_app.command("install")
def service_install(
    linger: Annotated[
        bool,
        typer.Option(
            "--linger", help="Keep the daemon running without a login (unattended wake-ups)."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="The service only logs power actions (testing).")
    ] = False,
) -> None:
    """Install the daemon as a user service, start it now and at every login."""
    module = _service()
    try:
        done = module.install(dry_run=dry_run, linger_user=getpass.getuser() if linger else None)
    except module.ServiceError as exc:
        _fail(str(exc))
    for line in done:
        console.print(f"[green]✔[/] {line}")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Stop and remove the service (rules and history are kept)."""
    module = _service()
    try:
        done = module.uninstall()
    except module.ServiceError as exc:
        _fail(str(exc))
    for line in done:
        console.print(f"[green]✔[/] {line}")


@service_app.command("status")
def service_status() -> None:
    """Whether the service is installed, enabled and running."""
    state = _service().status()
    mark = "[green]✔[/]" if state.installed else "[red]✘[/]"
    console.print(f"{mark} {_('unit')}: {state.unit}")
    console.print(f"  {_('active')}: {state.active} · {_('enabled')}: {state.enabled}")


# ── Helper ─────────────────────────────────────────────────────────────────────


def _helper() -> ModuleType:
    try:
        return helper_module()
    except NotSupported as exc:
        _fail(str(exc))


def _offer(module: ModuleType, commands: list[list[str]], print_only: bool) -> bool:
    """Show the exact commands; run them with sudo only if the user says yes."""
    if print_only:
        for command in commands:
            typer.echo(module.shell(command))
        return False
    if not _as_root(module, commands):
        raise typer.Exit(1)
    return True


def _as_root(module: ModuleType, commands: list[list[str]]) -> bool:
    """Show the commands and run them with sudo if the user agrees; False if not done."""
    for command in commands:
        typer.echo(module.shell(command))
    if not typer.confirm(_("Run these commands now with sudo?"), default=False):
        console.print(_("Nothing done: you can run them yourself."))
        return False
    failed = module.run_all(commands)
    if failed is not None:
        errors.print(
            "[red]✘[/] " + escape(_("failed: {command}").format(command=module.shell(failed)))
        )
        return False
    return True


@helper_app.command("install")
def helper_install(
    unattended: Annotated[
        bool,
        typer.Option(
            "--unattended",
            help="Also allow wake-ups and power actions without a login (polkit rule).",
        ),
    ] = False,
    print_only: Annotated[
        bool, typer.Option("--print", help="Only show the commands, do not run them.")
    ] = False,
) -> None:
    """Install the wake-up helper and its polkit policy (asks before using sudo)."""
    module = _helper()
    rules_file = Paths.default().data / "50-powerclock-unattended.rules"
    user = getpass.getuser() if unattended else None
    commands = module.install_commands(unattended_user=user, rules_file=rules_file)
    console.print(_("To allow turning the computer on, these commands run as root:"))
    if _offer(module, commands, print_only):
        console.print(f"[green]✔[/] {_('Done: PowerClock can turn the computer on.')}")
        console.print(
            _("  check: powerclock doctor · try it: powerclock doctor --test-wake 120"), style="dim"
        )
        if unattended:
            console.print(
                _("  to work with the session closed: powerclock service install --linger"),
                style="dim",
            )


@helper_app.command("uninstall")
def helper_uninstall(
    print_only: Annotated[
        bool, typer.Option("--print", help="Only show the commands, do not run them.")
    ] = False,
) -> None:
    """Clear the alarm and remove the helper and the polkit files (asks before using sudo)."""
    module = _helper()
    commands = module.uninstall_commands(helper_present=module.HELPER.exists())
    console.print(
        _("To remove the permission to turn the computer on, these commands run as root:")
    )
    if _offer(module, commands, print_only):
        console.print(f"[green]✔[/] {_('Permission to turn the computer on removed.')}")


# ── GUI ────────────────────────────────────────────────────────────────────────


def gui_executable() -> Path | None:
    """powerclock-gui next to this Python (the same install), else the one on the PATH."""
    beside = Path(sys.executable).parent / (
        "powerclock-gui.exe" if sys.platform == "win32" else "powerclock-gui"
    )
    if beside.exists():
        return beside
    found = shutil.which("powerclock-gui")
    return Path(found) if found else None


@app.command()
def gui(
    tray: Annotated[bool, typer.Option("--tray", help="Only the tray icon, no window.")] = False,
) -> None:
    """Open PowerClock's window and tray icon (it keeps running after this command returns)."""
    executable = gui_executable()
    if executable is None or importlib.util.find_spec("PySide6") is None:
        _fail(_("The GUI is not installed: pipx install --force 'powerclock[gui]'"))
    command = [str(executable), *(["--tray"] if tray else [])]
    subprocess.Popen(  # detached: the terminal is free again at once
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    console.print(f"[green]✔[/] {_('PowerClock opened')}")


# ── Setup, update and uninstall ────────────────────────────────────────────────


def _report(report: Report) -> None:
    for line in report.done:
        console.print(f"[green]✔[/] {escape(line)}")
    for line in report.problems:
        console.print(f"[yellow]•[/] {escape(line)}")


@app.command()
def setup(
    menu: Annotated[
        bool, typer.Option("--menu/--no-menu", help="An entry in the applications menu.")
    ] = True,
    login: Annotated[
        bool, typer.Option("--login/--no-login", help="The tray icon when the session starts.")
    ] = True,
    helper: Annotated[
        bool,
        typer.Option(
            "--helper/--no-helper", help="Turn the computer on at a time (asks for sudo once)."
        ),
    ] = True,
    unattended: Annotated[
        bool, typer.Option("--unattended", help="Also act with nobody logged in.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="The service only logs power actions (testing).")
    ] = False,
) -> None:
    """Set PowerClock up in this session: service, menu, login start and wake-up helper."""
    installer = Setup()
    options = Options(
        menu=menu,
        login=login,
        helper=helper,
        unattended=unattended,
        dry_run=dry_run or dry_run_requested(),
    )

    def run_root(commands: list[list[str]]) -> bool:
        console.print(_("To allow turning the computer on, these commands run as root:"))
        return installer.helper is not None and _as_root(installer.helper, commands)

    report = installer.install(options, run_root)
    _report(report)
    if report.ok:
        console.print(_("PowerClock is ready. Open it with: powerclock gui"))


@app.command()
def update() -> None:
    """Install the newest version of PowerClock and restart its service."""
    try:
        latest = asyncio.run(latest_version())
    except httpx.HTTPError as exc:
        _fail(_("cannot reach PyPI: {error}").format(error=exc))
    if not newer(latest):
        console.print(_("PowerClock {version} is the newest version.").format(version=__version__))
        return
    upgrade = program_commands().upgrade
    if upgrade is None:
        _fail(
            _("Version {latest} is out; update it the way you installed it.").format(latest=latest)
        )
    if subprocess.run(upgrade, check=False).returncode != 0:
        _fail(_("the update failed"))
    service = Setup().service
    if service is not None and service.status().installed:
        service.restart()
    console.print("[green]✔[/] " + _("Updated to {version}.").format(version=latest))


@app.command()
def uninstall(
    purge: Annotated[
        bool, typer.Option("--purge", help="Also delete your rules and history.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Take PowerClock out of this session: service, menu, login start, helper and program."""
    if not yes and not typer.confirm(_("Uninstall PowerClock?"), default=False):
        raise typer.Exit(1)
    installer = Setup()

    def run_root(commands: list[list[str]]) -> bool:
        console.print(
            _("To remove the permission to turn the computer on, these commands run as root:")
        )
        return installer.helper is not None and _as_root(installer.helper, commands)

    _report(installer.uninstall(run_root, remove_data=purge))
    remove = program_commands().uninstall
    if remove is None:
        console.print(
            _("Remove the program the way you installed it (e.g. pipx uninstall powerclock).")
        )
        return
    subprocess.run(remove, check=False)
    console.print("[green]✔[/] " + _("PowerClock uninstalled."))


# ── Doctor ─────────────────────────────────────────────────────────────────────


def _test_wake(seconds: int) -> None:
    if dry_run_requested():
        console.print(
            _("[yellow]Test mode:[/] the test would suspend the computer, so nothing was done.")
        )
        return
    console.print(
        _(
            "This programs a wake-up in {seconds} s and [bold]suspends the computer now[/]. "
            "Save your work and do not touch it until it wakes up by itself."
        ).format(seconds=seconds)
    )
    if not typer.confirm(_("Suspend now?"), default=False):
        raise typer.Exit(1)
    for left in range(HANDS_OFF, 0, -1):  # a touchpad or a pointing stick can wake it up
        console.print(
            _("Suspending in {seconds} s: hands off the keyboard, touchpad and stick…").format(
                seconds=f"{left:2d}"  # fixed width: \r rewrites the line in place
            ),
            end="\r",
        )
        time.sleep(1)
    console.print()

    def announce(alarm: datetime) -> None:
        console.print(_("⏰ alarm set for {time}; suspending…").format(time=local(alarm)))

    async def run() -> WakeTest:
        backend = get_backend()
        try:
            return await run_wake_test(backend, seconds, announce=announce)
        finally:
            await backend.close()

    try:
        result = asyncio.run(run())
    except NotSupported as exc:
        _fail(f"{exc}" + (f" ({exc.fix_hint})" if exc.fix_hint else ""))
    style = {"ok": "green", "early": "yellow"}.get(result.verdict, "red")
    first, *rest = verdict_message(result, local).splitlines()
    console.print(first, style=style, markup=False)
    for line in rest:
        console.print(f"  {line}", style="dim", markup=False)
    if result.verdict != "ok":
        raise typer.Exit(1)


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
    test_wake: Annotated[
        int | None,
        typer.Option(
            "--test-wake",
            min=60,
            max=3600,
            help="Program a wake-up in N seconds and SUSPEND now, to check it (asks first).",
        ),
    ] = None,
) -> None:
    """Check what works on this machine and how to fix what does not."""
    if test_wake is not None:
        _test_wake(test_wake)
        return
    backend = get_backend()
    name = backend.name
    capabilities = asyncio.run(collect(backend))
    if as_json:
        typer.echo(json.dumps([c.model_dump() for c in capabilities], indent=2, ensure_ascii=False))
        return
    console.print(f"[bold]powerclock {__version__}[/] · backend [bold]{name}[/]")
    if dry_run_requested():
        console.print(
            _("[yellow]Test mode:[/] nothing really turns off or on; actions are only noted down.")
        )
    table = Table(show_lines=False, header_style="bold")
    table.add_column("", width=1)
    table.add_column(_("Capability"), no_wrap=True)
    table.add_column(_("Detail"))
    table.add_column(_("How to fix"))
    for capability in capabilities:
        mark = "[green]✔[/]" if capability.supported else "[red]✘[/]"
        table.add_row(mark, capability.id, capability.detail, capability.fix_hint or "")
    console.print(table)
