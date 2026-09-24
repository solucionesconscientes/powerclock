"""The GUI's link with the daemon: requests, events and being offline."""

from typing import Any

import httpx
import pytest

from guisupport import pump
from powerclock.connection import ApiError, DaemonUnavailable, Endpoint
from powerclock.daemon.core import Daemon
from powerclock.engine.clock import FakeClock
from powerclock.gui.client import DaemonLink, HttpApi


async def test_online_with_health_and_pending(link: DaemonLink, daemon: Daemon) -> None:
    assert link.online
    assert link.health is not None
    assert link.health["backend"] == "fake"
    assert link.pending["next"] == []
    changes: list[bool] = []
    link.changed.connect(lambda: changes.append(link.online))
    await link.api.post("/quick", json={"action": "shutdown", "in": "1h"})
    await pump()
    assert changes  # the rule_changed event refreshed /pending
    [entry] = link.pending["next"]
    assert entry["name"] == "Shut down in 1h"


async def test_events_reach_the_gui(link: DaemonLink, clock: FakeClock) -> None:
    events: list[dict[str, Any]] = []
    link.event.connect(events.append)
    await link.api.post("/quick", json={"action": "lock", "warning": "0s"})
    await pump()
    assert "run_finished" in [event["type"] for event in events]


async def test_api_errors(link: DaemonLink) -> None:
    with pytest.raises(ApiError) as info:
        await link.api.get("/rules/missing")
    assert info.value.status == 404
    with pytest.raises(ApiError, match="set exactly one of"):
        await link.api.post("/quick", json={"in": "1m"})


async def test_offline_when_the_daemon_has_never_run(qapp: object) -> None:
    def nowhere() -> Endpoint:
        raise DaemonUnavailable("no API token yet")

    async def stream() -> Any:
        nowhere()
        yield {}

    link = DaemonLink(HttpApi(locate=nowhere), stream, debounce=0)
    link.start()
    await pump()
    assert not link.online
    assert link.error == "no API token yet"
    await link.stop()


async def test_offline_when_the_daemon_does_not_answer(qapp: object) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    api = HttpApi(
        locate=lambda: Endpoint("http://powerclock", "token"), transport=httpx.MockTransport(refuse)
    )
    with pytest.raises(DaemonUnavailable, match="not running"):
        await api.get("/health")
    link = DaemonLink(api, None, debounce=0)
    link.refresh()
    await pump()
    assert not link.online
    await api.close()
