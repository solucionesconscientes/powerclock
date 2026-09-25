"""Time triggers (at, countdown, cron, sun, calendar): when each rule fires next, and a loop
that fires them.

Instants are UTC-aware. Cron expressions follow the wall clock of the rule's time zone:
in a DST gap the run moves forward by the gap (02:30 → 03:30), and in the repeated hour
each wall-clock time fires once, at its first occurrence.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from croniter import CroniterBadDateError, croniter

from powerclock.engine import sun
from powerclock.engine.clock import Clock
from powerclock.models import (
    AtTrigger,
    CalendarTrigger,
    CountdownTrigger,
    CronTrigger,
    Rule,
    SunTrigger,
    Trigger,
)

log = logging.getLogger(__name__)

MAX_SLEEP = 30.0  # seconds; re-checking this often notices suspends and clock changes
MISSED_GRACE = timedelta(minutes=2)  # later than this counts as missed (on_missed applies)
_MAX_CRON_STEPS = 1000

OnDue = Callable[[Rule, datetime, bool], None]  # (rule, scheduled_for, missed)
# (calendar source, after, text in the title) → the next event's start
CalendarLookup = Callable[[str, datetime, str | None], datetime | None]


def next_fire(
    trigger: Trigger, after: datetime, tz: tzinfo, calendars: CalendarLookup | None = None
) -> datetime | None:
    """First instant strictly after `after` at which a time trigger fires (None: never)."""
    match trigger:
        case SunTrigger():
            offset = timedelta(minutes=trigger.offset_minutes)
            return sun.next_sun(
                after, trigger.event, offset, tz, trigger.latitude, trigger.longitude
            )
        case CalendarTrigger(source=source, match=match, before=before):
            start = calendars(source, after + before, match) if calendars else None
            return None if start is None else start - before
        case AtTrigger(when=when):
            return when.astimezone(UTC) if when > after else None
        case CountdownTrigger(armed_at=datetime() as armed_at, duration=duration):
            due = (armed_at + duration).astimezone(UTC)
            return due if due > after else None
        case CronTrigger(expr=expr):
            return _next_cron(expr, after, tz)
    return None


def _next_cron(expr: str, after: datetime, tz: tzinfo) -> datetime | None:
    # croniter walks naive wall-clock times; zoneinfo turns each one into an instant.
    wall = after.astimezone(tz).replace(tzinfo=None)
    candidates = croniter(expr, wall)
    try:
        for _ in range(_MAX_CRON_STEPS):
            candidate = candidates.get_next(datetime).replace(tzinfo=tz).astimezone(UTC)
            if candidate > after:  # skips second-pass times in a repeated hour
                return candidate
    except CroniterBadDateError:  # the expression never matches (e.g. 30 February)
        return None
    return None


@dataclass
class _Entry:
    rule: Rule
    tz: tzinfo
    due: datetime


class Scheduler:
    def __init__(
        self,
        clock: Clock,
        on_due: OnDue,
        *,
        grace: timedelta = MISSED_GRACE,
        max_sleep: float = MAX_SLEEP,
        calendars: CalendarLookup | None = None,
    ) -> None:
        self._clock = clock
        self._calendars = calendars
        self._on_due = on_due
        self._grace = grace
        self._max_sleep = max_sleep
        self._entries: dict[str, _Entry] = {}
        self._wakeup = asyncio.Event()

    def schedule(self, rule: Rule, tz: tzinfo, since: datetime | None = None) -> datetime | None:
        """(Re)schedule a rule and return its next fire.

        `since` is when the rule was last checked (default: now). If an occurrence fell
        between `since` and now, it fires right away, flagged as missed when late.
        """
        self._entries.pop(rule.id, None)
        after = since or self._clock.now()
        due = next_fire(rule.trigger, after, tz, self._calendars) if rule.enabled else None
        if due is not None:
            self._entries[rule.id] = _Entry(rule, tz, due)
        self.poke()
        return due

    def unschedule(self, rule_id: str) -> None:
        if self._entries.pop(rule_id, None) is not None:
            self.poke()

    def pending(self) -> dict[str, datetime]:
        return {rule_id: entry.due for rule_id, entry in self._entries.items()}

    def poke(self) -> None:
        """Check again now: rules changed or the machine resumed."""
        self._wakeup.set()

    async def run(self) -> None:
        while True:
            self._wakeup.clear()
            now = self._clock.now()
            self._fire_due(now)
            await self._sleep(self._delay(now))

    def _fire_due(self, now: datetime) -> None:
        due = sorted((e for e in self._entries.values() if e.due <= now), key=lambda e: e.due)
        for entry in due:
            if self._entries.get(entry.rule.id) is not entry:  # changed by an earlier callback
                continue
            scheduled = entry.due
            upcoming = next_fire(entry.rule.trigger, now, entry.tz, self._calendars)
            if upcoming is None:
                del self._entries[entry.rule.id]
            else:
                entry.due = upcoming
            try:
                self._on_due(entry.rule, scheduled, now - scheduled > self._grace)
            except Exception:
                log.exception("firing rule %s failed", entry.rule.id)

    def _delay(self, now: datetime) -> float:
        if not self._entries:
            return self._max_sleep
        earliest = min(entry.due for entry in self._entries.values())
        return min(self._max_sleep, max(0.0, (earliest - now).total_seconds()))

    async def _sleep(self, seconds: float) -> None:
        if self._wakeup.is_set():
            return
        sleeper = asyncio.ensure_future(self._clock.sleep(seconds))
        waker = asyncio.ensure_future(self._wakeup.wait())
        try:
            await asyncio.wait({sleeper, waker}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            waker.cancel()
