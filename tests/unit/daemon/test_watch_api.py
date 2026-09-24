"""Quick actions that wait for a condition (--when-*) and what /pending shows about them."""

from typing import Any

import httpx
import pytest

from kse.engine.clock import FakeClock, settle
from kse.platform.base import PowerAction
from kse.platform.fake import FakePlatform
from kse.sensors.fake import FakeReadings


async def quick(http: httpx.AsyncClient, **payload: Any) -> dict[str, Any]:
    response = await http.post("/quick", json={"action": "shutdown", **payload})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("payload", "name", "trigger"),
    [
        (
            {"when_idle": "20m"},
            "Shut down when idle for 20m",
            {"type": "idle", "for": "20m"},
        ),
        (
            {"when_exits": "ffmpeg"},
            "Shut down when ffmpeg exits",
            {"type": "process_exit", "name": "ffmpeg", "pid": None},
        ),
        (
            {"when_exits": "4321"},
            "Shut down when PID 4321 exits",
            {"type": "process_exit", "name": None, "pid": 4321},
        ),
        (
            {"when_cpu_below": 10},
            "Shut down when the CPU is below 10 % for 5m",
            {"type": "cpu_below", "percent": 10.0, "for": "5m"},
        ),
        (
            {"when_net_below": 50, "for": "10m"},
            "Shut down when the network is below 50 kbit/s for 10m",
            {
                "type": "net_below",
                "kbps": 50.0,
                "for": "10m",
                "direction": "both",
                "interface": None,
            },
        ),
    ],
)
async def test_quick_when(
    http: httpx.AsyncClient, payload: dict[str, Any], name: str, trigger: dict[str, Any]
) -> None:
    rule = await quick(http, **payload)
    assert (rule["name"], rule["trigger"], rule["one_shot"]) == (name, trigger, True)
    await settle()
    pending = (await http.get("/pending")).json()
    assert pending["next"] == []
    [watch] = pending["watching"]
    assert (watch["rule_id"], watch["name"], watch["armed"]) == (rule["id"], name, True)
    assert watch["checked_at"] is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"in": "2m", "when_idle": "20m"},
        {"when_idle": "20m", "when_exits": "ffmpeg"},
        {"when_idle": "20m", "for": "5m"},  # `for` is for CPU and network only
        {"when_exits": "0"},
        {"when_exits": ""},
        {"when_cpu_below": 0},
        {"when_cpu_below": 150},
        {"when_net_below": 50, "for": "0s"},
        {"when_idle": "20m", "wake": True},  # wake-ups need a time
    ],
)
async def test_quick_when_validation(http: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    response = await http.post("/quick", json={"action": "shutdown", **payload})
    assert response.status_code == 422, response.text


async def test_shut_down_when_the_render_ends(
    http: httpx.AsyncClient, fake: FakePlatform, readings: FakeReadings, clock: FakeClock
) -> None:
    rule = await quick(http, when_exits="ffmpeg", warning="0s")
    await clock.advance(30)
    [watch] = (await http.get("/pending")).json()["watching"]
    assert watch["value"] == "not_seen"
    readings.start("ffmpeg", pid=100)
    await clock.advance(3)
    readings.stop(100)
    await clock.advance(3)
    assert [call.args[0] for call in fake.calls_to("power")] == [PowerAction.SHUTDOWN]
    assert (await http.get("/rules")).json() == []  # quick rules go away once they end
    [entry] = (await http.get("/history")).json()["runs"]
    assert (entry["rule_id"], entry["cause"], entry["state"]) == (rule["id"], "trigger", "done")


async def test_cancel_a_quick_action_that_waits(
    http: httpx.AsyncClient, fake: FakePlatform, readings: FakeReadings, clock: FakeClock
) -> None:
    await quick(http, when_idle="20m")
    rule = await quick(http, when_idle="30m")
    postponed = await http.post("/postpone", json={"delay": "10m"})
    assert postponed.status_code == 409
    assert "cancel it instead" in postponed.json()["detail"]
    cancelled = (await http.post("/cancel")).json()
    assert cancelled == {
        "cancelled": "rule",
        "rule_id": rule["id"],
        "name": "Shut down when idle for 30m",
    }  # the latest one first
    await settle()
    assert len((await http.get("/pending")).json()["watching"]) == 1
    assert (await http.post("/cancel")).status_code == 200
    await settle()
    assert (await http.get("/pending")).json()["watching"] == []
    readings.idle_seconds = 3600
    await clock.advance(60)
    assert fake.calls_to("power") == []


async def test_timed_quick_actions_are_cancelled_first(http: httpx.AsyncClient) -> None:
    waiting = await quick(http, when_idle="20m")
    timed = await quick(http, **{"in": "1h"})
    assert (await http.post("/cancel")).json()["rule_id"] == timed["id"]
    assert (await http.post("/cancel")).json()["rule_id"] == waiting["id"]
