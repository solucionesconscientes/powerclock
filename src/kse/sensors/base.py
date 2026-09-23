"""What the evaluator asks the sensors.

Real readers arrive in M3 (psutil, D-Bus) and M6 (history for `for`).
"""

from typing import Protocol

from kse.models import (
    BatteryLevel,
    CpuBelow,
    Idle,
    MediaPlaying,
    NetBelow,
    PowerSource,
    ProcessRunning,
    SshSession,
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
)


class SensorReader(Protocol):
    async def check(self, predicate: SensorPredicate) -> bool | None:
        """Whether the predicate holds now (sustained for its `for`, if it has one).

        None means the value cannot be known, e.g. no battery or no media player API.
        """
        ...


class UnknownSensors:
    """Reader used until real sensors exist: every value is unknown."""

    async def check(self, predicate: SensorPredicate) -> bool | None:
        return None
