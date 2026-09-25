"""WakePlanner: keeps the single hardware wake alarm on the earliest wake-up needed.

The alarm is set `margin` before the earliest enabled rule with `wake: true`, so the
daemon is ready when the rule fires (a bit more when the rule also logs in: booting and
logging in take about a minute). When that rule has `log_in`, the one-time log-in ticket
is armed for that alarm (and disarmed when no longer needed). It is rewritten when rules
change, after each firing and right before the machine sleeps or shuts down (holding a
logind delay inhibitor, so manual shutdowns are covered too). An alarm programmed by
somebody else that comes earlier (e.g. `powerclock doctor --test-wake`) is never delayed
or removed.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta

from powerclock.engine.clock import Clock
from powerclock.engine.runs import Event, EventSink
from powerclock.platform.base import LogInMode, NotSupported, PlatformBackend, PowerEvent

log = logging.getLogger(__name__)

MARGIN = timedelta(seconds=120)  # time for the machine and the daemon to be ready
LOGIN_MARGIN = timedelta(seconds=180)  # …and to log in (the Latitude needs about 50 s)
MIN_LEAD = timedelta(seconds=10)  # the helper refuses alarms in the past

WakeNeed = datetime | tuple[datetime, LogInMode | None]  # when, and whether to log in


class WakePlanner:
    def __init__(
        self,
        backend: PlatformBackend,
        clock: Clock,
        wake_times: Callable[[], list[WakeNeed]],
        *,
        margin: timedelta = MARGIN,
        emit: EventSink | None = None,
    ) -> None:
        self._backend = backend
        self._clock = clock
        self._wake_times = wake_times  # upcoming fires of enabled rules with wake: true
        self._margin = margin
        self._sink = emit
        self.target: datetime | None = None  # the alarm we programmed
        self.login: LogInMode | None = None  # the log-in ticket we armed for it
        self.error: str | None = None  # why the last attempt failed
        self._dirty = asyncio.Event()
        self._reread = False  # after a resume: the alarm may have fired, check it
        self._inhibitor: AbstractAsyncContextManager[None] | None = None
        self._lock = asyncio.Lock()

    def plan(self) -> tuple[datetime | None, LogInMode | None]:
        """The alarm to program and whether its power-on logs in ("locked" wins)."""
        now = self._clock.now()
        needs = [need if isinstance(need, tuple) else (need, None) for need in self._wake_times()]
        upcoming = [(moment, login) for moment, login in needs if moment > now]
        if not upcoming:
            return None, None
        first = min(moment for moment, _ in upcoming)
        modes = {login for moment, login in upcoming if moment == first and login}
        login: LogInMode | None = (
            "locked" if "locked" in modes else "unlocked" if "unlocked" in modes else None
        )
        margin = max(self._margin, LOGIN_MARGIN) if login else self._margin
        alarm = max(first - margin, now + MIN_LEAD)
        return alarm.replace(microsecond=0), login  # the RTC counts whole seconds

    def desired(self) -> datetime | None:
        return self.plan()[0]

    def request_sync(self) -> None:
        """Something changed: bring the alarm up to date soon (changes are coalesced)."""
        self._dirty.set()

    async def run(self) -> None:
        try:
            while True:
                await self._dirty.wait()
                self._dirty.clear()
                rewrite, self._reread = self._reread, False
                await self.sync(rewrite=rewrite)
        finally:
            await self._release()  # the alarm itself stays: it may have to power us on

    async def sync(self, *, rewrite: bool = False) -> None:
        async with self._lock:
            await self._sync(rewrite)
            if self.target is not None:
                await self._hold()
            else:
                await self._release()

    async def on_power_event(self, event: PowerEvent) -> None:
        if event in (PowerEvent.BEFORE_SLEEP, PowerEvent.BEFORE_SHUTDOWN):
            async with self._lock:
                await self._sync(rewrite=True)  # covers suspends and shutdowns by hand
                await self._release()  # let it go on
        elif event is PowerEvent.AFTER_RESUME:
            self._reread = True  # the alarm may have fired: check and program the next
            self.request_sync()

    async def _sync(self, rewrite: bool) -> None:
        desired, login = self.plan()
        if (desired, login) == (self.target, self.login) and self.error is None and not rewrite:
            return
        try:
            current = await self._current()
            now = self._clock.now()
            if (
                current is not None
                and current > now
                and current != self.target  # not ours
                and (desired is None or current < desired)
            ):
                log.info("wake: keeping an earlier alarm set by someone else (%s)", current)
                self.target, self.error = None, None
                return
            if desired is None:
                if current is not None and current == self.target:
                    await self._backend.wake_clear()
            elif rewrite or desired != current:
                await self._backend.wake_set(desired)
        except NotSupported as exc:
            self._fail(f"{exc}" + (f" ({exc.fix_hint})" if exc.fix_hint else ""))
            return
        except Exception as exc:
            self._fail(str(exc) or type(exc).__name__)
            return
        changed = desired != self.target
        self.target, self.error = desired, None
        if changed:
            log.info("wake: alarm %s", desired or "cleared")
            self._emit({"at": desired.isoformat() if desired else None})
        await self._ticket(desired, login, rewrite)

    async def _ticket(self, alarm: datetime | None, login: LogInMode | None, rewrite: bool) -> None:
        """Arm the one-time log-in for this alarm, or disarm the one we armed."""
        armed = self.login is not None
        try:
            if alarm is not None and login is not None:
                await self._backend.autologin_arm(alarm, login)
            elif armed:
                await self._backend.autologin_disarm()
            self.login = login if alarm is not None else None
        except NotSupported as exc:
            self._fail("log in: " + f"{exc}" + (f" ({exc.fix_hint})" if exc.fix_hint else ""))
        except Exception as exc:
            self._fail("log in: " + (str(exc) or type(exc).__name__))

    async def _current(self) -> datetime | None:
        try:
            return await self._backend.wake_get()
        except NotSupported:
            return self.target  # cannot read it: trust what we programmed

    def _fail(self, message: str) -> None:
        if message != self.error:
            log.warning("wake: %s", message)
            self._emit({"at": None, "error": message})
        self.error = message

    async def _hold(self) -> None:
        """Hold a delay inhibitor, so logind waits for us before sleeping/shutting down."""
        if self._inhibitor is not None:
            return
        try:
            inhibitor = self._backend.inhibit_delay()
            await inhibitor.__aenter__()
        except Exception as exc:  # NotSupported, D-Bus errors…: the periodic sync remains
            log.info("wake: no delay inhibitor (%s)", exc)
            return
        self._inhibitor = inhibitor

    async def _release(self) -> None:
        inhibitor, self._inhibitor = self._inhibitor, None
        if inhibitor is not None:
            with contextlib.suppress(Exception):
                await inhibitor.__aexit__(None, None, None)

    def _emit(self, data: dict[str, object]) -> None:
        if self._sink is None:
            return
        try:
            self._sink(Event(type="wake_changed", at=self._clock.now(), data=data))
        except Exception:
            log.exception("event listener failed")
