"""The /events WebSocket, through FastAPI's TestClient (the daemon runs in its thread)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from kse.config import Paths
from kse.daemon.core import Daemon
from kse.platform.fake import FakePlatform

RULE = {
    "id": "test",
    "name": "Test",
    "trigger": {"type": "manual"},
    "actions": [{"type": "notify", "title": "KSE"}],
}


@pytest.fixture
def daemon(tmp_path: Path) -> Daemon:
    return Daemon(FakePlatform(), paths=Paths(tmp_path / "c", tmp_path / "d"), dry_run=True)


def test_events_reach_subscribers(daemon: Daemon) -> None:
    auth = {"Authorization": f"Bearer {daemon.token}"}
    with (
        TestClient(daemon.app) as client,
        client.websocket_connect("/events", headers=auth) as ws,
    ):
        client.post("/rules", json=RULE, headers=auth)
        event = ws.receive_json()
        assert (event["type"], event["rule_id"], event["data"]) == (
            "rule_changed",
            "test",
            {"change": "created"},
        )
        client.post("/rules/test/run", headers=auth)
        types = [ws.receive_json()["type"] for _ in range(2)]
        assert types == ["run_started", "run_finished"]


def test_token_in_the_query_string(daemon: Daemon) -> None:
    with (
        TestClient(daemon.app) as client,
        client.websocket_connect(f"/events?token={daemon.token}") as ws,
    ):
        client.post("/rules", json=RULE, headers={"Authorization": f"Bearer {daemon.token}"})
        assert ws.receive_json()["type"] == "rule_changed"


@pytest.mark.parametrize("url", ["/events", "/events?token=wrong"])
def test_events_need_the_token(daemon: Daemon, url: str) -> None:
    with (
        TestClient(daemon.app) as client,
        pytest.raises(WebSocketDisconnect) as info,
        client.websocket_connect(url),
    ):
        pass
    assert info.value.code == 1008
