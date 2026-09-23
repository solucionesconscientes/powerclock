from datetime import UTC, datetime, timedelta

import pytest

from kse.engine.clock import FakeClock, settle
from kse.engine.evaluator import Evaluator
from kse.engine.executor import Executor
from kse.engine.processes import FakeProcesses
from kse.engine.runs import Event, Run
from kse.platform.base import NotSupported, PowerAction, PowerMode
from kse.platform.fake import FakeCall, FakePlatform
from kse.sensors.fake import FakeSensors
from support import MADRID, START, rule

SHUTDOWN = {"type": "power", "action": "shutdown"}
NOTIFY = {"type": "notify", "title": "KSE", "body": "hola"}


def power_calls(fake: FakePlatform) -> list[FakeCall]:
    return fake.calls_to("power")


def event_types(events: list[Event]) -> list[str]:
    return [event.type for event in events if event.type != "tick"]


async def finish(executor: Executor, run: Run) -> Run:
    return await executor.wait(run.id)


# ── Sequence, conditions and guards ─────────────────────────────────────────


async def test_actions_run_in_order(
    executor: Executor, fake: FakePlatform, events: list[Event]
) -> None:
    run = executor.start(
        rule(
            actions=[
                NOTIFY,
                {"type": "open", "target": "https://example.org"},
                {"type": "power", "action": "lock"},
            ]
        ),
        MADRID,
        cause="manual",
    )
    run = await finish(executor, run)
    assert run.state == "done"
    assert run.reason is None
    assert [step.status for step in run.steps] == ["ok", "ok", "ok"]
    assert [call.method for call in fake.calls] == ["notify", "open", "power"]
    assert power_calls(fake) == [FakeCall("power", (PowerAction.LOCK, PowerMode.GRACEFUL))]
    assert event_types(events) == ["run_started", "run_finished"]
    assert run in executor.recent


@pytest.mark.parametrize(
    ("value", "reason"),
    [(False, "conditions not met"), (None, "conditions unknown")],
)
async def test_conditions_must_be_true(
    executor: Executor,
    fake: FakePlatform,
    sensors: FakeSensors,
    value: bool | None,
    reason: str,
) -> None:
    sensors.values["power_source"] = value
    conditions = {"type": "power_source", "is": "ac"}
    run = await finish(
        executor,
        executor.start(rule(conditions=conditions, actions=[SHUTDOWN]), MADRID, cause="manual"),
    )
    assert run.state == "skipped"
    assert run.reason is not None
    assert reason in run.reason
    assert fake.calls == []


async def test_guards_postpone_until_they_clear(
    executor: Executor,
    fake: FakePlatform,
    sensors: FakeSensors,
    clock: FakeClock,
    events: list[Event],
) -> None:
    sensors.values["media_playing"] = True
    guards = {"any": [{"type": "media_playing"}], "retry": "5m", "max_wait": "1h"}
    run = executor.start(rule(guards=guards, actions=[NOTIFY]), MADRID, cause="schedule")
    await settle()
    assert run.state == "postponed"
    assert run.reason is not None
    assert "media_playing" in run.reason
    await clock.advance(300)
    assert run.state == "postponed"
    sensors.values["media_playing"] = False
    await clock.advance(300)
    assert run.state == "done"
    assert fake.calls_to("notify")
    assert event_types(events) == ["run_started", "postponed", "postponed", "run_finished"]


async def test_guards_unknown_do_not_block(executor: Executor, fake: FakePlatform) -> None:
    guards = {"any": [{"type": "media_playing"}]}  # FakeSensors: unknown
    run = await finish(
        executor, executor.start(rule(guards=guards, actions=[NOTIFY]), MADRID, cause="manual")
    )
    assert run.state == "done"


async def test_guards_give_up_after_max_wait(
    executor: Executor, fake: FakePlatform, sensors: FakeSensors, clock: FakeClock
) -> None:
    sensors.values["ssh_session"] = True
    guards = {"any": [{"type": "ssh_session"}], "retry": "5m", "max_wait": "10m"}
    run = executor.start(rule(guards=guards, actions=[SHUTDOWN]), MADRID, cause="schedule")
    await clock.advance(600)
    assert run.state == "skipped"
    assert run.reason is not None
    assert run.reason.startswith("guard still active after 10m")
    assert fake.calls == []


# ── Power actions and countdown ─────────────────────────────────────────────


