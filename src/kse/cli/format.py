"""How the CLI shows times, durations and rules."""

from datetime import UTC, datetime
from typing import Any


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
    return f"in {text}" if seconds >= 0 else f"{text} ago"


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
