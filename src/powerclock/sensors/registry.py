"""SensorHub: samples only the sensors that active rules use and answers predicates,
applying their `for` with a short history (docs/ARCHITECTURE.md §5).

- Polled channels (state triggers and predicates with a `for`) are sampled continuously
  by the engine's loop through `sample()`; any other sensor is read only when a predicate
  asks, and the reading is reused for a while.
- `cpu_below` / `net_below`: the average of the samples of the last `for` is below the
  threshold. `battery` / `power_source` with a `for`: every sample of the last `for`
  agrees. `idle` needs no history: the OS already counts the idle time.
- The history must cover the whole `for`; until it does the answer is unknown (None).
  A gap between samples (suspend, clock jump) starts it again.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from powerclock.models import (
    BatteryLevel,
    CpuBelow,
    DesktopSession,
    Idle,
    MediaPlaying,
    NetBelow,
    PowerSource,
    ProcessExitTrigger,
    ProcessRunning,
    SshSession,
    WifiSsid,
)
from powerclock.sensors.base import NetRate, PowerState, ProcessInfo, Readings, SensorPredicate

if TYPE_CHECKING:  # powerclock.engine imports this module
    from powerclock.engine.clock import Clock

log = logging.getLogger(__name__)

Channel = Literal["idle", "cpu", "net", "processes", "power", "ssh", "media", "wifi", "desktop"]
Watched = SensorPredicate | ProcessExitTrigger

INTERVALS: dict[Channel, float] = {  # seconds between samples
    "idle": 5.0,
    "cpu": 5.0,
    "net": 5.0,
    "processes": 3.0,
    "power": 5.0,
    "ssh": 10.0,
    "media": 5.0,
    "wifi": 30.0,
    "desktop": 5.0,
}
FRESH = 0.9  # a reading younger than this fraction of its interval is reused
GAP = 3.0  # samples further apart than this many intervals break the history


def channel_of(item: Watched) -> Channel:
    match item:
        case Idle():
            return "idle"
        case CpuBelow():
            return "cpu"
        case NetBelow():
            return "net"
        case BatteryLevel() | PowerSource():
            return "power"
        case ProcessRunning() | ProcessExitTrigger():
            return "processes"
        case SshSession():
            return "ssh"
        case MediaPlaying():
            return "media"
        case WifiSsid():
            return "wifi"
        case DesktopSession():
            return "desktop"


def window_of(item: Watched) -> timedelta:
    """History an item needs: its `for`, except idle (the OS already measures it)."""
    match item:
        case CpuBelow() | NetBelow() | BatteryLevel() | PowerSource():
            return item.for_
    return timedelta(0)


def needs_polling(item: Watched) -> bool:
    """Predicates with a history must be sampled all along, not only when asked."""
    return window_of(item) > timedelta(0)


@dataclass
class _Series:
    value: Any = None  # latest reading
    last: datetime | None = None  # when it was read
    start: datetime | None = None  # when the current unbroken history began
    samples: deque[tuple[datetime, Any]] = field(default_factory=deque)

    def reset(self) -> None:
        self.start = None
        self.samples.clear()


class SensorHub:
    def __init__(self, readings: Readings, clock: "Clock") -> None:
        self._readings = readings
        self._clock = clock
        self._series: dict[Channel, _Series] = {}
        self._polled: dict[Channel, timedelta] = {}  # channel → history to keep
        self._locks: dict[Channel, asyncio.Lock] = {}

    # ── Demand and sampling ───────────────────────────────────────────────────

    def demand(self, items: Iterable[Watched]) -> None:
        """What active rules need sampled all along: their state triggers and their
        predicates with a `for`. Channels that leave the demand lose their history."""
        polled: dict[Channel, timedelta] = {}
        for item in items:
            channel = channel_of(item)
            polled[channel] = max(polled.get(channel, timedelta(0)), window_of(item))
        for channel in self._polled.keys() - polled.keys():
            if channel in self._series:
                self._series[channel].reset()
        self._polled = polled

    @property
    def polled(self) -> set[Channel]:
        return set(self._polled)

    async def sample(self) -> None:
        """Read every polled channel whose interval has passed."""
        for channel in list(self._polled):
            await self._fresh(channel)

    def next_due(self) -> float | None:
        """Seconds until a polled channel is due again (None: nothing is polled)."""
        now = self._clock.now()
        waits = []
        for channel in self._polled:
            series = self._series.get(channel)
            if series is None or series.last is None:
                return 0.0
            elapsed = (now - series.last).total_seconds()
            waits.append(max(0.0, INTERVALS[channel] - elapsed))
        return min(waits, default=None)

    # ── Predicates ────────────────────────────────────────────────────────────

    async def check(self, predicate: SensorPredicate) -> bool | None:
        match predicate:
            case Idle(for_=for_):
                idle = await self._fresh("idle")
                return None if idle is None else idle >= for_.total_seconds()
            case CpuBelow(percent=percent, for_=for_):
                mean = self._mean("cpu", for_, _cpu)
                return None if mean is None else mean < percent
            case NetBelow(kbps=kbps, for_=for_):
                mean = self._mean("net", for_, _throughput_of(predicate))
                return None if mean is None else mean < kbps
            case BatteryLevel(for_=for_):
                return await self._sustained("power", for_, lambda s: _battery_ok(predicate, s))
            case PowerSource(for_=for_):
                return await self._sustained("power", for_, lambda s: _source_ok(predicate, s))
            case ProcessRunning(name=name):
                table = await self.processes()
                return None if table is None else any(p.name == name for p in table)
            case SshSession():
                sessions = await self._fresh("ssh")
                return None if sessions is None else sessions > 0
            case MediaPlaying():
                playing = await self._fresh("media")
                return None if playing is None else bool(playing)
            case WifiSsid(ssid=ssid):
                current = await self._fresh("wifi")
                return None if current is None else current == ssid
            case DesktopSession():
                up = await self._fresh("desktop")
                return None if up is None else bool(up)

    async def processes(self) -> list[ProcessInfo] | None:
        return await self._fresh("processes")

    def measure(self, item: Watched) -> tuple[float | str | None, timedelta | None]:
        """What the sensor behind an item reads now, for status displays: the value (idle
        seconds, average %, kbit/s, battery %, "ac"/"battery") and, for averages, how much
        history there is so far."""
        channel = channel_of(item)
        series = self._series.get(channel)
        if series is None:
            return None, None
        now = self._clock.now()
        match item:
            case Idle():
                return series.value, None
            case CpuBelow() | NetBelow():
                extract = _cpu if isinstance(item, CpuBelow) else _throughput_of(item)
                span = min(item.for_, now - series.start) if series.start else timedelta(0)
                return _average(series, now, span, extract), span
            case BatteryLevel():
                state = series.value
                return (state.percent if isinstance(state, PowerState) else None), None
            case PowerSource():
                state = series.value
                if not isinstance(state, PowerState) or state.on_ac is None:
                    return None, None
                return ("ac" if state.on_ac else "battery"), None
            case DesktopSession():
                up = series.value
                return (None if up is None else ("up" if up else "down")), None
        return None, None

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _fresh(self, channel: Channel) -> Any:
        """The channel's latest reading, reading it again when it is too old."""
        lock = self._locks.setdefault(channel, asyncio.Lock())
        async with lock:
            series = self._series.get(channel)
            now = self._clock.now()
            if series is None or series.last is None or self._stale(channel, series, now):
                await self._read(channel, now)
        return self._series[channel].value

    @staticmethod
    def _stale(channel: Channel, series: _Series, now: datetime) -> bool:
        assert series.last is not None
        age = (now - series.last).total_seconds()
        return age < 0 or age >= INTERVALS[channel] * FRESH

    async def _read(self, channel: Channel, now: datetime) -> None:
        reader: Callable[[], Any] = {
            "idle": self._readings.idle,
            "cpu": self._readings.cpu,
            "net": self._readings.net,
            "processes": self._readings.processes,
            "power": self._readings.power,
            "ssh": self._readings.ssh_sessions,
            "media": self._readings.media_playing,
            "wifi": self._readings.wifi,
            "desktop": self._readings.desktop,
        }[channel]
        try:
            value = await reader()
        except Exception as exc:
            log.debug("sensor %s could not be read: %s", channel, exc)
            value = None
        self._record(channel, now, value)

    def _record(self, channel: Channel, now: datetime, value: Any) -> None:
        series = self._series.setdefault(channel, _Series())
        previous, series.value, series.last = series.last, value, now
        window = self._polled.get(channel, timedelta(0))
        if window <= timedelta(0):
            series.reset()
            return
        interval = timedelta(seconds=INTERVALS[channel])
        broken = previous is None or now < previous or now - previous > interval * GAP
        if broken or series.start is None:
            series.reset()
            series.start = now
        series.samples.append((now, value))
        while series.samples and series.samples[0][0] < now - window - interval:
            series.samples.popleft()

    def _history(self, channel: Channel, window: timedelta) -> _Series | None:
        """The channel's history if it is recent and covers `window`, else None."""
        series = self._series.get(channel)
        now = self._clock.now()
        if series is None or series.start is None or series.last is None:
            return None
        if now - series.last > timedelta(seconds=INTERVALS[channel] * GAP):
            return None  # nobody has sampled it lately
        return series if now - series.start >= window else None

    def _mean(
        self, channel: Channel, window: timedelta, extract: Callable[[Any], float | None]
    ) -> float | None:
        series = self._history(channel, window)
        if series is None:
            return None
        return _average(series, self._clock.now(), window, extract)

    async def _sustained(
        self, channel: Channel, window: timedelta, ok: Callable[[Any], bool | None]
    ) -> bool | None:
        """True if every reading of the last `window` is ok (just the latest if it is 0)."""
        latest = ok(await self._fresh(channel))
        if window <= timedelta(0) or latest is False:
            return latest
        series = self._series[channel]
        now = self._clock.now()
        results = [ok(value) for at, value in series.samples if at >= now - window]
        if False in results:
            return False
        if None in results or self._history(channel, window) is None:
            return None
        return True


