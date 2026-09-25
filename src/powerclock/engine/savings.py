"""Use and savings: how long the computer was on and off, how much of the off time came
after PowerClock shut it down or put it to sleep, and the energy that saved (estimated).

The daemon notes the periods it was awake (`History.awake`: a mark every minute; a gap
starts a new period) and how a period ended when PowerClock ended it. Time with the daemon
stopped counts as off: it is an estimate.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SAVING_ACTIONS = ("shutdown", "suspend", "hibernate", "hybrid_sleep")
LAPTOP_WATTS = 15.0  # typical consumption when nobody set theirs
DESKTOP_WATTS = 60.0
STANDBY_WATTS = 1.0  # still drawn when asleep or off
PRICE_KWH = 0.15  # €/kWh, when nobody set theirs


@dataclass(frozen=True)
class Period:
    since: datetime
    until: datetime
    ended: str | None = None  # the PowerClock action that ended it, if any


@dataclass
class Stats:
    since: datetime
    until: datetime
    on: timedelta = timedelta(0)
    off: timedelta = timedelta(0)
    off_by_powerclock: timedelta = timedelta(0)
    actions: dict[str, int] = field(default_factory=dict)

    def saved_kwh(self, watts: float) -> float:
        hours = self.off_by_powerclock.total_seconds() / 3600
        return max(0.0, watts - STANDBY_WATTS) * hours / 1000


def stats(periods: Iterable[Period], since: datetime, until: datetime) -> Stats:
    """Totals between `since` and `until`; before the first period nothing is known."""
    ordered = sorted(periods, key=lambda period: period.since)
    result = Stats(since=since, until=until)
    known_from = max(since, ordered[0].since) if ordered else until
    result.since = known_from
    for index, period in enumerate(ordered):
        result.on += _overlap(period.since, period.until, known_from, until)
        after = ordered[index + 1].since if index + 1 < len(ordered) else None
        if after is None:
            continue  # the last period: on until now
        gap = _overlap(period.until, after, known_from, until)
        result.off += gap
        if period.ended in SAVING_ACTIONS:
            result.off_by_powerclock += gap
            if period.until >= known_from:
                result.actions[period.ended] = result.actions.get(period.ended, 0) + 1
    return result


def default_watts(has_battery: bool | None) -> float:
    """A laptop (it has a battery) or a desktop; in between if unknown."""
    if has_battery is None:
        return (LAPTOP_WATTS + DESKTOP_WATTS) / 2
    return LAPTOP_WATTS if has_battery else DESKTOP_WATTS


def _overlap(start: datetime, end: datetime, low: datetime, high: datetime) -> timedelta:
    return max(timedelta(0), min(end, high) - max(start, low))
