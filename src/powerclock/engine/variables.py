"""Variables in the text of steps: `{date}`, `{time}`… replaced when a run starts.

Only these exact names are replaced, so any other braces (a shell `{a,b}`, a yt-dlp
`%(ext)s`, JSON) stay as they are. Times are the run's start in the rule's time zone,
written so they fit in file names: `{date}` 2026-09-25, `{time}` 07-30, `{datetime}`
2026-09-25_07-30, `{weekday}` thu (like the `weekday` condition), `{rule}` the rule's id,
plus what the daemon adds (`{home}`, `{data}`).
"""

import re
from collections.abc import Mapping
from datetime import datetime

NAMES = ("date", "time", "datetime", "weekday", "rule")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def context(
    moment: datetime, rule_id: str, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The values for a run that starts at `moment` (already in the rule's time zone)."""
    return {
        **(extra or {}),
        "date": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime("%H-%M"),
        "datetime": moment.strftime("%Y-%m-%d_%H-%M"),
        "weekday": _WEEKDAYS[moment.weekday()],
        "rule": rule_id,
    }


def expand(text: str, values: Mapping[str, str]) -> str:
    """Replace every `{name}` whose name is in `values`; leave the rest untouched."""
    if "{" not in text or not values:
        return text
    pattern = re.compile(r"\{(" + "|".join(re.escape(name) for name in values) + r")\}")
    return pattern.sub(lambda match: values[match[1]], text)


def expand_all(items: list[str], values: Mapping[str, str]) -> list[str]:
    return [expand(item, values) for item in items]
