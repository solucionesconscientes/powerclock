import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from powerclock.config import Paths
from powerclock.daemon.core import Daemon
from powerclock.daemon.store import History
from powerclock.engine.clock import FakeClock, settle
from powerclock.platform.base import PowerAction
from powerclock.platform.fake import FakePlatform
from support import MADRID, START

ROOT = Path(__file__).resolve().parents[3]
BACKUP = json.loads((ROOT / "examples" / "backup-nocturno.json").read_text())
LOCK = {"type": "power", "action": "lock"}


def a_rule(**fields: Any) -> dict[str, Any]:
    return {
        "id": "test",
        "name": "Test",
        "trigger": {"type": "manual"},
        "actions": [{"type": "notify", "title": "PowerClock"}],
        **fields,
    }


def power_calls(fake: FakePlatform) -> list[PowerAction]:
    return [call.args[0] for call in fake.calls_to("power")]


async def runs(http: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await http.get("/history", params=params)
    return response.json()["runs"]


# ── Access ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic abc", "Bearer "])
async def test_a_valid_token_is_required(daemon: Daemon, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=daemon.app), base_url="http://powerclock", headers=headers
    ) as client:
        response = await client.get("/rules")
    assert response.status_code == 401


async def test_health(http: httpx.AsyncClient) -> None:
    health = (await http.get("/health")).json()
    assert health["backend"] == "fake"
    assert health["dry_run"] is False
    assert health["timezone"] == "Europe/Madrid"
    assert health["rules_errors"] == []


# ── Rules ───────────────────────────────────────────────────────────────────


async def test_rule_crud(http: httpx.AsyncClient, daemon: Daemon, paths: Paths) -> None:
    created = await http.post("/rules", json=BACKUP)
    assert created.status_code == 201
    assert created.json()["id"] == "backup-nocturno"
    assert (await http.get("/rules/backup-nocturno")).json() == created.json()
    assert [r["id"] for r in (await http.get("/rules")).json()] == ["backup-nocturno"]
    assert json.loads(paths.rules.read_text())["rules"][0]["id"] == "backup-nocturno"

    updated = await http.put("/rules/backup-nocturno", json={**BACKUP, "name": "Otro"})
    assert updated.json()["name"] == "Otro"
    assert daemon.engine.rules["backup-nocturno"].name == "Otro"

    assert (await http.delete("/rules/backup-nocturno")).status_code == 204
    assert (await http.get("/rules/backup-nocturno")).status_code == 404
    assert json.loads(paths.rules.read_text())["rules"] == []


async def test_created_rules_get_an_id(http: httpx.AsyncClient) -> None:
    data = a_rule()
    del data["id"]
    rule = (await http.post("/rules", json=data)).json()
    assert rule["id"].startswith("rule-")


async def test_rule_errors(http: httpx.AsyncClient) -> None:
    await http.post("/rules", json=a_rule())
    duplicate = await http.post("/rules", json=a_rule())
    assert (duplicate.status_code, duplicate.json()["detail"]) == (
        409,
        "a rule with id 'test' already exists",
    )
    invalid = await http.post("/rules", json=a_rule(id="other", warning="soon"))
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["warning"]
    mismatch = await http.put("/rules/test", json=a_rule(id="other"))
    assert mismatch.status_code == 422
    assert (await http.put("/rules/missing", json=a_rule())).status_code == 404


async def test_enable_rearms_a_countdown(
    http: httpx.AsyncClient, daemon: Daemon, clock: FakeClock
) -> None:
    countdown = {"type": "countdown", "duration": "30m"}
    await http.post("/rules", json=a_rule(enabled=False, trigger=countdown))
    await clock.advance(600)
    rule = (await http.post("/rules/test/enable")).json()
    assert rule["trigger"]["armed_at"] == "2026-09-24T08:10:00Z"
    assert (await http.get("/pending")).json()["next"][0]["at"] == "2026-09-24T08:40:00Z"
    assert (await http.post("/rules/test/disable")).json()["enabled"] is False
    assert (await http.get("/pending")).json()["next"] == []


