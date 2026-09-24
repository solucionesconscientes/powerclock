"""State and startup triggers, sensors on demand and guards, through the engine with fake
sensors (FakeReadings) and a fake clock."""

from collections.abc import Callable
from typing import Any

import pytest

from powerclock.engine import Engine
from powerclock.engine.clock import FakeClock, settle
from powerclock.platform.base import PowerEvent
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.base import PowerState
from powerclock.sensors.fake import FakeReadings
from support import MADRID, rule

IDLE_20M = {"type": "idle", "for": "20m"}


def fired(engine: Engine) -> int:
    """Runs started by a state or startup trigger."""
    return sum(1 for run in engine.executor.recent if run.cause == "trigger")


def watching(engine: Engine) -> dict[str, Any]:
    [status] = engine.watching()
    return status.model_dump()


# ── State triggers ────────────────────────────────────────────────────────────


async def test_idle_fires_once_until_the_user_comes_back(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger=IDLE_20M))
    readings.idle_seconds = 1195
    await clock.advance(5)
    assert fired(engine) == 0
    readings.idle_seconds = 1200
    await clock.advance(5)
    assert fired(engine) == 1
    readings.idle_seconds = 3000  # still idle: it does not fire again
    await clock.advance(600)
    assert fired(engine) == 1
    assert watching(engine)["armed"] is False
    readings.idle_seconds = 2  # the user is back
    await clock.advance(5)
    readings.idle_seconds = 1200
    await clock.advance(5)
    assert fired(engine) == 2
    first = engine.executor.recent[0]
    assert (first.state, first.scheduled_for) == ("done", None)


async def test_unknown_neither_fires_nor_rearms(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.idle_seconds = 1300
    engine.upsert(rule(trigger=IDLE_20M))
    await clock.advance(5)
    assert fired(engine) == 1
    readings.idle_seconds = None  # e.g. the session is locked and cannot tell
    await clock.advance(10)
    readings.idle_seconds = 1300
    await clock.advance(10)
    assert fired(engine) == 1


async def test_process_exit_waits_for_the_process_to_start(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger={"type": "process_exit", "name": "ffmpeg"}, one_shot=True))
    await clock.advance(30)
    assert fired(engine) == 0  # not running: never taken as finished
    assert watching(engine)["value"] == "not_seen"
    readings.start("ffmpeg", pid=100)
    await clock.advance(3)
    assert watching(engine) | {"checked_at": None} == {
        "rule_id": "test",
        "name": "Test",
        "trigger": {"type": "process_exit", "name": "ffmpeg", "pid": None},
        "state": False,
        "armed": True,
        "value": "running",
        "measured": None,
        "checked_at": None,
    }
    readings.start("ffmpeg", pid=101)
    readings.stop(100)
    await clock.advance(3)
    assert fired(engine) == 0  # another ffmpeg is still running
    readings.stop(101)
    await clock.advance(3)
    assert fired(engine) == 1
    assert engine.rules["test"].enabled is False  # one-shot
    assert engine.watching() == []


