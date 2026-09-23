"""Helpers shared by the tests (importable thanks to `pythonpath = ["tests"]`)."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from kse.engine.clock import FakeClock
from kse.models import Rule

START = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)  # Thursday, 10:00 in Madrid
MADRID = ZoneInfo("Europe/Madrid")


def rule(**fields: Any) -> Rule:
    """A valid rule; any field can be overridden. No countdown unless `warning` is given."""
    data: dict[str, Any] = {
        "id": "test",
        "name": "Test",
        "trigger": {"type": "manual"},
        "actions": [{"type": "notify", "title": "KSE"}],
        "warning": "0s",
    }
    data.update(fields)
    return Rule.model_validate(data)


async def until_sleeping(clock: FakeClock, seconds: float = 5.0) -> None:
    """Wait (in real time) until some task sleeps on the fake clock, e.g. after a
    subprocess has started."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while clock.next_wakeup() is None:
        if loop.time() > deadline:
            raise TimeoutError("nothing is sleeping on the fake clock")
        await asyncio.sleep(0.01)