async def test_countdown_then_power(
    executor: Executor, fake: FakePlatform, clock: FakeClock, events: list[Event]
) -> None:
    run = executor.start(rule(warning="60s", actions=[SHUTDOWN]), MADRID, cause="schedule")
    await clock.advance(59)
    assert run.state == "warning"
    assert run.deadline == START + timedelta(seconds=60)
    assert power_calls(fake) == []
    await clock.advance(1)
    assert run.state == "done"
    assert power_calls(fake) == [FakeCall("power", (PowerAction.SHUTDOWN, PowerMode.GRACEFUL))]
    ticks = [event.data["remaining"] for event in events if event.type == "tick"]
    assert ticks == list(range(60, 0, -1))
    assert event_types(events) == ["run_started", "warning_started", "run_finished"]


async def test_countdown_notification_offers_cancel_and_postpone(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    executor.start(rule(name="Backup", warning="60s", actions=[SHUTDOWN]), MADRID, cause="manual")
    await clock.advance(1)
    [call] = fake.calls_to("notify")
    title, body, buttons = call.args
    assert title == "KSE"
    assert "Backup" in body
    assert "60" in body
    assert buttons == ("cancel", "postpone")


async def test_cancel_countdown(
    executor: Executor, fake: FakePlatform, clock: FakeClock, events: list[Event]
) -> None:
    run = executor.start(rule(warning="60s", actions=[SHUTDOWN]), MADRID, cause="schedule")
    await clock.advance(30)
    assert executor.cancel_countdown() is run
    await clock.advance(120)
    assert run.state == "cancelled"
    assert run.steps[0].status == "cancelled"
    assert power_calls(fake) == []
    assert "cancelled" in event_types(events)
    assert executor.cancel_countdown() is None


async def test_postpone_countdown(executor: Executor, fake: FakePlatform, clock: FakeClock) -> None:
    run = executor.start(rule(warning="60s", actions=[SHUTDOWN]), MADRID, cause="schedule")
    await clock.advance(30)
    assert executor.postpone(run.id)
    assert run.deadline == START + timedelta(minutes=10, seconds=60)
    await clock.advance(60)
    assert power_calls(fake) == []
    await clock.advance(570)
    assert len(power_calls(fake)) == 1


async def test_postpone_needs_a_countdown(executor: Executor) -> None:
    run = executor.start(rule(actions=[{"type": "wait", "duration": "1m"}]), MADRID, cause="manual")
    await settle()
    assert not executor.postpone(run.id)
    assert not executor.postpone("unknown")


@pytest.mark.parametrize(("choice", "state"), [("cancel", "cancelled"), ("postpone", "warning")])
async def test_notification_buttons(
    executor: Executor, fake: FakePlatform, clock: FakeClock, choice: str, state: str
) -> None:
    fake.notify_response = choice
    run = executor.start(rule(warning="60s", actions=[SHUTDOWN]), MADRID, cause="manual")
    await clock.advance(60)
    assert run.state == state
    assert power_calls(fake) == []


async def test_global_dry_run(fake: FakePlatform, evaluator: Evaluator, clock: FakeClock) -> None:
    executor = Executor(fake, evaluator, clock, dry_run=True)
    run = await finish(executor, executor.start(rule(actions=[SHUTDOWN]), MADRID, cause="manual"))
    assert run.dry_run
    assert run.state == "done"
    assert run.steps[0].status == "dry_run"
    assert power_calls(fake) == []


async def test_rule_dry_run(executor: Executor, fake: FakePlatform) -> None:
    run = executor.start(rule(dry_run=True, actions=[SHUTDOWN]), MADRID, cause="manual")
    run = await finish(executor, run)
    assert run.dry_run
    assert run.steps[0].status == "dry_run"
    assert power_calls(fake) == []


async def test_one_power_action_at_a_time(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    first = executor.start(
        rule(id="first", warning="60s", actions=[{"type": "power", "action": "suspend"}]),
        MADRID,
        cause="schedule",
    )
    second = executor.start(
        rule(id="second", warning="60s", actions=[SHUTDOWN]), MADRID, cause="schedule"
    )
    await settle()
    assert (first.state, second.state) == ("warning", "waiting")
    await clock.advance(60)
    assert first.state == "done"
    assert second.state == "warning"
    await clock.advance(60)
    assert [call.args[0] for call in power_calls(fake)] == [
        PowerAction.SUSPEND,
        PowerAction.SHUTDOWN,
    ]


async def test_power_not_supported_fails_the_run(evaluator: Evaluator, clock: FakeClock) -> None:
    class NoPower(FakePlatform):
        async def power(self, action: PowerAction, mode: PowerMode) -> None:
            raise NotSupported("power", "no logind here")

    executor = Executor(NoPower(), evaluator, clock)
    run = await finish(executor, executor.start(rule(actions=[SHUTDOWN]), MADRID, cause="manual"))
    assert run.state == "failed"
    assert run.reason == "step 1 (power) failed: power: no logind here"


# ── Other actions ───────────────────────────────────────────────────────────


async def test_same_rule_does_not_run_twice_at_once(executor: Executor) -> None:
    slow = rule(actions=[{"type": "wait", "duration": "1h"}])
    first = executor.start(slow, MADRID, cause="schedule")
    second = executor.start(slow, MADRID, cause="schedule")
    assert first.state == "running"
    assert second.state == "skipped"
    assert second.reason == "the previous run of this rule is still active"


@pytest.mark.parametrize(
    ("on_error", "statuses"), [("stop", ["failed"]), ("continue", ["failed", "ok"])]
)
async def test_on_error(
    executor: Executor, fake: FakePlatform, on_error: str, statuses: list[str]
) -> None:
    actions = [{"type": "set_wake", "after": "8h"}, NOTIFY]  # set_wake needs M5
    run = executor.start(rule(on_error=on_error, actions=actions), MADRID, cause="manual")
    run = await finish(executor, run)
    assert run.state == "failed"
    assert [step.status for step in run.steps] == statuses
    assert run.reason is not None
    assert "WakePlanner" in run.reason


async def test_set_wake_asks_the_wake_planner(
    fake: FakePlatform, evaluator: Evaluator, clock: FakeClock
) -> None:
    requested: list[datetime] = []

    async def request_wake(when: datetime) -> None:
        requested.append(when)

    executor = Executor(fake, evaluator, clock, request_wake=request_wake)
    actions = [
        {"type": "set_wake", "after": "8h"},
        {"type": "set_wake", "when": "2026-09-25T07:30:00+02:00"},
    ]
    run = await finish(executor, executor.start(rule(actions=actions), MADRID, cause="manual"))
    assert run.state == "done"
    assert requested == [START + timedelta(hours=8), datetime(2026, 9, 25, 5, 30, tzinfo=UTC)]


async def test_notify_is_best_effort(evaluator: Evaluator, clock: FakeClock) -> None:
    class NoDesktop(FakePlatform):
        async def notify(
            self, title: str, body: str, actions: dict[str, str] | None = None
        ) -> str | None:
            raise NotSupported("notify", "no notification server")

    executor = Executor(NoDesktop(), evaluator, clock)
    run = await finish(executor, executor.start(rule(actions=[NOTIFY]), MADRID, cause="manual"))
    assert run.state == "done"
    assert run.steps[0].status == "skipped"


async def test_wait(executor: Executor, clock: FakeClock) -> None:
    run = executor.start(
        rule(actions=[{"type": "wait", "duration": "10m"}]), MADRID, cause="manual"
    )
    await clock.advance(599)
    assert run.state == "waiting"
    await clock.advance(1)
    assert run.state == "done"


async def test_wait_until(executor: Executor, sensors: FakeSensors, clock: FakeClock) -> None:
    step = {"type": "wait_until", "condition": {"type": "ssh_session"}, "timeout": "1h"}
    run = executor.start(rule(actions=[step]), MADRID, cause="manual")
    await clock.advance(60)
    assert run.state == "waiting"
    sensors.values["ssh_session"] = True
    await clock.advance(5)
    assert run.state == "done"


async def test_wait_until_times_out(executor: Executor, clock: FakeClock) -> None:
    step = {"type": "wait_until", "condition": {"type": "ssh_session"}, "timeout": "1m"}
    run = executor.start(rule(actions=[step]), MADRID, cause="manual")
    await clock.advance(60)
    assert run.state == "failed"
    assert run.steps[0].detail == "condition not met within 1m"


async def test_close_app(executor: Executor, processes: FakeProcesses) -> None:
    processes.running["firefox"] = 2
    actions = [
        {"type": "close_app", "name": "firefox", "timeout": "10s"},
        {"type": "close_app", "name": "gimp"},
    ]
    run = await finish(executor, executor.start(rule(actions=actions), MADRID, cause="manual"))
    assert [step.detail for step in run.steps] == ["closed 2 process(es)", "not running"]
    assert processes.closed == [("firefox", timedelta(seconds=10)), ("gimp", timedelta(seconds=30))]


async def test_shutdown_cancels_active_runs(executor: Executor) -> None:
    run = executor.start(rule(actions=[{"type": "wait", "duration": "1h"}]), MADRID, cause="manual")
    await settle()
    await executor.shutdown()
    assert run.state == "cancelled"
    assert executor.active == []
