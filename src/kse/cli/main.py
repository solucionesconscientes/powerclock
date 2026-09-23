"""`kse` command line: quick actions, rules, status and the daemon service.

Everything except `doctor` and `service` talks to the daemon's local API.
"""

import asyncio
import contextlib
import getpass
import json
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, NoReturn

import click
import typer
from rich.console import Console
from rich.table import Table

from kse import __version__
from kse.cli import client as api
from kse.cli.format import local, relative, span, trigger
from kse.config import Paths
from kse.doctor import WakeTest, collect, run_wake_test
from kse.i18n import _, power_action_label
from kse.install.helper import helper_module
from kse.install.service import service_module
from kse.platform import dry_run_requested, get_backend
from kse.platform.base import NotSupported, PowerAction

app = typer.Typer(
    name="kse",
    help="KShutdown Evolution: power and task automation driven by persistent rules.",
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
        typer.echo(f"kse {__version__}")
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
    """KShutdown Evolution: power and task automation driven by persistent rules."""
    ctx.obj = {"dry_run": dry_run}


@contextlib.contextmanager
def _daemon() -> Iterator[api.Client]:
    """A client of the daemon; its errors become a message and exit code 1."""
    try:
        yield api.connect()
    except api.DaemonUnavailable as exc:
        errors.print(f"[red]✘[/] {exc}")
        errors.print(_("Start it with: kse service install   (or run: kse-daemon)"))
        raise typer.Exit(1) from None
    except api.ApiError as exc:
        errors.print(f"[red]✘[/] {exc}")
        raise typer.Exit(1) from None


def _fail(message: str) -> NoReturn:
    errors.print(f"[red]✘[/] {message}")
    raise typer.Exit(1)


def _styled(state: str) -> str:
    style = STATE_STYLES.get(state)
    return f"[{style}]{state}[/]" if style else state


# ── Quick actions ──────────────────────────────────────────────────────────────

InOption = Annotated[str | None, typer.Option("--in", help="After a delay: 30s, 5m, 2h, 1h30m.")]
AtOption = Annotated[
    str | None, typer.Option("--at", help="At a time: 23:30 or '2026-09-24 07:30'.")
]


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
    if rule.get("wake") or payload.get("wake_at"):
        _show_wake()
    console.print(_("  cancel: kse cancel · postpone: kse postpone 10m"), style="dim")


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
) -> None:
    """Wake the computer up (from suspend, or from off if the firmware allows it)."""
    with _daemon() as client:
        rule = client.post("/wake", json={"at": at})
    console.print(f"[green]✔[/] {rule['name']}")
    _show_wake()


def _power_command(action: PowerAction) -> Callable[..., None]:
    def command(
        ctx: typer.Context,
        in_: InOption = None,
        at: AtOption = None,
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
    ) -> None:
        payload: dict[str, Any] = {
            "action": action.value,
            "mode": "force" if force else "graceful",
            "warning": warning,
        }
        if wake:
            payload["wake_at"] = wake
        if in_:
            payload["in"] = in_
        if at:
            payload["at"] = at
        _quick(ctx, payload)

    return command


for _action in PowerAction:
    app.command(
        name=_action.value.replace("_", "-"),
        help=f"{power_action_label(_action)}: now, after a delay (--in) or at a time (--at).",
    )(_power_command(_action))


@app.command("run")
def run_command(
    ctx: typer.Context,
    command: Annotated[list[str], typer.Argument(help="The program and its arguments, after --.")],
    in_: InOption = None,
    at: AtOption = None,
    wake: Annotated[
        bool, typer.Option("--wake", help="Wake the computer up to run it (needs --in/--at).")
    ] = False,
) -> None:
    """Run a program now, after a delay or at a time: kse run --at 03:00 --wake -- backup.sh"""
    payload: dict[str, Any] = {"command": command, "wake": wake}
    if in_:
        payload["in"] = in_
    if at:
        payload["at"] = at
    _quick(ctx, payload)


# ── Status, cancel, postpone, history ──────────────────────────────────────────


