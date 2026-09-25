"""Calendars (the calendar trigger): events read from an iCalendar (.ics) address or file,
refreshed every few minutes, and their next start.

Supports what calendars export for meetings: single events, all-day events, time zones by
TZID, cancelled events, EXDATE and RRULE with FREQ DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL,
COUNT, UNTIL and (weekly) BYDAY. Without internet the last copy is used.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

log = logging.getLogger(__name__)

REFRESH = 900.0  # seconds between readings of each calendar
HORIZON = timedelta(days=400)  # how far ahead repeated events are expanded
DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass(frozen=True)
class Event:
    start: datetime  # UTC; all-day events start at midnight of the calendar's zone
    summary: str
    rule: dict[str, str] = field(default_factory=dict)  # RRULE parts
    exdates: frozenset[datetime] = frozenset()
    zone: tzinfo = UTC  # repetitions keep the wall-clock time of this zone (across DST)

    def occurrences(self, after: datetime, until: datetime) -> Iterator[datetime]:
        """Starts in (after, until], in order."""
        for moment in _expand(self):
            if moment > until:
                return
            if moment > after and moment not in self.exdates:
                yield moment


def parse(text: str, default_tz: tzinfo = UTC) -> list[Event]:
    events: list[Event] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    exdates: list[datetime] = []
    for line in _unfold(text):
        name, params, value = _property(line)
        if name == "BEGIN" and value == "VEVENT":
            current, exdates = {}, []
        elif name == "END" and value == "VEVENT" and current is not None:
            event = _event(current, exdates, default_tz)
            if event is not None:
                events.append(event)
            current = None
        elif current is not None:
            if name == "EXDATE":
                exdates += [_moment(v, params, default_tz) for v in value.split(",") if v]
            else:
                current.setdefault(name, (params, value))
    return events


def next_start(
    events: Iterable[Event], after: datetime, match: str | None = None
) -> datetime | None:
    """The first start after `after` of an event whose title contains `match`."""
    wanted = (match or "").lower()
    best: datetime | None = None
    for event in events:
        if wanted and wanted not in event.summary.lower():
            continue
        for moment in event.occurrences(after, after + HORIZON):
            if best is None or moment < best:
                best = moment
            break
    return best


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _property(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *raw_params = head.split(";")
    params = dict(p.partition("=")[::2] for p in raw_params)
    return name.upper(), {k.upper(): v for k, v in params.items()}, value.strip()


def _event(
    props: dict[str, tuple[dict[str, str], str]], exdates: list[datetime], default_tz: tzinfo
) -> Event | None:
    if "DTSTART" not in props or props.get("STATUS", ({}, ""))[1].upper() == "CANCELLED":
        return None
    params, value = props["DTSTART"]
    try:
        start = _moment(value, params, default_tz)
    except ValueError:
        return None
    zone = UTC if value.endswith("Z") else _zone(params, default_tz)
    rule = {}
    if "RRULE" in props:
        rule = dict(part.partition("=")[::2] for part in props["RRULE"][1].split(";") if part)
    summary = props.get("SUMMARY", ({}, ""))[1].replace("\\,", ",").replace("\\n", " ")
    return Event(start, summary, rule, frozenset(exdates), zone)


def _moment(value: str, params: dict[str, str], default_tz: tzinfo) -> datetime:
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        return datetime(day.year, day.month, day.day, tzinfo=default_tz).astimezone(UTC)
    naive = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return naive.replace(tzinfo=UTC)
    return naive.replace(tzinfo=_zone(params, default_tz)).astimezone(UTC)


def _zone(params: dict[str, str], default_tz: tzinfo) -> tzinfo:
    if "TZID" in params:
        try:
            return ZoneInfo(params["TZID"].strip('"'))
        except (ZoneInfoNotFoundError, ValueError):
            pass  # e.g. an Outlook zone name: the rule's zone is a fair guess
    return default_tz


def _expand(event: Event) -> Iterator[datetime]:
    """The event's starts in order: once, or following its RRULE."""
    rule = event.rule
    if not rule:
        yield event.start
        return
    frequency = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = _until(rule.get("UNTIL"))
    by_day = [DAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in DAYS]
    produced = 0
    local = event.start.astimezone(event.zone).replace(tzinfo=None)  # wall-clock time
    for index in range(100_000):
        if frequency == "DAILY":
            candidates = [local + timedelta(days=interval * index)]
        elif frequency == "WEEKLY":
            week = local + timedelta(weeks=interval * index)
            if by_day:
                monday = week - timedelta(days=week.weekday())
                candidates = sorted(monday + timedelta(days=d) for d in by_day)
                candidates = [c for c in candidates if c >= local]
            else:
                candidates = [week]
        elif frequency in ("MONTHLY", "YEARLY"):
            months = interval * index * (12 if frequency == "YEARLY" else 1)
            month = local.month - 1 + months
            try:
                candidates = [local.replace(year=local.year + month // 12, month=month % 12 + 1)]
            except ValueError:  # the 31st in a short month: skipped, as RFC 5545 says
                candidates = []
        else:
            yield event.start
            return
        for wall in candidates:
            candidate = wall.replace(tzinfo=event.zone).astimezone(UTC)
            if until is not None and candidate > until:
                return
            yield candidate
            produced += 1
            if count is not None and produced >= count:
                return


def _until(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _moment(value, {}, UTC)
    except ValueError:
        return None


# ── The cache the scheduler asks ─────────────────────────────────────────────


class Calendars:
    """The events of every calendar in use, read now and then; `changed` is called when
    a calendar's events change (the scheduler recomputes its rules)."""

    def __init__(
        self,
        tz: tzinfo,
        on_change: Callable[[], None],
        client: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._tz = tz
        self._on_change = on_change
        self._client = client or (lambda: httpx.AsyncClient(timeout=30, follow_redirects=True))
        self.events: dict[str, list[Event]] = {}
        self.errors: dict[str, str] = {}
        self._sources: set[str] = set()

    def use(self, sources: Iterable[str]) -> None:
        """The calendars the enabled rules need; new ones are read on the next refresh."""
        self._sources = set(sources)
        for gone in set(self.events) - self._sources:
            del self.events[gone]

    def next_start(self, source: str, after: datetime, match: str | None) -> datetime | None:
        return next_start(self.events.get(source, []), after, match)

    async def refresh(self) -> None:
        changed = False
        for source in sorted(self._sources):
            try:
                text = await self._read(source)
            except (OSError, httpx.HTTPError, ValueError) as exc:
                self.errors[source] = str(exc) or type(exc).__name__
                log.warning("calendar %s: %s", source, exc)
                continue
            self.errors.pop(source, None)
            events = parse(text, self._tz)
            if events != self.events.get(source):
                self.events[source] = events
                changed = True
        if changed:
            self._on_change()

    async def _read(self, source: str) -> str:
        if source.startswith(("https://", "http://", "webcal://")):
            url = source.replace("webcal://", "https://", 1)
            async with self._client() as http:
                reply = await http.get(url)
                reply.raise_for_status()
                return reply.text
        return await asyncio.to_thread(_read_file, source)


def _read_file(source: str) -> str:
    return Path(source).expanduser().read_text(encoding="utf-8")
