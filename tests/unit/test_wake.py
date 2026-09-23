import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest

from kse.engine import Engine
from kse.engine.clock import FakeClock, settle
from kse.engine.runs import Event
from kse.engine.wake import WakePlanner
from kse.platform.base import NotSupported, PowerEvent
from kse.platform.fake import FakePlatform
from support import MADRID, START, rule


class Times:
    def __init__(self) -> None:
        self.values: list[datetime] = []

    def __call__(self) -> list[datetime]:
        return list(self.values)


@pytest.fixture
def times() -> Times:
    return Times()


@pytest.fixture
async def planner(
    fake: FakePlatform, clock: FakeClock, times: Times, events: list[Event]
) -> AsyncIterator[WakePlanner]:
    planner = WakePlanner(fake, clock, times, emit=events.append)
    yield planner
    await planner._release()


def wake_calls(fake: FakePlatform) -> list[tuple[str, tuple[object, ...]]]:
    return [(c.method, c.args) for c in fake.calls if c.method in ("wake_set", "wake_clear")]


async def test_alarm_goes_two_minutes_before_the_earliest_wake(
    planner: WakePlanner, fake: FakePlatform, times: Times, events: list[Event]
) -> None:
    times.values = [START + timedelta(hours=3), START + timedelta(hours=1)]
    await planner.sync()
    expected = START + timedelta(hours=1) - timedelta(minutes=2)
    assert fake.wake == expected
    assert planner.target == expected
    assert fake.inhibited  # logind will wait for us before sleeping
    assert [e.data for e in events if e.type == "wake_changed"] == [{"at": expected.isoformat()}]
    await planner.sync()  # nothing changed: nothing written
    assert len(wake_calls(fake)) == 1


async def test_close_wakes_are_never_in_the_past(
    planner: WakePlanner, fake: FakePlatform, times: Times
) -> None:
    times.values = [START + timedelta(seconds=30), START - timedelta(minutes=5)]
    await planner.sync()
    assert fake.wake == START + timedelta(seconds=10)


async def test_whole_seconds(planner: WakePlanner, fake: FakePlatform, times: Times) -> None:
    times.values = [START + timedelta(hours=1, microseconds=250_000)]
    await planner.sync()
    assert fake.wake == START + timedelta(minutes=58)


async def test_clears_only_its_own_alarm(
    planner: WakePlanner, fake: FakePlatform, times: Times
) -> None:
    times.values = [START + timedelta(hours=1)]
    await planner.sync()
    times.values = []
    await planner.sync()
    assert fake.wake is None
    assert not fake.inhibited
    fake.wake = START + timedelta(hours=5)  # somebody else's (e.g. rtcwake by hand)
    await planner.sync(rewrite=True)
    assert fake.wake == START + timedelta(hours=5)


async def test_keeps_an_earlier_foreign_alarm(
    planner: WakePlanner, fake: FakePlatform, times: Times
) -> None:
    fake.wake = START + timedelta(minutes=2)  # kse doctor --test-wake
    times.values = [START + timedelta(hours=1)]
    await planner.sync()
    assert fake.wake == START + timedelta(minutes=2)
    assert planner.target is None
    fake.wake = START + timedelta(hours=9)  # a later foreign alarm is replaced
    await planner.sync()
    assert fake.wake == START + timedelta(minutes=58)


async def test_errors_are_kept_and_retried(
    planner: WakePlanner, fake: FakePlatform, times: Times, events: list[Event]
) -> None:
    async def refuse(when: datetime) -> None:
        raise NotSupported("wake", "kse-helper is not installed", fix_hint="kse helper install")

    original = fake.wake_set
    fake.wake_set = refuse  # type: ignore[method-assign]
    times.values = [START + timedelta(hours=1)]
    await planner.sync()
    assert planner.error == "wake: kse-helper is not installed (kse helper install)"
    assert planner.target is None
    assert events[-1].data["error"] == planner.error
    fake.wake_set = original  # type: ignore[method-assign]
    await planner.sync()
    assert planner.error is None
    assert fake.wake == START + timedelta(minutes=58)


async def test_before_sleep_rewrites_and_lets_go(
    planner: WakePlanner, fake: FakePlatform, times: Times
) -> None:
    times.values = [START + timedelta(hours=1)]
    await planner.sync()
    fake.wake = None  # e.g. the firmware lost it
    await planner.on_power_event(PowerEvent.BEFORE_SLEEP)
    assert fake.wake == START + timedelta(minutes=58)
    assert not fake.inhibited  # the suspend can go on
    await planner.on_power_event(PowerEvent.BEFORE_SHUTDOWN)
    assert len(wake_calls(fake)) == 3  # rewritten every time


async def test_after_resume_it_checks_again(
    fake: FakePlatform, clock: FakeClock, times: Times
) -> None:
    planner = WakePlanner(fake, clock, times)
    task = asyncio.create_task(planner.run())
    times.values = [START + timedelta(hours=1)]
    planner.request_sync()
    await settle()
    assert fake.wake == START + timedelta(minutes=58)
    fake.wake = None  # the alarm fired and was consumed
    await planner.on_power_event(PowerEvent.AFTER_RESUME)
    await settle()
    assert fake.wake == START + timedelta(minutes=58)
    task.cancel()
    await settle()
    assert not fake.inhibited  # stopping releases the inhibitor, but keeps the alarm
    assert fake.wake is not None


# ── With the engine ────────────────────────────────────────────────────────


async def test_engine_programs_wake_rules(
    engine: Engine, fake: FakePlatform, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger={"type": "cron", "expr": "0 11 * * *"}, wake=True))  # 09:00 UTC
    engine.upsert(rule(id="no-wake", trigger={"type": "cron", "expr": "30 10 * * *"}))
    await settle()
    assert fake.wake == datetime(2026, 9, 24, 8, 58, tzinfo=START.tzinfo)
    await clock.advance(3600)  # it fires; the next one is tomorrow
    await settle()
    assert fake.wake == datetime(2026, 9, 25, 8, 58, tzinfo=START.tzinfo)
    engine.remove("test")
    await settle()
    assert fake.wake is None


async def test_engine_forwards_power_events(engine: Engine, fake: FakePlatform) -> None:
    engine.upsert(rule(trigger={"type": "cron", "expr": "0 11 * * *"}, wake=True))
    await settle()
    fake.wake = None
    await fake.emit(PowerEvent.BEFORE_SHUTDOWN)
    assert fake.wake is not None


async def test_set_wake_action_asks_the_daemon(fake: FakePlatform, clock: FakeClock) -> None:
    requested: list[datetime] = []

    async def request_wake(when: datetime) -> None:
        requested.append(when)

    engine = Engine(fake, tz=MADRID, clock=clock, request_wake=request_wake)
    await engine.start()
    engine.upsert(rule(actions=[{"type": "set_wake", "after": "8h"}]))
    run = engine.run_now("test")
    await engine.executor.wait(run.id)
    assert requested == [START + timedelta(hours=8)]
    await engine.stop()
