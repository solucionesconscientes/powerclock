import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from kse.engine.clock import FakeClock, settle
from kse.engine.scheduler import Scheduler
from kse.models import Rule
from support import MADRID, START, rule

Fired = list[tuple[str, datetime, bool]]


def at(delta: timedelta, rule_id: str = "test") -> Rule:
    return rule(id=rule_id, trigger={"type": "at", "when": (START + delta).isoformat()})


async def running(scheduler: Scheduler) -> AsyncIterator[Scheduler]:
    task = asyncio.create_task(scheduler.run())
    await settle()
    yield scheduler
    task.cancel()


@pytest.fixture
def fired() -> Fired:
    return []


@pytest.fixture
async def scheduler(clock: FakeClock, fired: Fired) -> AsyncIterator[Scheduler]:
    async for scheduler in running(
        Scheduler(clock, lambda r, when, missed: fired.append((r.id, when, missed)))
    ):
        yield scheduler


async def test_at_fires_on_time(scheduler: Scheduler, clock: FakeClock, fired: Fired) -> None:
    scheduler.schedule(at(timedelta(seconds=90)), MADRID)
    await clock.advance(89)
    assert fired == []
    await clock.advance(1)
    assert fired == [("test", START + timedelta(seconds=90), False)]
    assert scheduler.pending() == {}


async def test_sleeps_at_most_30_seconds(scheduler: Scheduler, clock: FakeClock) -> None:
    scheduler.schedule(at(timedelta(hours=1)), MADRID)
    await settle()
    wakeup = clock.next_wakeup()
    assert wakeup is not None
    assert wakeup <= 30


async def test_new_rules_wake_the_loop(
    scheduler: Scheduler, clock: FakeClock, fired: Fired
) -> None:
    await clock.advance(10)  # the loop is asleep for up to 30 s
    scheduler.schedule(at(timedelta(seconds=15)), MADRID)
    await clock.advance(5)
    assert [rule_id for rule_id, _, _ in fired] == ["test"]


async def test_disabled_and_non_time_rules_are_not_scheduled(scheduler: Scheduler) -> None:
    assert (
        scheduler.schedule(
            rule(enabled=False, trigger={"type": "cron", "expr": "0 3 * * *"}), MADRID
        )
        is None
    )
    assert (
        scheduler.schedule(rule(id="idle", trigger={"type": "idle", "for": "5m"}), MADRID) is None
    )
    assert scheduler.pending() == {}


async def test_unschedule(scheduler: Scheduler, clock: FakeClock, fired: Fired) -> None:
    scheduler.schedule(at(timedelta(minutes=1)), MADRID)
    scheduler.unschedule("test")
    await clock.advance(120)
    assert fired == []


async def test_clock_jump_forward_is_a_missed_fire(
    scheduler: Scheduler, clock: FakeClock, fired: Fired
) -> None:
    scheduler.schedule(at(timedelta(minutes=10)), MADRID)
    await clock.advance(5)
    clock.jump(3600)  # e.g. suspended for an hour
    await clock.advance(30)  # noticed at the next re-check, at most 30 s later
    assert fired == [("test", START + timedelta(minutes=10), True)]


async def test_a_little_late_is_not_missed(
    scheduler: Scheduler, clock: FakeClock, fired: Fired
) -> None:
    scheduler.schedule(at(timedelta(minutes=10)), MADRID)
    await clock.advance(5)
    clock.jump(11 * 60)  # one minute late: within the 2-minute grace
    await clock.advance(30)
    assert fired == [("test", START + timedelta(minutes=10), False)]


async def test_clock_jump_backward_does_not_fire_twice(
    scheduler: Scheduler, clock: FakeClock, fired: Fired
) -> None:
    scheduler.schedule(rule(trigger={"type": "cron", "expr": "0 * * * *"}), MADRID)
    await clock.advance(3600)  # fires at 09:00 UTC
    assert len(fired) == 1
    clock.jump(-600)  # NTP or a manual change moves the clock 10 minutes back
    await clock.advance(20 * 60)
    assert len(fired) == 1
    assert scheduler.pending() == {"test": START + timedelta(hours=2)}


async def test_since_detects_occurrences_missed_while_stopped(
    scheduler: Scheduler, clock: FakeClock, fired: Fired
) -> None:
    daily = rule(trigger={"type": "cron", "expr": "0 3 * * *"})
    scheduler.schedule(daily, MADRID, since=START - timedelta(days=2))
    await settle()
    # Two occurrences were missed; they are reported once and the rule moves on.
    assert fired == [("test", datetime(2026, 9, 23, 1, 0, tzinfo=UTC), True)]
    assert scheduler.pending() == {"test": datetime(2026, 9, 25, 1, 0, tzinfo=UTC)}


@pytest.mark.parametrize(
    ("start", "expr", "expected"),
    [
        # DST ends on 2026-10-25: 03:00 local is 01:00 UTC before, 02:00 UTC after
        (
            datetime(2026, 10, 24, 12, 0, tzinfo=UTC),
            "0 3 * * *",
            [datetime(2026, 10, d, 2, 0, tzinfo=UTC) for d in (25, 26, 27)],
        ),
        # DST starts on 2026-03-29: 02:30 does not exist and runs at 03:30 CEST
        (
            datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
            "30 2 * * *",
            [
                datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
                datetime(2026, 3, 30, 0, 30, tzinfo=UTC),
                datetime(2026, 3, 31, 0, 30, tzinfo=UTC),
            ],
        ),
    ],
    ids=["dst-end", "dst-start"],
)
async def test_cron_over_several_days_across_dst(
    start: datetime, expr: str, expected: list[datetime]
) -> None:
    clock = FakeClock(start)
    fired: Fired = []
    daily = Scheduler(
        clock, lambda r, when, missed: fired.append((r.id, when, missed)), max_sleep=3600
    )
    async for scheduler in running(daily):
        scheduler.schedule(rule(trigger={"type": "cron", "expr": expr}), MADRID)
        await clock.advance(3 * 86_400)
    assert fired == [("test", when, False) for when in expected]
