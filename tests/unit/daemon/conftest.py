from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest

from kse.config import Paths
from kse.daemon.core import Daemon
from kse.engine.clock import FakeClock
from kse.platform.fake import FakePlatform
from support import MADRID

MakeDaemon = Callable[..., Awaitable[Daemon]]


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data")


@pytest.fixture
async def make_daemon(
    paths: Paths, clock: FakeClock, fake: FakePlatform
) -> AsyncIterator[MakeDaemon]:
    """Start daemons on the same files (to test restarts); all are stopped at the end."""
    started: list[Daemon] = []

    async def make(dry_run: bool = False) -> Daemon:
        daemon = Daemon(fake, paths=paths, clock=clock, dry_run=dry_run)
        await daemon.start()
        started.append(daemon)
        return daemon

    yield make
    for daemon in started:
        if daemon.engine._loop is not None:  # not stopped by the test itself
            await daemon.stop()


@pytest.fixture
async def daemon(make_daemon: MakeDaemon, fake: FakePlatform) -> Daemon:
    fake.tz = MADRID
    return await make_daemon()


@pytest.fixture
async def http(daemon: Daemon) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=daemon.app),
        base_url="http://kse",
        headers={"Authorization": f"Bearer {daemon.token}"},
    ) as client:
        yield client
