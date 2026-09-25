"""Opening applications (the launch step), closing them, the {date}… variables and the
desktop session: executor, sensors and watcher, against the fake backend."""

import sys
from datetime import UTC, datetime, timedelta

import pytest

from powerclock.engine import variables
from powerclock.engine.clock import FakeClock, settle
from powerclock.engine.executor import Executor
from powerclock.engine.processes import FakeProcesses
from powerclock.models import LaunchStep
from powerclock.platform.base import LaunchRequest, WindowPlacement
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings
from support import MADRID, rule

# ── Variables ─────────────────────────────────────────────────────────────────


def test_variables_of_a_run() -> None:
    moment = datetime(2026, 9, 24, 7, 5, tzinfo=MADRID)
    values = variables.context(moment, "radio", {"home": "/home/pc"})
    assert values["date"] == "2026-09-24"
    assert values["time"] == "07-05"
    assert values["datetime"] == "2026-09-24_07-05"
    assert values["weekday"] == "thu"
    assert values["rule"] == "radio"
    assert variables.expand("{home}/radio-{date}.mp3", values) == "/home/pc/radio-2026-09-24.mp3"


@pytest.mark.parametrize(
    "text",
    ["echo {a,b}", "%(ext)s", '{"json": 1}', "{unknown}", "no braces", "{ date }"],
)
def test_other_braces_stay(text: str) -> None:
    values = variables.context(datetime(2026, 1, 1, tzinfo=UTC), "x")
    assert variables.expand(text, values) == text


# ── The launch step ───────────────────────────────────────────────────────────


async def test_launch_opens_the_app(executor: Executor, fake: FakePlatform) -> None:
    step = {
        "type": "launch",
        "app": "org.kde.okular",
        "args": ["--presentation", "/tmp/{date}.pdf"],
        "window": {"screen": 2, "state": "fullscreen"},
        "keep_open": True,
        "stop_signal": "INT",
    }
    run = await executor.wait(executor.start(rule(actions=[step]), MADRID, cause="manual").id)
    assert run.state == "done"
    assert run.steps[0].detail == "Okular (simulated)"
    [call] = fake.calls_to("launch")
    request = call.args[0]
    assert request == LaunchRequest(
        app="org.kde.okular",
        args=("--presentation", "/tmp/2026-09-24.pdf"),
        window=WindowPlacement(screen=2, state="fullscreen"),
        keep_open=True,
        stop_signal="INT",
    )


async def test_launch_waits_for_the_desktop(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    fake.desktop = False
    step = {"type": "launch", "app": "vlc", "wait_desktop": "1m"}
    run = executor.start(rule(actions=[step]), MADRID, cause="manual")
    await clock.advance(10)
    assert (run.state, run.reason) == ("waiting", "waiting for the desktop session")
    fake.desktop = True
    await clock.advance(2)
    await settle()
    assert run.state == "done"
    assert fake.opened == {"vlc": 1}


async def test_launch_gives_up_without_a_desktop(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    fake.desktop = False
    step = {"type": "launch", "app": "vlc", "wait_desktop": "30s"}
    run = executor.start(rule(actions=[step]), MADRID, cause="manual")
    await clock.advance(32)
    await settle()
    assert run.state == "failed"
    assert run.steps[0].detail == "no desktop session after 30s"
    assert fake.calls_to("launch") == []


async def test_launch_of_a_missing_app_fails(executor: Executor) -> None:
    step = {"type": "launch", "app": "nope"}
    run = await executor.wait(executor.start(rule(actions=[step]), MADRID, cause="manual").id)
    assert run.state == "failed"
    assert "not an installed application" in (run.reason or "")


async def test_close_app_by_app_or_by_name(
    executor: Executor, fake: FakePlatform, processes: FakeProcesses
) -> None:
    fake.opened["vlc"] = 2
    processes.running["obs"] = 1
    steps = [
        {"type": "close_app", "app": "vlc"},
        {"type": "close_app", "name": "obs", "signal": "INT", "timeout": "10s"},
    ]
    run = await executor.wait(executor.start(rule(actions=steps), MADRID, cause="manual").id)
    assert [step.detail for step in run.steps] == ["closed 2 process(es)", "closed 1 process(es)"]
    assert processes.signals == ["INT"]


def test_launch_step_model() -> None:
    step = LaunchStep.model_validate({"type": "launch", "app": "org.kde.okular.desktop"})
    assert step.app == "org.kde.okular"
    assert step.wait_desktop == timedelta(minutes=2)
    with pytest.raises(ValueError, match="exactly one of: name, app"):
        rule(actions=[{"type": "close_app", "name": "a", "app": "b"}])


# ── run: variables and the session's environment ──────────────────────────────


async def test_run_sees_the_desktop_session(
    executor: Executor, fake: FakePlatform, tmp_path: object
) -> None:
    fake.session_vars = {"WAYLAND_DISPLAY": "wayland-9"}
    code = "import os, sys; print(os.environ['WAYLAND_DISPLAY'], sys.argv[1])"
    step = {"type": "run", "cmd": [sys.executable, "-c", code, "{rule}-{weekday}"]}
    run = await executor.wait(executor.start(rule(actions=[step]), MADRID, cause="manual").id)
    assert run.state == "done", run.reason
    assert run.steps[0].detail == "wayland-9 test-thu"


async def test_notify_and_open_expand_variables(executor: Executor, fake: FakePlatform) -> None:
    steps = [
        {"type": "notify", "title": "Copia {date}", "body": "{rule}"},
        {"type": "open", "target": "https://example.org/{date}"},
    ]
    await executor.wait(executor.start(rule(actions=steps), MADRID, cause="manual").id)
    assert fake.calls_to("notify")[0].args[:2] == ("Copia 2026-09-24", "test")
    assert fake.calls_to("open")[0].args == ("https://example.org/2026-09-24",)


# ── The desktop session as a trigger ──────────────────────────────────────────


async def test_desktop_session_trigger_fires_when_it_starts(
    engine: object, readings: FakeReadings, fake: FakePlatform, clock: FakeClock
) -> None:
    from powerclock.engine import Engine

    assert isinstance(engine, Engine)
    readings.desktop_up = False
    engine.upsert(
        rule(
            id="login",
            trigger={"type": "desktop_session"},
            actions=[{"type": "launch", "app": "vlc"}],
        )
    )
    await clock.advance(10)
    assert fake.calls_to("launch") == []
    readings.desktop_up = True
    await clock.advance(10)
    await settle()
    assert len(fake.calls_to("launch")) == 1
    await clock.advance(30)  # still up: it does not fire again
    await settle()
    assert len(fake.calls_to("launch")) == 1
    [status] = engine.watcher.status()
    assert status.value == "up"
