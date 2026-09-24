"""Time source. The engine reads the time and sleeps only through a Clock, so tests can
drive time deterministically with FakeClock."""

import asyncio
import heapq
import itertools
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current wall-clock time, timezone-aware (UTC)."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Sleep on a monotonic clock, which does not advance while the machine is suspended."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


async def settle(rounds: int = 20) -> None:
    """Let every task that is ready run until it blocks again."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeClock:
    """Manual clock for tests: `advance` moves both clocks, `jump` only the wall clock
    (as a suspend or a manual clock change would)."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start")
        self._wall = start.astimezone(UTC)
        self._mono_us = 0  # integer microseconds: no float drift
        self._sleepers: list[tuple[int, int, asyncio.Future[None]]] = []
        self._order = itertools.count()

    def now(self) -> datetime:
        return self._wall

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        deadline = self._mono_us + _microseconds(seconds)
        heapq.heappush(self._sleepers, (deadline, next(self._order), future))
        await future

    def next_wakeup(self) -> float | None:
        """Seconds until the earliest pending sleeper wakes up (None: nobody sleeps)."""
        pending = [deadline for deadline, _, future in self._sleepers if not future.done()]
        return (min(pending) - self._mono_us) / 1_000_000 if pending else None

    async def advance(self, seconds: float) -> None:
        target = self._mono_us + _microseconds(seconds)
        await settle()
        while self._sleepers and self._sleepers[0][0] <= target:
            deadline, _, future = heapq.heappop(self._sleepers)
            if future.done():  # its task was cancelled
                continue
            self._move_to(deadline)
            future.set_result(None)
            await settle()
        self._move_to(target)
        await settle()

    def jump(self, seconds: float) -> None:
        self._wall += timedelta(microseconds=_microseconds(seconds))

    def _move_to(self, mono_us: int) -> None:
        if mono_us > self._mono_us:
            self._wall += timedelta(microseconds=mono_us - self._mono_us)
            self._mono_us = mono_us


def _microseconds(seconds: float) -> int:
    return round(seconds * 1_000_000)
