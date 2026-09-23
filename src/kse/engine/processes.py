"""Closing applications by process name (the close_app action). psutil works on every OS."""

import asyncio
import contextlib
import os
from datetime import timedelta
from typing import Protocol

import psutil


class ProcessManager(Protocol):
    async def close(self, name: str, grace: timedelta) -> int:
        """Ask every process of the current user called `name` to quit, kill the ones
        still running after `grace`, and return how many there were."""
        ...


class PsutilProcesses:
    async def close(self, name: str, grace: timedelta) -> int:
        return await asyncio.to_thread(_close, name, grace.total_seconds())


def _close(name: str, grace: float) -> int:
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
            process.terminate()
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

    async def close(self, name: str, grace: timedelta) -> int:
        self.closed.append((name, grace))
        return self.running.pop(name, 0)
