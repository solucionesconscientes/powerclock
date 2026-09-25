"""Translatable names for what the CLI and the GUI show: rule parts, fields, values, run
states, capabilities and the reasons the engine writes (stored in English, translated when
shown). They use the user's words (docs/ARCHITECTURE.md §10, vocabulary)."""

import json
import re
from collections.abc import Callable
from typing import Any

from powerclock.cli.format import local
from powerclock.i18n import _, power_action_label
from powerclock.platform.base import PowerAction


def kind_label(kind: str) -> str:
    """Name of a trigger, predicate or action type."""
    labels = {
        # triggers
        "at": _("At a date and time"),
        "countdown": _("After a delay"),
        "cron": _("Repeats (cron expression)"),
        "process_exit": _("When a program ends"),
        "startup": _("When PowerClock starts or the computer wakes up"),
        "manual": _("Only by hand"),
        # triggers and predicates
        "idle": _("Not in use"),
        "cpu_below": _("Computer quiet (CPU below)"),
        "net_below": _("Network quiet (below)"),
        "battery": _("Battery level"),
        "power_source": _("Plugged in or on battery"),
        # predicates
        "process_running": _("A program is running"),
        "media_playing": _("Something is playing"),
        "ssh_session": _("Someone is connected by SSH"),
        "time_window": _("Time of day between"),
        "weekday": _("Day of the week"),
        "wifi_ssid": _("Connected to the Wi-Fi network"),
        "json": _("Advanced (JSON)"),
        # actions
        "power": _("Shut down, restart, suspend…"),
        "run": _("Run a program"),
        "open": _("Open a file or web page"),
        "close_app": _("Close a program"),
        "notify": _("Show a notification"),
        "wait": _("Wait"),
        "wait_until": _("Wait until"),
        "set_wake": _("Turn the computer on later"),
    }
    return labels.get(kind, kind)


def field_label(name: str) -> str:
    labels = {
        "name": _("Name"),
        "enabled": _("Enabled"),
        "for": _("For"),
        "percent": _("Percent"),
        "kbps": _("kbit/s"),
        "direction": _("Direction"),
        "interface": _("Interface"),
        "below": _("Below (%)"),
        "above": _("Above (%)"),
        "is": _("Power"),
        "when": _("When"),
        "duration": _("Duration"),
        "expr": _("Cron expression"),
        "pid": _("PID"),
        "on": _("On"),
        "delay": _("Delay"),
        "start": _("From"),
        "end": _("To"),
        "days": _("Days"),
        "ssid": _("Network name"),
        "action": _("Action"),
        "mode": _("Mode"),
        "cmd": _("Command"),
        "cwd": _("Working folder"),
        "env": _("Environment"),
        "shell": _("Run through the shell"),
        "timeout": _("Time limit"),
        "wait": _("Wait until it ends"),
        "target": _("File or address"),
        "title": _("Title"),
        "body": _("Text"),
        "condition": _("Condition"),
        "after": _("After"),
        "warning": _("Warn before shutting down, restarting or suspending"),
        "wake": _("Turn the computer on for it"),
        "one_shot": _("Only once (then disable it)"),
        "on_missed": _("If the moment was missed"),
        "on_error": _("If a step fails"),
        "dry_run": _("Test mode (nothing really turns off)"),
        "timezone": _("Time zone"),
        "retry": _("Check again every"),
        "max_wait": _("Give up after"),
    }
    return labels.get(name, name.replace("_", " ").capitalize())


