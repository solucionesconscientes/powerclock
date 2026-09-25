"""Closing applications by process name (the close_app action). psutil works on every OS."""

import asyncio
import contextlib
import os
import signal as signals
from datetime import timedelta
from typing import Protocol

import psutil

from powerclock.platform.base import StopSignal

SIGNALS: dict[str, int] = {"TERM": signals.SIGTERM, "INT": signals.SIGINT, "HUP": signals.SIGHUP}


class ProcessManager(Protocol):
    async def close(self, name: str, grace: timedelta, signal: StopSignal = "TERM") -> int:
        """Ask every process of the current user called `name` to quit (with `signal`),
        kill the ones still running after `grace`, and return how many there were."""
        ...


class PsutilProcesses:
    async def close(self, name: str, grace: timedelta, signal: StopSignal = "TERM") -> int:
        return await asyncio.to_thread(_close, name, grace.total_seconds(), SIGNALS[signal])


def _close(name: str, grace: float, signum: int = signals.SIGTERM) -> int:
    user = psutil.Process().username()
    targets = [
        process
        for process in psutil.process_iter(["name", "username"])
        if process.info["name"] == name
        and process.info["username"] == user
        and process.pid != os.getpid()
    ]
    for process in targets:
        with contextlib.suppress(psutil.NoSuchProcess):
            process.send_signal(signum)
    _, alive = psutil.wait_procs(targets, timeout=grace)
    for process in alive:
        with contextlib.suppress(psutil.NoSuchProcess):
            process.kill()
    return len(targets)


class FakeProcesses:
    """For tests: pretends `running[name]` processes exist and records every request."""

    def __init__(self, running: dict[str, int] | None = None) -> None:
        self.running = dict(running or {})
        self.closed: list[tuple[str, timedelta]] = []
        self.signals: list[StopSignal] = []

    async def close(self, name: str, grace: timedelta, signal: StopSignal = "TERM") -> int:
        self.closed.append((name, grace))
        self.signals.append(signal)
        return self.running.pop(name, 0)
