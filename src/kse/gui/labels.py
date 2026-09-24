"""Translatable names for what the GUI shows: rule parts, fields, values and run states."""

from typing import Any

from kse.cli.format import local
from kse.i18n import _, power_action_label
from kse.platform.base import PowerAction


def kind_label(kind: str) -> str:
    """Name of a trigger, predicate or action type."""
    labels = {
        # triggers
        "at": _("At a date and time"),
        "countdown": _("After a delay"),
        "cron": _("Repeating (cron)"),
        "process_exit": _("When a program exits"),
        "startup": _("At startup or after resume"),
        "manual": _("Only by hand"),
        # triggers and predicates
        "idle": _("Nobody uses the computer"),
        "cpu_below": _("CPU usage below"),
        "net_below": _("Network traffic below"),
        "battery": _("Battery level"),
        "power_source": _("Power source"),
        # predicates
        "process_running": _("A program is running"),
        "media_playing": _("Something is playing"),
        "ssh_session": _("Someone is connected by SSH"),
        "time_window": _("Time of day between"),
        "weekday": _("Day of the week"),
        "wifi_ssid": _("Connected to the Wi-Fi network"),
        "json": _("Advanced (JSON)"),
        # actions
        "power": _("Power action"),
        "run": _("Run a program"),
        "open": _("Open a file or web page"),
        "close_app": _("Close a program"),
        "notify": _("Show a notification"),
        "wait": _("Wait"),
        "wait_until": _("Wait until"),
        "set_wake": _("Program a wake-up"),
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
        "is": _("Source"),
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
        "warning": _("Countdown before power actions"),
        "wake": _("Wake the computer up for it"),
        "one_shot": _("Only once (then disable it)"),
        "on_missed": _("If the moment was missed"),
        "on_error": _("If a step fails"),
        "dry_run": _("Dry run (only log power actions)"),
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
        case _:
            detail = ""
    return kind_label(kind) + (f": {detail}" if detail else "")


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
        ("is", "ac"): _("Plugged in (AC)"),
        ("is", "battery"): _("On battery"),
        ("on", "daemon_start"): _("When KSE starts"),
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
        "dry_run": _("dry run"),
    }
    return labels.get(state, state)


def cause_label(cause: str) -> str:
    labels = {
        "schedule": _("scheduled"),
        "trigger": _("condition"),
        "manual": _("by hand"),
    }
    return labels.get(cause, cause)
