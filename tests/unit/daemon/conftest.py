from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest

from powerclock.config import Paths
from powerclock.daemon.core import Daemon
from powerclock.engine.clock import FakeClock
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings
from support import MADRID

MakeDaemon = Callable[..., Awaitable[Daemon]]


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data")


@pytest.fixture
async def make_daemon(
    paths: Paths, clock: FakeClock, fake: FakePlatform, readings: FakeReadings
) -> AsyncIterator[MakeDaemon]:
    """Start daemons on the same files (to test restarts); all are stopped at the end."""
    started: list[Daemon] = []

    async def make(dry_run: bool = False) -> Daemon:
        daemon = Daemon(fake, paths=paths, clock=clock, dry_run=dry_run, readings=readings)
        await daemon.start()
        started.append(daemon)
        return daemon

    yield make
    for daemon in started:
        if daemon.engine.running:  # not stopped by the test itself
            await daemon.stop()


@pytest.fixture
async def daemon(make_daemon: MakeDaemon, fake: FakePlatform) -> Daemon:
    fake.tz = MADRID
    return await make_daemon()


@pytest.fixture
async def http(daemon: Daemon) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=daemon.app),
        base_url="http://powerclock",
        headers={"Authorization": f"Bearer {daemon.token}"},
    ) as client:
        yield client
