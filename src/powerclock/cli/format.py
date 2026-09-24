"""How the CLI shows times, durations and rules."""

from datetime import UTC, datetime
from typing import Any

from powerclock.i18n import _
from powerclock.models import parse_duration


def moment(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def local(value: str | datetime | None) -> str:
    """A date-time in the machine's local time."""
    when = moment(value)
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S") if when else "-"


def relative(value: str | datetime | None, now: datetime | None = None) -> str:
    when = moment(value)
    if when is None:
        return "-"
    seconds = round((when - (now or datetime.now(UTC))).total_seconds())
    text = span(abs(seconds))
    return _("in {time}").format(time=text) if seconds >= 0 else _("{time} ago").format(time=text)


def span(seconds: int) -> str:
    days, rest = divmod(seconds, 86_400)
    hours, rest = divmod(rest, 3_600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def trigger(rule: dict[str, Any]) -> str:
    data = dict(rule["trigger"])
    kind = data.pop("type")
    match kind:
        case "at":
            return f"at {local(data['when'])}"
        case "countdown":
            return f"countdown {data['duration']}"
        case "cron":
            return f"cron {data['expr']}"
        case "manual":
            return "manual"
    details = " ".join(f"{key}={value}" for key, value in data.items() if value is not None)
    return f"{kind} {details}".strip()


def watch_detail(item: dict[str, Any]) -> str:
    """What a rule with a state trigger sees now (an item of /pending "watching")."""
    trigger_ = item["trigger"]
    value, measured = item.get("value"), item.get("measured")
    window = trigger_.get("for")
    match trigger_["type"]:
        case "process_exit":
            target = trigger_.get("name") or f"PID {trigger_.get('pid')}"
            if value == "running":
                text = _("{process} is running").format(process=target)
            elif trigger_.get("pid"):
                text = _("{process} is not running: it may have ended already").format(
                    process=target
                )
            else:
                text = _("{process} is not running yet: waiting for it to start").format(
                    process=target
                )
        case "idle":
            text = (
                _("idle for {time}").format(time=span(round(value)))
                if isinstance(value, int | float)
                else _("idle time unknown")
            )
        case "cpu_below" | "net_below":
            text = _average(trigger_["type"], value, measured, window)
        case "battery":
            text = (
                _("battery at {percent} %").format(percent=round(value))
                if isinstance(value, int | float)
                else _("battery level unknown")
            )
        case "power_source":
            text = {"ac": _("on AC"), "battery": _("on battery")}.get(str(value), _("unknown"))
        case _:
            text = ""
    if not item.get("armed", True):
        text += " · " + _("done: waits until the condition is over")
    return text


def _average(kind: str, value: Any, measured: float | None, window: str | None) -> str:
    if not isinstance(value, int | float):
        return _("measuring…")
    text = f"CPU {value:.0f} %" if kind == "cpu_below" else f"{value:.0f} kbit/s"
    if measured is None or window is None:
        return text
    if measured < parse_duration(window).total_seconds():
        return (
            text
            + " · "
            + _("measuring: {elapsed} of {window}").format(
                elapsed=span(round(measured)), window=window
            )
        )
    return text + " · " + _("average of the last {window}").format(window=window)
