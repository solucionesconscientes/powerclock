import asyncio
from datetime import datetime, timedelta

import pytest

from powerclock.engine.clock import FakeClock, settle
from support import START


async def test_sleepers_wake_in_order_at_their_time() -> None:
    clock = FakeClock(START)
    woke: list[tuple[str, datetime]] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        woke.append((name, clock.now()))

    tasks = [asyncio.create_task(sleeper("b", 20)), asyncio.create_task(sleeper("a", 10))]
    await clock.advance(15)
    assert woke == [("a", START + timedelta(seconds=10))]
    await clock.advance(10)
    assert woke[1] == ("b", START + timedelta(seconds=20))
    assert clock.now() == START + timedelta(seconds=25)
    await asyncio.gather(*tasks)


async def test_jump_moves_only_the_wall_clock() -> None:
    clock = FakeClock(START)
    task = asyncio.create_task(clock.sleep(60))
    await settle()
    clock.jump(3600)
    assert clock.now() == START + timedelta(hours=1)
    assert clock.next_wakeup() == 60
    await clock.advance(60)
    assert task.done()
    assert clock.now() == START + timedelta(hours=1, seconds=60)


async def test_cancelled_sleepers_are_ignored() -> None:
    clock = FakeClock(START)
    task = asyncio.create_task(clock.sleep(10))
    await settle()
    task.cancel()
    await settle()
    assert clock.next_wakeup() is None
    await clock.advance(20)
    assert task.cancelled()


def test_needs_an_aware_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 9, 24))  # naive on purpose