async def test_run_a_rule_now(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    await http.post("/rules", json=a_rule(warning="0s", actions=[LOCK]))
    run = (await http.post("/rules/test/run")).json()
    assert run["cause"] == "manual"
    await settle()
    assert (await http.get(f"/runs/{run['id']}")).json()["state"] == "done"
    assert power_calls(fake) == [PowerAction.LOCK]
    assert (await http.post("/rules/missing/run")).status_code == 404


# ── Quick actions (the M4 definition of done) ───────────────────────────────


async def test_quick_shutdown_cancelled_before_it_fires(
    http: httpx.AsyncClient, daemon: Daemon, fake: FakePlatform, clock: FakeClock
) -> None:
    rule = (await http.post("/quick", json={"action": "shutdown", "in": "2m"})).json()
    assert rule["id"].startswith("quick-")
    assert rule["name"] == "Shut down in 2m"
    assert rule["one_shot"] is True
    pending = (await http.get("/pending")).json()
    assert pending["next"] == [
        {"rule_id": rule["id"], "name": "Shut down in 2m", "at": "2026-09-24T08:02:00Z"}
    ]

    cancelled = (await http.post("/cancel")).json()
    assert cancelled == {"cancelled": "rule", "rule_id": rule["id"], "name": "Shut down in 2m"}
    await settle()
    assert (await http.get("/rules")).json() == []
    [entry] = await runs(http)
    assert (entry["rule_id"], entry["state"], entry["reason"]) == (
        rule["id"],
        "cancelled",
        "cancelled before it fired",
    )
    await clock.advance(300)
    assert power_calls(fake) == []


async def test_quick_countdown_then_power(
    http: httpx.AsyncClient, fake: FakePlatform, clock: FakeClock
) -> None:
    rule = (await http.post("/quick", json={"action": "shutdown", "in": "2m"})).json()
    await clock.advance(120)
    [active] = (await http.get("/pending")).json()["active"]
    assert (active["state"], active["deadline"]) == ("warning", "2026-09-24T08:03:00Z")
    await clock.advance(60)
    assert power_calls(fake) == [PowerAction.SHUTDOWN]
    assert (await http.get("/rules")).json() == []  # quick rules go away once they end
    [entry] = await runs(http)
    assert (entry["rule_id"], entry["state"]) == (rule["id"], "done")


async def test_cancel_the_countdown_in_progress(
    http: httpx.AsyncClient, fake: FakePlatform, clock: FakeClock
) -> None:
    await http.post("/quick", json={"action": "reboot", "in": "1m"})
    await clock.advance(90)
    result = (await http.post("/cancel")).json()
    assert result["cancelled"] == "run"
    await clock.advance(120)
    assert power_calls(fake) == []
    [entry] = await runs(http)
    assert entry["state"] == "cancelled"
    assert (await http.post("/cancel")).status_code == 404


async def test_postpone_a_quick_action_before_it_fires(
    http: httpx.AsyncClient, clock: FakeClock
) -> None:
    rule = (await http.post("/quick", json={"action": "suspend", "in": "2m"})).json()
    result = (await http.post("/postpone", json={"delay": "10m"})).json()
    assert result == {
        "postponed": "rule",
        "rule_id": rule["id"],
        "name": "Suspend in 2m",
        "at": "2026-09-24T08:12:00Z",
    }
    assert (await http.get("/pending")).json()["next"][0]["at"] == "2026-09-24T08:12:00Z"


async def test_postpone_the_countdown_in_progress(
    http: httpx.AsyncClient, fake: FakePlatform, clock: FakeClock
) -> None:
    await http.post("/quick", json={"action": "shutdown", "in": "1m"})
    await clock.advance(90)
    [active] = (await http.get("/pending")).json()["active"]
    result = (await http.post("/postpone")).json()  # default 10 minutes
    assert result["at"] == "2026-09-24T08:12:00Z"
    by_id = await http.post(f"/runs/{active['id']}/postpone", json={"delay": "5m"})
    assert by_id.json()["at"] == "2026-09-24T08:17:00Z"
    await clock.advance(600)
    assert power_calls(fake) == []
    assert (await http.post("/runs/unknown/postpone", json={})).status_code == 409


async def test_quick_at_a_local_time(http: httpx.AsyncClient) -> None:
    rule = (await http.post("/quick", json={"action": "lock", "at": "10:30"})).json()
    assert rule["name"] == "Lock the screen at 2026-09-24 10:30"
    assert rule["trigger"]["when"] == "2026-09-24T08:30:00Z"
    past = await http.post("/quick", json={"action": "lock", "at": "2020-01-01 00:00"})
    assert (past.status_code, past.json()["detail"]) == (
        422,
        "'2020-01-01 00:00' is already in the past",
    )
    bad = await http.post("/quick", json={"action": "lock", "at": "soon"})
    assert bad.status_code == 422


async def test_quick_now(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    await http.post("/quick", json={"action": "lock", "warning": "0s"})
    await settle()
    assert power_calls(fake) == [PowerAction.LOCK]
    assert (await http.get("/rules")).json() == []


async def test_quick_command(http: httpx.AsyncClient) -> None:
    command = [sys.executable, "-c", "print('hecho')"]
    rule = (await http.post("/quick", json={"command": command})).json()
    assert rule["name"].startswith("Run python")
    for _ in range(200):  # a real (harmless) process: wait for it in real time
        if entries := await runs(http):
            break
        await asyncio.sleep(0.01)
    assert (entries[0]["state"], entries[0]["steps"][0]["detail"]) == ("done", "hecho")


@pytest.mark.parametrize(
    "payload",
    [
        {"in": "2m"},
        {"action": "shutdown", "command": ["x"]},
        {"action": "shutdown", "in": "2m", "at": "10:00"},
        {"action": "explode"},
        {"action": "shutdown", "in": "0s"},
    ],
)
async def test_quick_validation(http: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    assert (await http.post("/quick", json=payload)).status_code == 422


async def test_dry_run_daemon(make_daemon: Any, fake: FakePlatform) -> None:
    daemon = await make_daemon(dry_run=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=daemon.app),
        base_url="http://powerclock",
        headers={"Authorization": f"Bearer {daemon.token}"},
    ) as http:
        assert (await http.get("/health")).json()["dry_run"] is True
        await http.post("/quick", json={"action": "shutdown", "warning": "0s"})
        await settle()
        [entry] = await runs(http)
    assert entry["dry_run"] is True
    assert entry["steps"][0]["status"] == "dry_run"
    assert power_calls(fake) == []


# ── History, capabilities, schema ───────────────────────────────────────────


async def test_history_pages_and_filters(http: httpx.AsyncClient) -> None:
    await http.post("/rules", json=a_rule(id="uno"))
    await http.post("/rules", json=a_rule(id="dos"))
    for rule_id in ("uno", "dos", "uno"):
        await http.post(f"/rules/{rule_id}/run")
        await settle()
    data = (await http.get("/history", params={"limit": 2})).json()
    assert data["total"] == 3
    assert len(data["runs"]) == 2
    assert [r["rule_id"] for r in await runs(http, rule_id="uno")] == ["uno", "uno"]
    assert (await http.get("/history", params={"limit": 0})).status_code == 422


async def test_capabilities_and_schema(http: httpx.AsyncClient) -> None:
    rows = (await http.get("/capabilities")).json()
    assert {"power.shutdown", "power_source"} <= {row["id"] for row in rows}
    schema = (await http.get("/schema/rule")).json()
    assert schema["title"] == "Rule"


# ── Files: persistence, hand edits, errors, missed runs ─────────────────────


async def test_rules_survive_a_restart(
    http: httpx.AsyncClient, daemon: Daemon, make_daemon: Any
) -> None:
    await http.post("/rules", json=BACKUP)
    await daemon.stop()
    again = await make_daemon()
    assert list(again.engine.rules) == ["backup-nocturno"]


async def test_hand_edits_are_picked_up(
    http: httpx.AsyncClient, daemon: Daemon, paths: Paths
) -> None:
    await http.post("/rules", json=a_rule(id="uno"))
    data = json.loads(paths.rules.read_text())
    data["rules"].append(a_rule(id="dos", trigger={"type": "cron", "expr": "0 11 * * *"}))
    paths.rules.write_text(json.dumps(data))
    daemon.reload_rules()
    assert sorted(daemon.engine.rules) == ["dos", "uno"]
    assert daemon.engine.pending() == {"dos": datetime(2026, 9, 24, 9, 0, tzinfo=UTC)}

    paths.rules.write_text("{broken")
    daemon.reload_rules()
    assert sorted(daemon.engine.rules) == ["dos", "uno"]  # still running
    health = (await http.get("/health")).json()
    assert health["rules_errors"][0].startswith("invalid JSON")
    blocked = await http.post("/rules", json=a_rule(id="tres"))
    assert blocked.status_code == 409
    assert paths.rules.read_text() == "{broken"


async def test_missed_while_the_daemon_was_stopped(
    make_daemon: Any, paths: Paths, fake: FakePlatform
) -> None:
    fake.tz = MADRID
    first = await make_daemon()
    first.create_rule(a_rule(trigger={"type": "cron", "expr": "0 3 * * *"}))
    await first.stop()
    history = History(paths.history)
    history.set_last_alive(START - timedelta(days=1))  # stopped since yesterday morning
    history.close()
    second = await make_daemon()
    await settle()
    [entry] = second.history.list()
    assert (entry.rule_id, entry.state, entry.missed) == ("test", "skipped", True)
    assert entry.scheduled_for == datetime(2026, 9, 24, 1, 0, tzinfo=UTC)


# ── Wake-ups (M5) ────────────────────────────────────────────────────────────


async def test_wake_request(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    rule = (await http.post("/wake", json={"at": "2026-09-25 07:30"})).json()
    assert rule["name"] == "Turn on at 2026-09-25 07:30"
    assert (rule["wake"], rule["one_shot"]) == (True, True)
    await settle()
    wake = (await http.get("/pending")).json()["wake"]
    assert wake == {"at": "2026-09-25T05:28:00Z", "error": None}  # 2 min before 07:30 Madrid
    assert fake.wake == datetime(2026, 9, 25, 5, 28, tzinfo=UTC)
    assert (await http.post("/wake", json={"at": "yesterday"})).status_code == 422


async def test_suspend_and_wake_up_later(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    rule = (
        await http.post("/quick", json={"action": "suspend", "at": "23:30", "wake_at": "07:30"})
    ).json()
    names = sorted(r["name"] for r in (await http.get("/rules")).json())
    assert names == ["Suspend at 2026-09-24 23:30", "Turn on at 2026-09-25 07:30"]
    assert rule["wake"] is False
    await settle()
    assert fake.wake == datetime(2026, 9, 25, 5, 28, tzinfo=UTC)


async def test_wake_to_run_a_program(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    payload = {"command": ["backup.sh"], "at": "2026-09-25 03:00", "wake": True}
    rule = (await http.post("/quick", json=payload)).json()
    assert rule["wake"] is True
    await settle()
    assert fake.wake == datetime(2026, 9, 25, 0, 58, tzinfo=UTC)
    now = await http.post("/quick", json={"command": ["x"], "wake": True})  # no time
    assert now.status_code == 422
    assert "time trigger" in json.dumps(now.json())


async def test_wake_errors_are_visible(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    async def refuse(when: datetime) -> None:
        from powerclock.platform.base import NotSupported

        raise NotSupported(
            "wake", "powerclock-helper is not installed", fix_hint="powerclock helper install"
        )

    fake.wake_set = refuse  # type: ignore[method-assign]
    await http.post("/wake", json={"at": "07:30"})
    await settle()
    wake = (await http.get("/pending")).json()["wake"]
    assert wake["at"] is None
    assert "powerclock helper install" in wake["error"]


# ── Applications ──────────────────────────────────────────────────────────────


async def test_apps_and_recipes(http: httpx.AsyncClient) -> None:
    found = (await http.get("/apps")).json()
    by_id = {app["id"]: app for app in found}
    assert by_id["vlc"]["recipes"] == ["vlc.loop", "vlc.once", "vlc.stream"]
    assert by_id["one.ablaze.floorp"]["flatpak"] == "one.ablaze.floorp"
    listed = (await http.get("/recipes")).json()
    assert {"id", "apps", "label", "args", "inputs"} <= set(listed[0])


async def test_quick_opens_an_app(http: httpx.AsyncClient, fake: FakePlatform) -> None:
    await http.get("/apps")  # the daemon learns the names
    reply = await http.post("/quick", json={"app": "vlc", "args": ["radio.m3u"], "in": "5m"})
    rule = reply.json()
    assert rule["name"] == "Open VLC media player in 5m"
    assert rule["actions"] == [
        {
            "type": "launch",
            "app": "vlc",
            "args": ["radio.m3u"],
            "recipe": None,
            "window": None,
            "keep_open": False,
            "stop_signal": "TERM",
            "wait_desktop": "2m",
        }
    ]
    bad = await http.post("/quick", json={"action": "shutdown", "args": ["x"]})
    assert bad.status_code == 422
