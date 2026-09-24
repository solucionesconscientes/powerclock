from datetime import UTC, datetime, timedelta

import pytest

from powerclock.engine import Engine
from powerclock.engine.clock import FakeClock, settle
from powerclock.engine.runs import Event
from powerclock.models import CountdownTrigger
from powerclock.platform.base import PowerAction, PowerEvent
from powerclock.platform.fake import FakePlatform
from support import MADRID, START, rule

SHUTDOWN = {"type": "power", "action": "shutdown"}


def changed(events: list[Event]) -> list[str | None]:
    return [event.rule_id for event in events if event.type == "rule_changed"]


async def test_cron_rule_runs_on_schedule(
    engine: Engine, fake: FakePlatform, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger={"type": "cron", "expr": "0 11 * * *"}))  # 11:00 Madrid
    assert engine.pending() == {"test": datetime(2026, 9, 24, 9, 0, tzinfo=UTC)}
    await clock.advance(3600)
    [run] = engine.executor.recent
    assert (run.cause, run.state, run.missed) == ("schedule", "done", False)
    assert run.scheduled_for == datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    assert fake.calls_to("notify")
    assert engine.pending() == {"test": datetime(2026, 9, 25, 9, 0, tzinfo=UTC)}


async def test_rule_time_zone_overrides_the_default(engine: Engine) -> None:
    engine.upsert(rule(timezone="UTC", trigger={"type": "cron", "expr": "0 11 * * *"}))
    assert engine.pending() == {"test": datetime(2026, 9, 24, 11, 0, tzinfo=UTC)}


async def test_countdown_one_shot(
    engine: Engine, fake: FakePlatform, clock: FakeClock, events: list[Event]
) -> None:
    stored = engine.upsert(
        rule(
            trigger={"type": "countdown", "duration": "30m"},
            one_shot=True,
            warning="60s",
            actions=[SHUTDOWN],
        )
    )
    assert isinstance(stored.trigger, CountdownTrigger)
    assert stored.trigger.armed_at == START
    assert changed(events) == ["test"]  # armed: the daemon must save it
    await clock.advance(30 * 60)
    assert engine.rules["test"].enabled is False  # one-shot: done after firing
    assert changed(events) == ["test", "test"]
    assert engine.pending() == {}
    await clock.advance(60)
    assert [call.args[0] for call in fake.calls_to("power")] == [PowerAction.SHUTDOWN]


async def test_countdown_rearms_when_enabled_again(engine: Engine, clock: FakeClock) -> None:
    countdown = {"type": "countdown", "duration": "30m"}
    engine.upsert(rule(trigger=countdown))
    await clock.advance(600)
    disabled = engine.upsert(engine.rules["test"].model_copy(update={"enabled": False}))
    assert engine.pending() == {}
    await clock.advance(600)
    enabled = engine.upsert(disabled.model_copy(update={"enabled": True}))
    assert isinstance(enabled.trigger, CountdownTrigger)
    assert enabled.trigger.armed_at == START + timedelta(minutes=20)
    assert engine.pending() == {"test": START + timedelta(minutes=50)}


@pytest.mark.parametrize(("on_missed", "state"), [("skip", "skipped"), ("run_once", "done")])
async def test_missed_occurrences(
    engine: Engine, fake: FakePlatform, on_missed: str, state: str
) -> None:
    daily = rule(on_missed=on_missed, trigger={"type": "cron", "expr": "0 3 * * *"})
    engine.upsert(daily, since=START - timedelta(days=1))  # the daemon was stopped
    await settle()
    [run] = engine.executor.recent
    assert run.missed
    assert run.state == state
    assert bool(fake.calls_to("notify")) is (on_missed == "run_once")


async def test_resume_checks_the_schedule_at_once(
    engine: Engine, fake: FakePlatform, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger={"type": "at", "when": (START + timedelta(minutes=10)).isoformat()}))
    await clock.advance(5)
    clock.jump(3600)  # suspended for an hour; the monotonic clock did not move
    await fake.emit(PowerEvent.AFTER_RESUME)
    await settle()
    [run] = engine.executor.recent
    assert (run.missed, run.state) == (True, "skipped")


async def test_run_now(engine: Engine, fake: FakePlatform) -> None:
    engine.upsert(rule(enabled=False))
    run = engine.run_now("test")
    run = await engine.executor.wait(run.id)
    assert (run.cause, run.state) == ("manual", "done")
    with pytest.raises(KeyError):
        engine.run_now("missing")


async def test_remove(engine: Engine, clock: FakeClock) -> None:
    engine.upsert(rule(trigger={"type": "cron", "expr": "0 11 * * *"}))
    engine.remove("test")
    await clock.advance(3600)
    assert engine.rules == {}
    assert list(engine.executor.recent) == []


async def test_stop_cancels_active_runs(engine: Engine) -> None:
    engine.upsert(rule(actions=[{"type": "wait", "duration": "1h"}]))
    run = engine.run_now("test")
    await settle()
    await engine.stop()
    assert run.state == "cancelled"


async def test_engine_without_power_events(clock: FakeClock) -> None:
    from powerclock.platform.base import Capability, PlatformBackend, PowerMode

    class Minimal(PlatformBackend):
        name = "minimal"

        async def power(self, action: PowerAction, mode: PowerMode) -> None:
            pass

        async def capabilities(self) -> list[Capability]:
            return []

    engine = Engine(Minimal(), tz=MADRID, clock=clock)
    await engine.start()  # NotSupported for power events is not an error
    await engine.stop()