def describe_trigger(trigger: dict[str, Any]) -> str:
    """A trigger in one line: "When a program exits: ffmpeg", "CPU usage below: 10 % for 5m"."""
    kind = trigger.get("type", "")
    held = trigger.get("for")
    during = _(" for {time}").format(time=held) if held and held != "0s" else ""
    match kind:
        case "at":
            detail = local(trigger["when"])[:16]
        case "countdown":
            detail = trigger["duration"]
        case "cron":
            detail = trigger["expr"]
        case "idle":
            detail = _("for {time}").format(time=held)
        case "process_exit":
            detail = trigger.get("name") or f"PID {trigger.get('pid')}"
        case "cpu_below":
            detail = f"{trigger['percent']:g} %{during}"
        case "net_below":
            detail = f"{trigger['kbps']:g} kbit/s{during}"
            if trigger.get("direction", "both") != "both":
                detail += f" ({value_label('direction', trigger['direction']).lower()})"
            if trigger.get("interface"):
                detail += f" · {trigger['interface']}"
        case "battery":
            below = trigger.get("below")
            text = _("below {percent} %") if below is not None else _("above {percent} %")
            detail = text.format(percent=below if below is not None else trigger.get("above"))
            detail += during
        case "power_source":
            detail = value_label("is", trigger["is"]) + during
        case "startup":
            detail = ", ".join(value_label("on", item) for item in trigger.get("on", []))
            if trigger.get("delay", "0s") != "0s":
                detail += " + " + trigger["delay"]
        case "process_running":
            detail = trigger.get("name", "")
        case "wifi_ssid":
            detail = trigger.get("ssid", "")
        case "weekday":
            detail = ", ".join(value_label("days", day) for day in trigger.get("days", []))
        case "time_window":
            detail = f"{str(trigger.get('start'))[:5]}-{str(trigger.get('end'))[:5]}"
        case _:
            detail = ""
    return kind_label(kind) + (f": {detail}" if detail else "")


def describe_predicate(predicate: Any) -> str:
    """A condition in words: "A program is running: ffmpeg", "not (…)", "… or …"."""
    if not isinstance(predicate, dict):
        return str(predicate)
    if "type" in predicate:
        return describe_trigger(predicate)
    if "not" in predicate:
        return _("not ({condition})").format(condition=describe_predicate(predicate["not"]))
    if "all" in predicate:
        return " + ".join(describe_predicate(item) for item in predicate["all"])
    if "any" in predicate:
        return _(" or ").join(describe_predicate(item) for item in predicate["any"])
    return json.dumps(predicate, ensure_ascii=False)


def _condition(text: str) -> str:
    try:
        return describe_predicate(json.loads(text))
    except ValueError:
        return text


_REASONS: dict[str, Callable[[], str]] = {
    "conditions not met": lambda: _("conditions not met"),
    "conditions unknown: a sensor could not be read": lambda: _(
        "conditions unknown: a sensor could not be read"
    ),
    "cancelled": lambda: _("cancelled"),
    "cancelled before it fired": lambda: _("cancelled before it fired"),
    "the previous run of this rule is still active": lambda: _(
        "the previous run of this rule is still active"
    ),
    "another power action is in progress": lambda: _("another power action is in progress"),
    "missed: the machine was off or asleep, or the daemon was not running": lambda: _(
        "missed: the computer was off or asleep, or PowerClock was not running"
    ),
    "not running": lambda: _("it was not running"),
}

_PATTERNS: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    (
        re.compile(r"step (\d+) \((\w+)\) failed: (.*)", re.DOTALL),
        lambda m: _("step {number} ({kind}) failed: {detail}").format(
            number=m[1], kind=kind_label(m[2]), detail=detail_label(m[3])
        ),
    ),
    (
        re.compile(r"guard still active after (\S+): (.*)", re.DOTALL),
        lambda m: _("still held after {time}: {guard}").format(time=m[1], guard=_condition(m[2])),
    ),
    (
        re.compile(r"guard active: (.*)", re.DOTALL),
        lambda m: _("waiting while: {guard}").format(guard=_condition(m[1])),
    ),
    (
        re.compile(r"waiting until (.*)", re.DOTALL),
        lambda m: _("waiting until: {condition}").format(condition=_condition(m[1])),
    ),
    (
        re.compile(r"timed out after (\S+)"),
        lambda m: _("timed out after {time}").format(time=m[1]),
    ),
    (
        re.compile(r"condition not met within (\S+)"),
        lambda m: _("the condition was not met within {time}").format(time=m[1]),
    ),
    (
        re.compile(r"exit code (-?\d+)(?:: (.*))?", re.DOTALL),
        lambda m: _("exit code {code}").format(code=m[1]) + (f": {m[2]}" if m[2] else ""),
    ),
    (
        re.compile(r"closed (\d+) process\(es\)"),
        lambda m: _("closed {count} process(es)").format(count=m[1]),
    ),
    (
        re.compile(r"started in the background \(pid (\d+)\)"),
        lambda m: _("started in the background (PID {pid})").format(pid=m[1]),
    ),
    (
        re.compile(r"dry run: (\w+) \((\w+)\) not executed"),
        lambda m: _("test mode: {action} was not really done").format(
            action=value_label("action", m[1])
        ),
    ),
    (
        re.compile(r"internal error: (.*)", re.DOTALL),
        lambda m: _("internal error: {error}").format(error=m[1]),
    ),
]


