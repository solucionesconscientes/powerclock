"""Raw readings from psutil (CPU, network, processes, battery/AC, SSH sessions) and the
backend (idle time, media, Wi-Fi). History and the `for` of predicates live in the hub."""

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

from powerclock.platform.base import NotSupported, PlatformBackend
from powerclock.sensors.base import NetRate, PowerState, ProcessInfo

# Interfaces that duplicate traffic or never leave the machine.
IGNORED_INTERFACES = ("lo", "veth", "docker", "br-", "virbr")


@dataclass(frozen=True)
class Battery:
    percent: float
    plugged: bool | None


def cpu_percent() -> float:
    """Average CPU usage since the previous call (the first call primes the counter)."""
    return psutil.cpu_percent(interval=None)


def process_table() -> list[ProcessInfo]:
    return [
        ProcessInfo(pid=p.pid, name=p.info["name"], started=p.info["create_time"] or 0.0)
        for p in psutil.process_iter(["name", "create_time"])
        if p.info["name"]
    ]


def battery() -> Battery | None:
    state = psutil.sensors_battery()
    if state is None:
        return None
    return Battery(percent=state.percent, plugged=state.power_plugged)


def power_state() -> PowerState:
    """Battery and AC. A machine without a battery (desktop, server) is always on AC."""
    state = battery()
    if state is None:
        return PowerState(percent=None, on_ac=True)
    return PowerState(percent=state.percent, on_ac=state.plugged)


def ssh_sessions() -> int:
    """Logged-in users that come from another host (tmux panes and X displays excluded)."""
    return sum(
        1 for user in psutil.users() if user.host and not user.host.startswith((":", "tmux("))
    )


class NetMeter:
    """Throughput between two consecutive samples, per interface and in total."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: tuple[float, dict[str, tuple[int, int]]] | None = None

    def sample(self) -> dict[str, NetRate] | None:
        """Rates since the previous sample (None on the first one). "total" sums the
        physical interfaces."""
        now = self._clock()
        counters = {
            name: (io.bytes_recv, io.bytes_sent)
            for name, io in psutil.net_io_counters(pernic=True).items()
        }
        previous, self._last = self._last, (now, counters)
        if previous is None or now <= previous[0]:
            return None
        elapsed = now - previous[0]
        rates: dict[str, NetRate] = {}
        for name, (received, sent) in counters.items():
            before = previous[1].get(name)
            if before is None:
                continue
            rates[name] = NetRate(
                down_kbps=max(0, received - before[0]) * 8 / 1000 / elapsed,
                up_kbps=max(0, sent - before[1]) * 8 / 1000 / elapsed,
            )
        physical = [rate for name, rate in rates.items() if not name.startswith(IGNORED_INTERFACES)]
        rates["total"] = NetRate(
            down_kbps=sum(rate.down_kbps for rate in physical),
            up_kbps=sum(rate.up_kbps for rate in physical),
        )
        return rates


class SystemReadings:
    """The real sensors. psutil calls run in a thread so they never block the event loop."""

    def __init__(self, backend: PlatformBackend) -> None:
        self._backend = backend
        self._net = NetMeter()
        with contextlib.suppress(Exception):
            cpu_percent()  # the first call only primes the counter

    async def idle(self) -> float | None:
        try:
            return await self._backend.idle_seconds()
        except NotSupported:
            return None

    async def cpu(self) -> float | None:
        return await asyncio.to_thread(cpu_percent)

    async def net(self) -> dict[str, NetRate] | None:
        return await asyncio.to_thread(self._net.sample)

    async def processes(self) -> list[ProcessInfo] | None:
        return await asyncio.to_thread(process_table)

    async def power(self) -> PowerState | None:
        return await asyncio.to_thread(power_state)

    async def ssh_sessions(self) -> int | None:
        return await asyncio.to_thread(ssh_sessions)

    async def media_playing(self) -> bool | None:
        try:
            return await self._backend.media_playing()
        except NotSupported:
            return None

    async def wifi(self) -> str | None:
        try:
            ssid = await self._backend.wifi_ssid()
        except NotSupported:
            return None
        return ssid or ""
