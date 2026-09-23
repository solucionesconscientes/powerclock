"""Times typed by people ("23:30", "2026-09-24 07:30") turned into instants."""

import re
from datetime import UTC, datetime, timedelta, tzinfo

_CLOCK = re.compile(r"(\d{1,2}):(\d{2})")


def resolve_at(text: str, now: datetime, tz: tzinfo) -> datetime:
    """ "HH:MM" is its next occurrence; an ISO date-time without offset is in `tz`."""
    text = text.strip()
    if match := _CLOCK.fullmatch(text):
        hour, minute = int(match[1]), int(match[2])
        if hour > 23 or minute > 59:
            raise ValueError(f"invalid time {text!r}")
        today = now.astimezone(tz).date()
        for day in (today, today + timedelta(days=1)):
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if candidate > now:
                return candidate.astimezone(UTC)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"invalid time {text!r}: use HH:MM or YYYY-MM-DD HH:MM") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(UTC)
