"""`powerclock doctor --test-wake`: the logic with a simulated suspend, and the CLI safeguards."""

import asyncio
import functools
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from powerclock.cli.main import app
from powerclock.doctor import WakeTest, run_wake_test
from powerclock.platform.base import NotSupported, PowerAction, PowerEvent, PowerMode
from powerclock.platform.fake import FakePlatform

ALARM = datetime(2026, 9, 24, 8, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    ("slept", "resumed", "left", "verdict"),
    [
        (True, ALARM + timedelta(seconds=3), False, "ok"),
        (True, ALARM - timedelta(seconds=40), False, "early"),
        (True, ALARM + timedelta(seconds=2), True, "early"),  # the alarm did not fire
        (True, ALARM + timedelta(minutes=10), False, "late"),
        (True, None, True, "no_resume"),
        (False, None, True, "no_sleep"),
    ],
)
def test_verdicts(slept: bool, resumed: datetime | None, left: bool, verdict: str) -> None:
    assert WakeTest(ALARM, slept, resumed, left).verdict == verdict


class Sleepy(FakePlatform):
    """Suspending emits before_sleep, then after_resume when the 'alarm' fires."""

    def __init__(self, clock: list[datetime], woken_after: float | None = 0.0) -> None:
        super().__init__()
        self.clock = clock
        self.woken_after = woken_after

    async def power(self, action: PowerAction, mode: PowerMode) -> None:
        await super().power(action, mode)
        if self.woken_after is None:
            return  # an inhibitor blocked the suspend

        async def cycle() -> None:
            await self.emit(PowerEvent.BEFORE_SLEEP)
            assert self.wake is not None
            self.clock[0] = self.wake + timedelta(seconds=self.woken_after or 0)
            self.wake = None  # consumed
            await self.emit(PowerEvent.AFTER_RESUME)

        asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(cycle()))


async def test_run_wake_test() -> None:
    clock = [datetime(2026, 9, 24, 8, 0, 0, 500_000, tzinfo=UTC)]
    backend = Sleepy(clock, woken_after=4)
    backend.wakeup = "IRQ 51: touchpad"  # stale: from an earlier wake-up
    announced: list[datetime] = []
    result = await run_wake_test(backend, 120, announce=announced.append, now=lambda: clock[0])
    assert announced == [ALARM]
    assert result == WakeTest(ALARM, True, ALARM + timedelta(seconds=4), False, woken_by=None)
    assert result.verdict == "ok"
    methods = [call.method for call in backend.calls]
    assert methods.index("wake_set") < methods.index("power")  # alarm first, then suspend


async def test_no_suspend_without_an_alarm() -> None:
    class NoHelper(Sleepy):
        async def wake_set(self, when: datetime) -> None:
            raise NotSupported("wake", "powerclock-helper is not installed")

    backend = NoHelper([datetime(2026, 9, 24, 8, 0, tzinfo=UTC)])
    with pytest.raises(NotSupported):
        await run_wake_test(backend, 120, announce=lambda alarm: None)
    assert backend.calls_to("power") == []


async def test_suspend_blocked() -> None:
    backend = Sleepy([datetime(2026, 9, 24, 8, 0, tzinfo=UTC)], woken_after=None)
    result = await run_wake_test(backend, 120, announce=lambda alarm: None, sleep_limit=0.05)
    assert result.verdict == "no_sleep"


def test_cli_does_nothing_in_dry_run() -> None:
    result = CliRunner().invoke(app, ["doctor", "--test-wake", "120"])  # POWERCLOCK_DRY_RUN=1
    assert result.exit_code == 0
    assert "nothing was done" in result.output


def test_cli_asks_before_suspending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWERCLOCK_DRY_RUN")  # the fake backend: nothing real could happen anyway
    backends: list[FakePlatform] = []
    monkeypatch.setattr(
        "powerclock.cli.main.get_backend", lambda: backends.append(FakePlatform()) or backends[-1]
    )
    result = CliRunner().invoke(app, ["doctor", "--test-wake", "120"], input="n\n")
    assert result.exit_code == 1
    assert "suspends the computer now" in result.output
    assert backends == []  # refused before even creating the backend


def test_cli_limits() -> None:
    result = CliRunner().invoke(app, ["doctor", "--test-wake", "5"])
    assert result.exit_code == 2  # at least 60 s


async def test_the_wake_source_is_reported_when_it_changes() -> None:
    clock = [datetime(2026, 9, 24, 8, 0, tzinfo=UTC)]

    class Touchy(Sleepy):
        async def power(self, action: PowerAction, mode: PowerMode) -> None:
            self.wakeup = "IRQ 51: DLL07A7:01 (DualPoint Stick)"
            await super().power(action, mode)

    backend = Touchy(clock, woken_after=-100)  # resumed well before the alarm
    result = await run_wake_test(backend, 120, announce=lambda alarm: None, now=lambda: clock[0])
    assert result.verdict == "early"
    assert result.woken_by == "IRQ 51: DLL07A7:01 (DualPoint Stick)"


def test_cli_full_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWERCLOCK_DRY_RUN")
    monkeypatch.setenv("COLUMNS", "200")
    clock = [datetime(2026, 9, 24, 8, 0, tzinfo=UTC)]
    backend = Sleepy(clock, woken_after=2)
    backend.wakeup = "IRQ 9: acpi"
    monkeypatch.setattr("powerclock.cli.main.get_backend", lambda: backend)
    monkeypatch.setattr("powerclock.cli.main.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "powerclock.cli.main.run_wake_test", functools.partial(run_wake_test, now=lambda: clock[0])
    )
    result = CliRunner().invoke(app, ["doctor", "--test-wake", "120"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "hands off" in result.output
    assert "Woke up by itself" in result.output
    assert [call.method for call in backend.calls].count("power") == 1