def _average(
    series: _Series, now: datetime, window: timedelta, extract: Callable[[Any], float | None]
) -> float | None:
    # Each sample averages the time since the previous one, so the sample taken when the
    # history began (which averages the time before it) is left out.
    values = [extract(value) for at, value in series.samples if at > now - window]
    known = [value for value in values if value is not None]
    if not known or len(known) < len(values):
        return None
    return sum(known) / len(known)


def _cpu(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _throughput(predicate: NetBelow, rates: dict[str, NetRate] | None) -> float | None:
    if rates is None:
        return None
    rate = rates.get(predicate.interface or "total")
    if rate is None:
        return None
    match predicate.direction:
        case "down":
            return rate.down_kbps
        case "up":
            return rate.up_kbps
    return rate.down_kbps + rate.up_kbps


def _throughput_of(predicate: NetBelow) -> Callable[[Any], float | None]:
    return lambda rates: _throughput(predicate, rates)


def _battery_ok(predicate: BatteryLevel, state: PowerState | None) -> bool | None:
    if state is None or state.percent is None:
        return None  # unknown, or no battery at all
    if predicate.below is not None:
        return state.percent < predicate.below
    assert predicate.above is not None
    return state.percent > predicate.above


def _source_ok(predicate: PowerSource, state: PowerState | None) -> bool | None:
    if state is None or state.on_ac is None:
        return None
    return state.on_ac == (predicate.is_ == "ac")