@app.command()
def status() -> None:
    """What the daemon is doing and what comes next."""
    with _daemon() as client:
        health = client.get("/health")
        pending = client.get("/pending")
    console.print(
        f"[bold]kse {health['version']}[/] · {health['backend']} · {health['timezone']}"
        f" · {_('up')} {span(health['uptime'])}"
    )
    if health["dry_run"]:
        console.print(_("[yellow]Dry run:[/] power actions and wake alarms are only logged."))
    for problem in health["rules_errors"]:
        console.print(f"[red]✘ rules.json:[/] {problem}")
    wake = pending["wake"]
    if wake["error"]:
        console.print(f"[red]✘ {_('wake-up alarm')}:[/] {wake['error']}")
    elif wake["at"]:
        console.print(f"⏰ {_('wake-up alarm')}: {local(wake['at'])} ({relative(wake['at'])})")
    active, upcoming = pending["active"], pending["next"]
    if active:
        table = Table(title=_("Running"), title_justify="left", header_style="bold")
        for column in (_("Rule"), _("State"), _("Detail"), _("Run")):
            table.add_column(column)
        for run in active:
            detail = (
                _("acts {when}").format(when=relative(run["deadline"]))
                if run.get("deadline")
                else run.get("reason") or ""
            )
            table.add_row(run["rule_name"], _styled(run["state"]), detail, run["id"])
        console.print(table)
    if upcoming:
        table = Table(title=_("Next"), title_justify="left", header_style="bold")
        for column in (_("When"), _("In"), _("Rule"), _("Id")):
            table.add_column(column)
        for item in upcoming:
            table.add_row(local(item["at"]), relative(item["at"]), item["name"], item["rule_id"])
        console.print(table)
    if not active and not upcoming:
        console.print(_("Nothing scheduled."))


@app.command()
def cancel(
    run_id: Annotated[
        str | None,
        typer.Argument(help="A run id (see kse status); default: the countdown or quick action."),
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
            local(run["finished_at"]), run["rule_name"], _styled(run["state"]), run["reason"] or ""
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
        upcoming = {item["rule_id"]: item["at"] for item in client.get("/pending")["next"]}
    if not rules:
        console.print(_("No rules yet: kse rules add FILE.json (see examples/)."))
        return
    table = Table(header_style="bold")
    for column in (_("Id"), _("Name"), _("Trigger"), _("On"), _("Next")):
        table.add_column(column)
    for rule in rules:
        when = upcoming.get(rule["id"])
        table.add_row(
            rule["id"],
            rule["name"],
            trigger(rule),
            "[green]✔[/]" if rule["enabled"] else "[dim]✘[/]",
            f"{local(when)} ({relative(when)})" if when else "",
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
    for command in commands:
        typer.echo(module.shell(command))
    if print_only:
        return False
    if not typer.confirm(_("Run these commands now with sudo?"), default=False):
        console.print(_("Nothing done: you can run them yourself."))
        return False
    failed = module.run_all(commands)
    if failed is not None:
        _fail(_("failed: {command}").format(command=module.shell(failed)))
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
    rules_file = Paths.default().data / "50-kse-unattended.rules"
    user = getpass.getuser() if unattended else None
    commands = module.install_commands(unattended_user=user, rules_file=rules_file)
    console.print(_("To install the helper, these commands run as root:"))
    if _offer(module, commands, print_only):
        console.print(f"[green]✔[/] {_('Helper installed.')}")
        console.print(_("  check: kse doctor · try it: kse doctor --test-wake 120"), style="dim")
        if unattended:
            console.print(_("  unattended also needs: kse service install --linger"), style="dim")


@helper_app.command("uninstall")
def helper_uninstall(
    print_only: Annotated[
        bool, typer.Option("--print", help="Only show the commands, do not run them.")
    ] = False,
) -> None:
    """Clear the alarm and remove the helper and the polkit files (asks before using sudo)."""
    module = _helper()
    commands = module.uninstall_commands(helper_present=module.HELPER.exists())
    console.print(_("To remove the helper, these commands run as root:"))
    if _offer(module, commands, print_only):
        console.print(f"[green]✔[/] {_('Helper removed.')}")


# ── Doctor ─────────────────────────────────────────────────────────────────────


def _test_wake(seconds: int) -> None:
    if dry_run_requested():
        console.print(_("[yellow]Dry run:[/] the test would suspend the computer; nothing done."))
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
                seconds=left
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
    messages = {
        "ok": _("[green]✔ Woke up by itself[/] at {resumed} (alarm {alarm})."),
        "early": _("[yellow]? Resumed at {resumed}, before the alarm ({alarm}): woken by hand?[/]"),
        "late": _("[red]✘ Resumed at {resumed}, long after the alarm ({alarm}).[/]"),
        "no_sleep": _("[red]✘ The computer did not suspend (an inhibitor?).[/]"),
        "no_resume": _("[red]✘ No resume was seen.[/]"),
    }
    console.print(
        messages[result.verdict].format(resumed=local(result.resumed_at), alarm=local(result.alarm))
    )
    if result.woken_by:
        console.print(_("  woken by: {source}").format(source=result.woken_by))
    elif result.verdict in ("early", "late"):
        console.print(_("  the OS did not say what woke it up"), style="dim")
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
