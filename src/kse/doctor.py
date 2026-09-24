"""`kse doctor`: the backend's report plus the checks that do not depend on the OS."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psutil

from kse.i18n import _
from kse.platform.base import (
    Capability,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerEvent,
    PowerMode,
)
from kse.sensors import system


async def capabilities(backend: PlatformBackend) -> list[Capability]:
    """The full report; the backend stays open (the daemon keeps using it)."""
    return [*await backend.capabilities(), *generic()]


async def collect(backend: PlatformBackend) -> list[Capability]:
    """The full report for a one-off command: closes the backend afterwards."""
    try:
        return await capabilities(backend)
    finally:
        await backend.close()


def generic() -> list[Capability]:
    state = system.battery()
    if state is None:
        power = _("no battery: always on AC")
    else:
        source = _("on AC") if state.plugged else _("on battery")
        power = _("{source} · battery {percent} %").format(
            source=source, percent=round(state.percent)
        )
    sensors = _("psutil {version}: CPU, network, processes, SSH sessions").format(
        version=psutil.__version__
    )
    return [
        Capability(id="power_source", supported=True, detail=power),
        Capability(id="sensors", supported=True, detail=sensors),
    ]


# ── `kse doctor --test-wake`: program an alarm, suspend, check who woke us up ──

WAKE_TOLERANCE = timedelta(seconds=90)  # firmware and resume take a while


@dataclass(frozen=True)
class WakeTest:
    alarm: datetime
    slept: bool
    resumed_at: datetime | None
    alarm_left: bool  # the alarm is still programmed: it did not fire
    woken_by: str | None = None  # what the OS says woke it, when it changed during the test

    @property
    def verdict(self) -> str:
        """ok, no_sleep, no_resume, early (woken by hand?) or late (alarm did not work?)."""
        if not self.slept:
            return "no_sleep"
        if self.resumed_at is None:
            return "no_resume"
        if self.alarm_left or self.resumed_at < self.alarm - timedelta(seconds=5):
            return "early"
        if self.resumed_at > self.alarm + WAKE_TOLERANCE:
            return "late"
        return "ok"


async def run_wake_test(
    backend: PlatformBackend,
    seconds: int,
    *,
    announce: Callable[[datetime], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep_limit: float = 30.0,
) -> WakeTest:
    """Program a wake-up in `seconds`, suspend, and report what happened. The alarm is set
    before suspending: if that fails, the machine is not suspended."""
    slept, resumed = asyncio.Event(), asyncio.Event()
    resumed_at: list[datetime] = []

    async def on_event(event: PowerEvent) -> None:
        if event is PowerEvent.BEFORE_SLEEP:
            slept.set()
        elif event is PowerEvent.AFTER_RESUME:
            resumed_at.append(now())
            resumed.set()

    await backend.subscribe_power_events(on_event)
    before = await _wakeup_source(backend)
    alarm = (now() + timedelta(seconds=seconds)).replace(microsecond=0)
    await backend.wake_set(alarm)
    announce(alarm)
    await backend.power(PowerAction.SUSPEND, PowerMode.GRACEFUL)
    try:
        await asyncio.wait_for(slept.wait(), sleep_limit)
    except TimeoutError:
        return WakeTest(alarm, slept=False, resumed_at=None, alarm_left=True)
    try:
        await asyncio.wait_for(resumed.wait(), seconds + 900)
    except TimeoutError:
        return WakeTest(alarm, slept=True, resumed_at=None, alarm_left=True)
    left = await backend.wake_get()
    after = await _wakeup_source(backend)
    return WakeTest(
        alarm,
        slept=True,
        resumed_at=resumed_at[0],
        alarm_left=left == alarm,
        woken_by=after if after != before else None,
    )


def verdict_message(result: WakeTest, show: Callable[[datetime | None], str]) -> str:
    """What the wake test found, in words; `show` writes a time for the user."""
    messages = {
        "ok": _("✔ Woke up by itself at {resumed} (alarm {alarm})."),
        "early": _("? Resumed at {resumed}, before the alarm ({alarm}): woken by hand?"),
        "late": _("✘ Resumed at {resumed}, long after the alarm ({alarm})."),
        "no_sleep": _("✘ The computer did not suspend (an inhibitor?)."),
        "no_resume": _("✘ No resume was seen."),
    }
    text = messages[result.verdict].format(
        resumed=show(result.resumed_at), alarm=show(result.alarm)
    )
    if result.woken_by:
        text += "\n" + _("woken by: {source}").format(source=result.woken_by)
    elif result.verdict in ("early", "late"):
        text += "\n" + _("the OS did not say what woke it up")
    return text


async def _wakeup_source(backend: PlatformBackend) -> str | None:
    try:
        return await backend.wakeup_source()
    except NotSupported:
        return None
