"""GUI tests: offscreen Qt against a real daemon (fake backend, fake clock, fake sensors)
reached in-process; nothing touches the system or shows a window."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="the GUI extra is not installed")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import httpx
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from guisupport import pump
from powerclock.config import Paths
from powerclock.connection import Endpoint
from powerclock.daemon.core import Daemon
from powerclock.engine.clock import FakeClock
from powerclock.gui import tasks
from powerclock.gui.client import DaemonLink, HttpApi
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings
from support import MADRID


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication(["powerclock-gui-tests"])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(autouse=True)
def _close_dialogs(qapp: QApplication) -> Iterator[None]:
    """A message box or dialog left open by one test must not be found by the next."""
    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QDialog) and widget.isVisible():
            widget.done(0)
            widget.close()


@pytest.fixture
def errors() -> Iterator[list[Exception]]:
    """Errors the GUI would show in a message box."""
    found: list[Exception] = []

    def sink(error: Exception, parent: QWidget | None) -> None:
        found.append(error)

    previous = tasks.set_error_sink(sink)
    yield found
    tasks.set_error_sink(previous)


@pytest.fixture
async def daemon(
    tmp_path: Path, clock: FakeClock, fake: FakePlatform, readings: FakeReadings
) -> AsyncIterator[Daemon]:
    fake.tz = MADRID
    daemon = Daemon(  # not a dry run: the fake backend only records power actions
        fake,
        paths=Paths(tmp_path / "c", tmp_path / "d"),
        clock=clock,
        readings=readings,
        dry_run=False,
    )
    await daemon.start()
    yield daemon
    await daemon.stop()


@pytest.fixture
async def link(qapp: QApplication, daemon: Daemon) -> AsyncIterator[DaemonLink]:
    api = HttpApi(
        locate=lambda: Endpoint("http://powerclock", daemon.token),
        transport=httpx.ASGITransport(app=daemon.app),
    )

    async def stream() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "connected"}
        with daemon.hub.subscribe() as queue:
            while True:
                yield (await queue.get()).model_dump(mode="json")

    link = DaemonLink(api, stream, debounce=0)
    link.start()
    await pump()
    yield link
    await link.stop()
    await api.close()
