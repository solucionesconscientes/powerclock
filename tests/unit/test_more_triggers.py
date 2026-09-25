"""More triggers and conditions (M17): the sun, calendars, holidays, tariff periods, use of
the computer, files, devices and temperature."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import TypeAdapter

from powerclock.engine import Engine, calendar, holidays, sun, tariff
from powerclock.engine.clock import FakeClock
from powerclock.engine.evaluator import Evaluator
from powerclock.engine.scheduler import next_fire
from powerclock.models import CalendarTrigger, Predicate, SunTrigger
from powerclock.sensors.fake import FakeReadings, FakeSensors
from powerclock.sensors.registry import SensorHub
from support import MADRID, START, rule

PREDICATE: TypeAdapter[Predicate] = TypeAdapter(Predicate)


def p(**data: Any) -> Any:
    return PREDICATE.validate_python(data)


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=MADRID)


def near(moment: datetime | None, expected: datetime, minutes: float = 2) -> bool:
    return moment is not None and abs(moment - expected) <= timedelta(minutes=minutes)


# ── The sun ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("day", "event", "expected"),
    [
        (date(2026, 6, 21), "sunrise", local(2026, 6, 21, 6, 44)),
        (date(2026, 6, 21), "sunset", local(2026, 6, 21, 21, 48)),
        (date(2026, 12, 21), "sunrise", local(2026, 12, 21, 8, 34)),
        (date(2026, 12, 21), "sunset", local(2026, 12, 21, 17, 51)),
    ],
)
def test_sunrise_and_sunset_in_madrid(day: date, event: Any, expected: datetime) -> None:
    latitude, longitude = sun.zone_location("Europe/Madrid") or (0, 0)
    assert (round(latitude, 1), round(longitude, 1)) == (40.4, -3.7)  # from the tz database
    assert near(sun.sun_time(day, latitude, longitude, event), expected)


def test_polar_night_waits_for_the_first_sunrise() -> None:
    assert sun.sun_time(date(2026, 12, 21), 69.65, 18.96, "sunrise") is None  # Tromsø
    winter = START.replace(month=12, day=21)
    first = sun.next_sun(winter, "sunrise", timedelta(0), UTC, 69.65, 18.96)
    assert first is not None
    assert first.date() == date(2027, 1, 16)


def test_sun_trigger_uses_the_time_zone_city_and_the_offset() -> None:
    before_sunset = SunTrigger(event="sunset", offset_minutes=-30)
    due = next_fire(before_sunset, START, MADRID)  # Thursday 24 September, 10:00 in Madrid
    assert near(due, local(2026, 9, 24, 19, 40))
    assert due is not None
    assert due.microsecond == 0
    # the next one is tomorrow's, not the same one again
    assert near(next_fire(before_sunset, due, MADRID), local(2026, 9, 25, 19, 38))
    elsewhere = SunTrigger(event="sunrise", latitude=41.39, longitude=2.17)  # Barcelona
    assert near(next_fire(elsewhere, START, MADRID), local(2026, 9, 25, 7, 40))
    assert next_fire(SunTrigger(), START, UTC) is None  # no city for UTC: no place, no sun


def test_sun_trigger_needs_both_coordinates() -> None:
    with pytest.raises(ValueError, match="both"):
        SunTrigger(latitude=40.0)


# ── Holidays and tariff periods ───────────────────────────────────────────────


def test_easter_and_spanish_holidays() -> None:
    assert [holidays.easter(y) for y in (2025, 2026, 2027)] == [
        date(2025, 4, 20),
        date(2026, 4, 5),
        date(2027, 3, 28),
    ]
    assert holidays.is_holiday(date(2026, 4, 3))  # Good Friday
    assert holidays.is_holiday(date(2026, 10, 12))
    assert not holidays.is_holiday(date(2026, 9, 24))
    assert holidays.is_holiday(date(2026, 9, 11), extra=(date(2026, 9, 11),))  # a local one


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (local(2026, 9, 24, 7, 59), "valley"),  # Thursday
        (local(2026, 9, 24, 8, 0), "flat"),
        (local(2026, 9, 24, 10, 0), "peak"),
        (local(2026, 9, 24, 14, 30), "flat"),
        (local(2026, 9, 24, 21, 59), "peak"),
        (local(2026, 9, 24, 22, 0), "flat"),
        (local(2026, 9, 26, 12, 0), "valley"),  # Saturday
        (local(2026, 12, 8, 12, 0), "valley"),  # a national holiday on a Tuesday
    ],
)
def test_spanish_2_0td_periods(moment: datetime, expected: str) -> None:
    assert tariff.period("es-2.0td", moment) == expected


async def test_holiday_and_tariff_conditions() -> None:
    clock = FakeClock(datetime(2026, 12, 8, 11, 0, tzinfo=UTC))  # a holiday, 12:00 in Madrid
    chosen: list[Any] = [None]
    evaluator = Evaluator(FakeSensors(), clock, lambda: chosen[0])
    assert await evaluator.evaluate(p(type="holiday"), MADRID) is True
    valley = p(type="tariff_period", period="valley")
    assert await evaluator.evaluate(valley, MADRID) is None  # no tariff chosen: unknown
    chosen[0] = "es-2.0td"
    assert await evaluator.evaluate(valley, MADRID) is True
    await clock.advance(86400)  # Wednesday 9, 12:00: peak
    assert await evaluator.evaluate(p(type="holiday"), MADRID) is False
    assert await evaluator.evaluate(p(type="holiday", extra=["2026-12-09"]), MADRID) is True
    assert await evaluator.evaluate(valley, MADRID) is False
    assert await evaluator.evaluate(p(type="tariff_period", period="peak"), MADRID) is True


# ── Calendars ─────────────────────────────────────────────────────────────────

ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "SUMMARY:Dentist",
        "DTSTART;TZID=Europe/Madrid:20260925T170000",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Stand-up meeting with the team\\, every",
        "  weekday",  # a folded line
        "DTSTART;TZID=Europe/Madrid:20261022T090000",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,TH;COUNT=4",
        "EXDATE;TZID=Europe/Madrid:20261026T090000",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Cancelled meeting",
        "DTSTART:20260924T120000Z",
        "STATUS:CANCELLED",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Holidays",
        "DTSTART;VALUE=DATE:20261001",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Rent",
        "DTSTART:20260131T080000Z",
        "RRULE:FREQ=MONTHLY;UNTIL=20260601T000000Z",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)


def test_ics_events_and_repetitions() -> None:
    events = calendar.parse(ICS, MADRID)
    by_title = {event.summary.split(" ")[0]: event for event in events}
    assert set(by_title) == {"Dentist", "Stand-up", "Holidays", "Rent"}  # not the cancelled
    assert by_title["Stand-up"].summary == "Stand-up meeting with the team, every weekday"
    assert by_title["Holidays"].start == local(2026, 10, 1)  # all day: local midnight
    standup = list(by_title["Stand-up"].occurrences(START, START + timedelta(days=60)))
    # Thu 22, (Mon 26 excluded), Thu 29 and Mon 2 November: still 09:00 after the DST change
    assert standup == [local(2026, 10, 22, 9), local(2026, 10, 29, 9), local(2026, 11, 2, 9)]
    rent = list(by_title["Rent"].occurrences(datetime(2026, 1, 1, tzinfo=UTC), START))
    assert [moment.month for moment in rent] == [1, 3, 5]  # no 31st in February, April…


def test_next_event_start_by_title() -> None:
    events = calendar.parse(ICS, MADRID)
    assert calendar.next_start(events, START) == local(2026, 9, 25, 17)
    assert calendar.next_start(events, START, "stand-up") == local(2026, 10, 22, 9)
    assert calendar.next_start(events, START, "nothing like this") is None


def test_calendar_trigger_fires_before_the_event() -> None:
    events = calendar.parse(ICS, MADRID)

    def lookup(source: str, after: datetime, match: str | None) -> datetime | None:
        assert source == "work.ics"
        return calendar.next_start(events, after, match)

    trigger = CalendarTrigger(source="work.ics", match="Dentist", before=timedelta(minutes=45))
    due = next_fire(trigger, START, MADRID, lookup)
    assert due == local(2026, 9, 25, 16, 15)
    assert next_fire(trigger, due, MADRID, lookup) is None  # it was the only one
    assert next_fire(trigger, START, MADRID) is None  # calendars not read yet


async def test_calendars_are_read_from_files_and_addresses(tmp_path: Path) -> None:
    (tmp_path / "home.ics").write_text(ICS, encoding="utf-8")
    served: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        served.append(str(request.url))
        if request.url.path == "/missing.ics":
            return httpx.Response(404)
        return httpx.Response(200, text=ICS)

    changes: list[bool] = []
    calendars = calendar.Calendars(
        MADRID,
        on_change=lambda: changes.append(True),
        client=lambda: httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    )
    home, work, missing = (
        str(tmp_path / "home.ics"),
        "webcal://example.org/work.ics",
        "https://example.org/missing.ics",
    )
    calendars.use([home, work, missing])
    await calendars.refresh()
    assert changes == [True]
    assert sorted(served) == ["https://example.org/missing.ics", "https://example.org/work.ics"]
    assert calendars.next_start(work, START, "dentist") == local(2026, 9, 25, 17)
    assert calendars.next_start(home, START, None) == local(2026, 9, 25, 17)
    assert set(calendars.errors) == {missing}
    await calendars.refresh()
    assert changes == [True]  # nothing new
    calendars.use([home])
    assert set(calendars.events) == {home}


async def test_a_calendar_rule_is_scheduled_once_its_calendar_is_read(
    engine: Engine, tmp_path: Path
) -> None:
    source = tmp_path / "agenda.ics"
    source.write_text(ICS, encoding="utf-8")
    trigger = {"type": "calendar", "source": str(source), "match": "dentist", "before": "1h"}
    engine.upsert(rule(trigger=trigger))
    for _ in range(200):  # the calendar is read in the background
        if engine.pending():
            break
        await asyncio.sleep(0.01)
    assert engine.pending() == {"test": local(2026, 9, 25, 16)}


# ── Use of the computer, files, devices, temperature ──────────────────────────


@pytest.fixture
def hub(readings: FakeReadings, clock: FakeClock) -> SensorHub:
    return SensorHub(readings, clock, tz=MADRID)


async def poll(hub: SensorHub, clock: FakeClock, seconds: float, step: float = 5.0) -> None:
    elapsed = 0.0
    while elapsed < seconds:
        await hub.sample()
        await clock.advance(step)
        elapsed += step
    await hub.sample()


async def test_active_asks_for_a_break(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    active = p(type="active", **{"for": "50m"}, pause="5m")
    hub.demand([active])
    readings.idle_seconds = 3.0
    await poll(hub, clock, 49 * 60)
    assert await hub.check(active) is None  # not 50 minutes of history yet
    await poll(hub, clock, 60)
    assert await hub.check(active) is True
    readings.idle_seconds = 400.0  # a break longer than 5 minutes
    await poll(hub, clock, 5)
    assert await hub.check(active) is False


async def test_used_today_adds_up_time_in_use(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    used = p(type="used_today", **{"for": "1h"})
    hub.demand([used])
    readings.idle_seconds = 10.0
    await poll(hub, clock, 40 * 60)
    readings.idle_seconds = 900.0  # away: not counted
    await poll(hub, clock, 30 * 60)
    assert await hub.check(used) is False
    assert timedelta(minutes=39) <= hub.used_today() <= timedelta(minutes=41)
    readings.idle_seconds = 1.0
    await poll(hub, clock, 21 * 60)
    assert await hub.check(used) is True
    assert hub.measure(used)[0] == pytest.approx(hub.used_today().total_seconds())
    await clock.advance(24 * 3600)  # a new day starts from zero
    await poll(hub, clock, 5)
    assert hub.used_today() <= timedelta(seconds=10)


async def test_file_device_and_temperature_checks(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock, tmp_path: Path
) -> None:
    pdfs = p(type="file", path=str(tmp_path), pattern="*.pdf")
    flag = p(type="file", path=str(tmp_path / "done.flag"))
    assert await hub.check(pdfs) is False
    assert await hub.check(flag) is False
    (tmp_path / "invoice.PDF.pdf").write_text("x")
    (tmp_path / "done.flag").write_text("")
    await clock.advance(5)
    assert await hub.check(pdfs) is True
    assert await hub.check(flag) is True

    stick = p(type="device", name="sandisk")
    assert await hub.check(stick) is False
    readings.connected = ["SanDisk Cruzer Blade", "BACKUP"]
    await clock.advance(5)
    assert await hub.check(stick) is True
    assert hub.measure(stick) == ("connected", None)
    readings.connected = None
    await clock.advance(5)
    assert await hub.check(stick) is None

    hot = p(type="temperature", above=80)
    nvme = p(type="temperature", above=60, sensor="nvme")
    readings.temps = {"coretemp": 85.0, "nvme": 50.0}
    assert await hub.check(hot) is True
    assert await hub.check(nvme) is False
    assert hub.measure(hot) == (85.0, None)
    readings.temps = None
    await clock.advance(10)
    assert await hub.check(hot) is None


def test_new_state_triggers_are_watched() -> None:
    from powerclock.engine.watcher import STATE_TRIGGERS

    for kind in ("active", "used_today", "file", "device", "temperature", "wifi_ssid"):
        trigger = rule(trigger={"type": kind, **_required(kind)}).trigger
        assert isinstance(trigger, STATE_TRIGGERS), kind


def _required(kind: str) -> dict[str, Any]:
    return {
        "active": {"for": "50m"},
        "used_today": {"for": "2h"},
        "file": {"path": "~/Downloads"},
        "device": {"name": "SanDisk"},
        "temperature": {"above": 85},
        "wifi_ssid": {"ssid": "Casa"},
    }[kind]


def test_zone_for_rules_elsewhere() -> None:
    tokyo = ZoneInfo("Asia/Tokyo")
    due = next_fire(SunTrigger(event="sunrise"), START, tokyo)
    assert due is not None
    assert due.astimezone(tokyo).hour in (5, 6)