def reason_label(reason: str | None) -> str:
    """Why a run is waiting or ended as it did, in the user's language."""
    if not reason:
        return ""
    if reason in _REASONS:
        return _REASONS[reason]()
    for pattern, render in _PATTERNS:
        match = pattern.fullmatch(reason)
        if match:
            return render(match)
    return reason


def detail_label(detail: str | None) -> str:
    """What a step reported (its output is shown as it came)."""
    return reason_label(detail)


def value_label(field: str, value: str) -> str:
    """Name of an enumerated value (direction, source, mode, action, day…)."""
    if field == "action":
        try:
            return power_action_label(PowerAction(value))
        except ValueError:
            return value
    labels = {
        ("direction", "down"): _("Download"),
        ("direction", "up"): _("Upload"),
        ("direction", "both"): _("Both"),
        ("is", "ac"): _("Plugged in"),
        ("is", "battery"): _("On battery"),
        ("on", "daemon_start"): _("When PowerClock starts"),
        ("on", "resume"): _("After resume"),
        ("on_missed", "skip"): _("Skip it"),
        ("on_missed", "run_once"): _("Run it once"),
        ("on_error", "stop"): _("Stop"),
        ("on_error", "continue"): _("Continue with the next step"),
        ("mode", "graceful"): _("Let applications ask to save"),
        ("mode", "force"): _("Force"),
        ("days", "mon"): _("Mon"),
        ("days", "tue"): _("Tue"),
        ("days", "wed"): _("Wed"),
        ("days", "thu"): _("Thu"),
        ("days", "fri"): _("Fri"),
        ("days", "sat"): _("Sat"),
        ("days", "sun"): _("Sun"),
    }
    return labels.get((field, value), value)


def state_label(state: str) -> str:
    labels = {
        "running": _("running"),
        "waiting": _("waiting"),
        "postponed": _("postponed"),
        "warning": _("counting down"),
        "done": _("done"),
        "failed": _("failed"),
        "cancelled": _("cancelled"),
        "skipped": _("skipped"),
        "ok": _("ok"),
        "dry_run": _("test mode"),
    }
    return labels.get(state, state)


def cause_label(cause: str) -> str:
    labels = {
        "schedule": _("Schedule"),
        "trigger": _("Condition"),
        "manual": _("Manual"),
    }
    return labels.get(cause, cause)


def capability_label(capability_id: str) -> str:
    """What a line of the doctor report is about, for people ("power.shutdown" → "Shut down")."""
    kind, _dot, action = capability_id.partition(".")
    if kind == "power" and action not in ("", "graceful"):
        try:
            return power_action_label(PowerAction(action))
        except ValueError:
            pass
    labels = {
        "session": _("Desktop session"),
        "power.graceful": _("Let applications ask to save"),
        "idle": _("Know when the computer is not in use"),
        "media": _("Know when something is playing"),
        "notify": _("Notifications"),
        "wifi": _("Wi-Fi network"),
        "power_events": _("Notice shutdowns and suspends"),
        "inhibit": _("Delay a shutdown to keep the wake-up alarm"),
        "wake.rtc": _("Wake-up clock (RTC)"),
        "wake.helper": _("Permission to turn the computer on"),
        "wake.authorized": _("Turn on without asking for a password"),
        "wake.unattended": _("Turn on and off with the session closed"),
        "wake.alarm": _("Next wake-up alarm"),
        "hardware": _("Computer"),
        "linger": _("Work with the session closed"),
        "timezone": _("Time zone"),
        "power_source": _("Power supply"),
        "sensors": _("Sensors"),
    }
    return labels.get(capability_id, capability_id)
