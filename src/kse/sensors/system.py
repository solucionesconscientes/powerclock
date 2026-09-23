"""Raw readings from psutil: CPU, network, processes, battery/AC and SSH sessions.

History and the `for` of predicates are added on top of these in M6.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

# Interfaces that duplicate traffic or never leave the machine.
IGNORED_INTERFACES = ("lo", "veth", "docker", "br-", "virbr")


@dataclass(frozen=True)
class Battery:
    percent: float
    plugged: bool | None


@dataclass(frozen=True)
class NetRate:
    down_kbps: float
    up_kbps: float


def cpu_percent() -> float:
    """Average CPU usage since the previous call (the first call primes the counter)."""
    return psutil.cpu_percent(interval=None)


def process_names() -> set[str]:
    return {name for p in psutil.process_iter(["name"]) if (name := p.info["name"])}


def battery() -> Battery | None:
    state = psutil.sensors_battery()
    if state is None:
        return None
    return Battery(percent=state.percent, plugged=state.power_plugged)


def on_ac() -> bool | None:
    """Plugged in? A machine without a battery (desktop, server) always is."""
    state = battery()
    return True if state is None else state.plugged


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
