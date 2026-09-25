"""What the evaluator asks the sensors, and the raw readings the sensor hub is built on."""

from dataclasses import dataclass
from typing import Protocol

from powerclock.models import (
    Active,
    BatteryLevel,
    CpuBelow,
    DesktopSession,
    Device,
    FileExists,
    Idle,
    MediaPlaying,
    NetBelow,
    PowerSource,
    ProcessRunning,
    SshSession,
    Temperature,
    UsedToday,
    WifiSsid,
)

SensorPredicate = (
    ProcessRunning
    | PowerSource
    | BatteryLevel
    | Idle
    | CpuBelow
    | NetBelow
    | MediaPlaying
    | SshSession
    | WifiSsid
    | DesktopSession
    | Active
    | UsedToday
    | FileExists
    | Device
    | Temperature
)


class SensorReader(Protocol):
    async def check(self, predicate: SensorPredicate) -> bool | None:
        """Whether the predicate holds now (sustained for its `for`, if it has one).

        None means the value cannot be known, e.g. no battery or no media player API.
        """
        ...


# ── Raw readings ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NetRate:
    down_kbps: float
    up_kbps: float


@dataclass(frozen=True)
class PowerState:
    percent: float | None  # None: no battery
    on_ac: bool | None  # None: cannot tell


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    started: float  # creation time: tells a process apart from a later one with its PID


class Readings(Protocol):
    """One raw value per sensor. None (or an exception) means unknown right now."""

    async def idle(self) -> float | None:
        """Seconds since the last user input."""
        ...

    async def cpu(self) -> float | None:
        """Average CPU usage (%) since the previous call."""
        ...

    async def net(self) -> dict[str, NetRate] | None:
        """Throughput since the previous call, per interface and "total"."""
        ...

    async def processes(self) -> list[ProcessInfo] | None: ...

    async def power(self) -> PowerState | None: ...

    async def ssh_sessions(self) -> int | None: ...

    async def media_playing(self) -> bool | None: ...

    async def wifi(self) -> str | None:
        """SSID of the Wi-Fi network; "" when not on Wi-Fi."""
        ...

    async def desktop(self) -> bool | None:
        """Whether a desktop session is up (applications can be opened in it)."""
        ...

    async def devices(self) -> list[str] | None:
        """Names of the connected devices (USB products, disk labels, Bluetooth…)."""
        ...

    async def temperatures(self) -> dict[str, float] | None:
        """The hottest reading of each temperature sensor, in °C."""
        ...


class NoReadings:
    """Sensors of a machine that tells nothing: every value is unknown."""

    async def idle(self) -> float | None:
        return None

    async def cpu(self) -> float | None:
        return None

    async def net(self) -> dict[str, NetRate] | None:
        return None

    async def processes(self) -> list[ProcessInfo] | None:
        return None

    async def power(self) -> PowerState | None:
        return None

    async def ssh_sessions(self) -> int | None:
        return None

    async def media_playing(self) -> bool | None:
        return None

    async def wifi(self) -> str | None:
        return None

    async def desktop(self) -> bool | None:
        return None

    async def devices(self) -> list[str] | None:
        return None

    async def temperatures(self) -> dict[str, float] | None:
        return None