async def test_process_exit_by_pid_notices_a_reused_pid(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.start("render", pid=200, started=1.0)
    engine.upsert(rule(trigger={"type": "process_exit", "pid": 200}))
    await clock.advance(3)
    assert fired(engine) == 0
    readings.stop(200)
    readings.start("bash", pid=200, started=99.0)  # another process got the same PID
    await clock.advance(3)
    assert fired(engine) == 1


async def test_a_new_version_of_the_rule_keeps_what_was_seen(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    trigger = {"type": "process_exit", "name": "ffmpeg"}
    engine.upsert(rule(trigger=trigger))
    readings.start("ffmpeg", pid=100)
    await clock.advance(3)
    engine.upsert(rule(trigger=trigger, name="Renamed"))
    readings.stop(100)
    await clock.advance(3)
    assert fired(engine) == 1
    readings.start("ffmpeg", pid=101)
    await clock.advance(3)
    engine.upsert(rule(trigger={"type": "process_exit", "name": "blender"}))
    assert watching(engine)["value"] == "not_seen"  # another trigger starts afresh


async def test_cpu_below_fires_after_its_window(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.cpu_percent = 80.0
    engine.upsert(rule(trigger={"type": "cpu_below", "percent": 10, "for": "5m"}))
    await clock.advance(600)
    readings.cpu_percent = 2.0  # the render is over
    await clock.advance(260)
    assert fired(engine) == 0  # the 5-minute average is still too high
    status = watching(engine)
    assert status["value"] > 10
    assert status["measured"] == 300
    await clock.advance(15)
    assert fired(engine) == 1


async def test_net_below_when_the_download_ends(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.set_net(down_kbps=8000.0, up_kbps=100.0)
    net = {"type": "net_below", "kbps": 50, "for": "5m", "direction": "down"}
    engine.upsert(rule(trigger=net))
    await clock.advance(120)
    assert watching(engine)["measured"] == 120  # still measuring
    await clock.advance(480)
    readings.set_net(down_kbps=1.0, up_kbps=100.0)
    await clock.advance(295)
    assert fired(engine) == 0
    await clock.advance(5)
    assert fired(engine) == 1


async def test_battery_already_low_fires_at_once(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.power_state = PowerState(percent=10.0, on_ac=False)
    engine.upsert(rule(trigger={"type": "battery", "below": 15}))
    await settle()
    assert fired(engine) == 1
    assert watching(engine)["value"] == 10.0
    readings.power_state = PowerState(percent=40.0, on_ac=True)  # charged
    await clock.advance(5)
    readings.power_state = PowerState(percent=14.0, on_ac=False)
    await clock.advance(5)
    assert fired(engine) == 2


async def test_power_source_unplugged_for_a_minute(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    engine.upsert(rule(trigger={"type": "power_source", "is": "battery", "for": "1m"}))
    await clock.advance(30)
    readings.power_state = PowerState(percent=80.0, on_ac=False)
    await clock.advance(55)
    assert fired(engine) == 0
    assert watching(engine)["value"] == "battery"
    await clock.advance(10)
    assert fired(engine) == 1


# ── Startup trigger ───────────────────────────────────────────────────────────


async def test_startup_trigger(
    fake: FakePlatform, readings: FakeReadings, clock: FakeClock
) -> None:
    engine = Engine(fake, tz=MADRID, clock=clock, readings=readings)
    boot = {"type": "startup", "on": ["daemon_start"], "delay": "30s"}
    engine.upsert(rule(id="boot", trigger=boot))
    engine.upsert(rule(id="resume", trigger={"type": "startup", "on": ["resume"]}))
    engine.upsert(rule(id="off", trigger={"type": "startup"}, enabled=False))
    await engine.start()
    try:
        await clock.advance(29)
        assert fired(engine) == 0
        await clock.advance(1)
        assert [run.rule_id for run in engine.executor.recent] == ["boot"]
        await fake.emit(PowerEvent.AFTER_RESUME)
        await settle()
        assert [run.rule_id for run in engine.executor.recent] == ["boot", "resume"]
        engine.upsert(rule(id="late", trigger={"type": "startup"}))
        await clock.advance(60)
        assert fired(engine) == 2  # added later: it waits for the next start or resume
    finally:
        await engine.stop()


async def test_startup_rule_disabled_during_its_delay(
    fake: FakePlatform, readings: FakeReadings, clock: FakeClock
) -> None:
    engine = Engine(fake, tz=MADRID, clock=clock, readings=readings)
    engine.upsert(rule(trigger={"type": "startup", "delay": "1m"}))
    await engine.start()
    try:
        engine.upsert(rule(trigger={"type": "startup", "delay": "1m"}, enabled=False))
        await clock.advance(120)
        assert fired(engine) == 0
    finally:
        await engine.stop()


# ── Sensors on demand ─────────────────────────────────────────────────────────


async def test_only_the_sensors_in_use_are_sampled(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    guards = {"any": [{"type": "process_running", "name": "ffmpeg"}]}
    engine.upsert(rule(id="backup", trigger={"type": "cron", "expr": "0 3 * * *"}, guards=guards))
    await clock.advance(600)
    assert readings.reads == {}  # that guard is read when the rule fires, not before
    engine.upsert(rule(id="idle", trigger=IDLE_20M))
    await clock.advance(60)
    assert set(readings.reads) == {"idle"}
    engine.remove("idle")
    busy = {"not": {"type": "cpu_below", "percent": 20, "for": "2m"}}
    engine.upsert(
        rule(id="backup", trigger={"type": "cron", "expr": "0 3 * * *"}, guards={"any": [busy]})
    )
    await settle()
    reads = readings.reads.copy()
    await clock.advance(60)
    assert readings.reads["idle"] == reads["idle"]
    assert readings.reads["cpu"] == reads["cpu"] + 12  # a guard with a `for` needs its history


async def test_a_one_shot_run_keeps_its_sensors_until_it_ends(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.cpu_percent = 50.0
    busy = {"not": {"type": "cpu_below", "percent": 20, "for": "2m"}}
    guards = {"any": [busy], "retry": "1m", "max_wait": "1h"}
    engine.upsert(rule(trigger=IDLE_20M, one_shot=True, guards=guards))
    await clock.advance(180)  # the CPU history builds up while the rule waits
    readings.idle_seconds = 1200
    await clock.advance(5)
    [run] = engine.executor.active
    assert run.state == "postponed"  # CPU busy: not below 20 % for 2 minutes
    assert engine.rules["test"].enabled is False
    readings.cpu_percent = 5.0
    await clock.advance(180)
    assert run.state == "done"  # the rule was disabled when it fired, the history went on


async def test_a_guard_without_history_does_not_block(
    engine: Engine, readings: FakeReadings, clock: FakeClock
) -> None:
    readings.cpu_percent = 90.0
    busy = {"not": {"type": "cpu_below", "percent": 20, "for": "2m"}}
    engine.upsert(rule(guards={"any": [busy]}))
    run = engine.run_now("test")  # just added: no 2 minutes of history yet → unknown
    await settle()
    assert run.state == "done"


# ── Guards ────────────────────────────────────────────────────────────────────

Change = Callable[[FakeReadings], None]


@pytest.mark.parametrize(
    ("guard", "block", "release"),
    [
        (
            {"type": "process_running", "name": "ffmpeg"},
            lambda r: r.start("ffmpeg", pid=7),
            lambda r: r.stop(7),
        ),
        (
            {"type": "media_playing"},
            lambda r: setattr(r, "media", True),
            lambda r: setattr(r, "media", False),
        ),
        ({"type": "ssh_session"}, lambda r: setattr(r, "ssh", 1), lambda r: setattr(r, "ssh", 0)),
    ],
)
async def test_a_guard_postpones_until_it_clears(
    engine: Engine,
    readings: FakeReadings,
    clock: FakeClock,
    guard: dict[str, Any],
    block: Change,
    release: Change,
) -> None:
    block(readings)
    engine.upsert(rule(guards={"any": [guard], "retry": "1m"}))
    run = engine.run_now("test")
    await settle()
    assert run.state == "postponed"
    await clock.advance(60)
    assert run.state == "postponed"
    release(readings)
    await clock.advance(60)
    assert run.state == "done"


async def test_time_window_guard(engine: Engine, clock: FakeClock) -> None:
    # 10:00 in Madrid: the guard holds until 10:30
    window = {"type": "time_window", "start": "09:00", "end": "10:30"}
    engine.upsert(rule(guards={"any": [window], "retry": "15m"}))
    run = engine.run_now("test")
    await clock.advance(15 * 60)
    assert run.state == "postponed"
    await clock.advance(15 * 60)
    assert run.state == "done"


async def test_weekday_guard_gives_up_after_max_wait(engine: Engine, clock: FakeClock) -> None:
    weekday = {"type": "weekday", "days": ["thu"]}  # today
    engine.upsert(rule(guards={"any": [weekday], "retry": "30m", "max_wait": "1h"}))
    run = engine.run_now("test")
    await clock.advance(3600)
    assert run.state == "skipped"
    assert run.reason is not None
    assert run.reason.startswith("guard still active after 1h")
