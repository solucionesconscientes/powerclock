"""Wake-on-LAN and the use and savings statistics (M18)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from powerclock.config import Paths
from powerclock.daemon.core import AWAKE_GAP, Daemon
from powerclock.daemon.store import History
from powerclock.engine import wol
from powerclock.engine.clock import FakeClock
from powerclock.engine.evaluator import Evaluator
from powerclock.engine.executor import Executor
from powerclock.engine.runs import Event
from powerclock.engine.savings import Period, default_watts, stats
from powerclock.labels import savings_text
from powerclock.models import WakeLanStep
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.base import PowerState
from powerclock.sensors.fake import FakeReadings, FakeSensors
from support import MADRID, START, rule

MAC = "00:1a:2b:3c:4d:5e"


def at(hours: float) -> datetime:
    return START + timedelta(hours=hours)


# ── Wake-on-LAN ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mac", [MAC, "00-1A-2B-3C-4D-5E", "001a2b3c4d5e"])
def test_magic_packet(mac: str) -> None:
    packet = wol.magic_packet(mac)
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("001a2b3c4d5e") * 16
    assert WakeLanStep(mac=mac).port == 9


@pytest.mark.parametrize("mac", ["00:1a:2b:3c:4d", "zz:1a:2b:3c:4d:5e", "nas"])
def test_bad_mac_addresses_are_refused(mac: str) -> None:
    with pytest.raises(ValueError, match="pattern"):
        WakeLanStep(mac=mac)


async def test_the_packet_is_sent_by_udp_broadcast(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[bytes, str, int]] = []

    async def udp(packet: bytes, host: str, port: int) -> None:
        sent.append((packet, host, port))

    monkeypatch.setattr(wol, "_udp", udp)
    await wol.send(MAC, "192.168.1.255", 7)
    assert sent == [(wol.magic_packet(MAC), "192.168.1.255", 7)]


@pytest.mark.parametrize("dry_run", [False, True])
async def test_wake_lan_step(fake: FakePlatform, clock: FakeClock, dry_run: bool) -> None:
    sent: list[tuple[str, str, int]] = []

    async def sender(mac: str, broadcast: str, port: int) -> None:
        sent.append((mac, broadcast, port))

    executor = Executor(
        fake, Evaluator(FakeSensors(), clock), clock, dry_run=dry_run, wake_lan=sender
    )
    step = {"type": "wake_lan", "mac": MAC, "broadcast": "10.0.0.255"}
    run = executor.start(rule(actions=[step]), MADRID, cause="manual")
    await executor.wait(run.id)
    [result] = run.steps
    if dry_run:
        assert (result.status, sent) == ("dry_run", [])
        assert result.detail == f"dry run: wake_lan {MAC} not sent"
    else:
        assert (result.status, result.detail) == ("ok", MAC)
        assert sent == [(MAC, "10.0.0.255", 9)]
    await executor.shutdown()


# ── Periods awake and statistics ──────────────────────────────────────────────


def test_statistics_from_periods() -> None:
    periods = [
        Period(at(0), at(8), "shutdown"),  # PowerClock shut it down: 10 h off
        Period(at(18), at(20)),  # then someone switched it off: 4 h off
        Period(at(24), at(30), "suspend"),  # suspended by PowerClock: 2 h asleep
        Period(at(32), at(33), "reboot"),  # a restart saves nothing
        Period(at(33.05), at(40)),  # on until now
    ]
    found = stats(periods, at(-24), at(40))
    assert found.since == at(0)  # nothing is known before the first period
    assert found.on == timedelta(hours=8 + 2 + 6 + 1 + 6.95)
    assert found.off == timedelta(hours=10 + 4 + 2 + 0.05)
    assert found.off_by_powerclock == timedelta(hours=12)
    assert found.actions == {"shutdown": 1, "suspend": 1}
    assert found.saved_kwh(61) == pytest.approx(0.72)  # (61 - 1 W on standby) * 12 h
    recent = stats(periods, at(28), at(40))  # only the last 12 hours
    assert recent.off_by_powerclock == timedelta(hours=2)
    assert recent.actions == {"suspend": 1}
    assert stats([], at(0), at(1)).on == timedelta(0)


def test_typical_consumption() -> None:
    assert default_watts(True) == 15.0  # a laptop
    assert default_watts(False) == 60.0
    assert default_watts(None) == 37.5


def test_history_marks_the_periods_awake(tmp_path: Path) -> None:
    history = History(tmp_path / "history.sqlite")
    minute = timedelta(minutes=1)
    for step in range(5):
        history.mark_awake(START + step * minute, AWAKE_GAP)
    history.mark_ended(START + 5 * minute, "suspend")
    history.mark_awake(START + 6 * minute, AWAKE_GAP)  # still going to sleep: ignored
    history.mark_awake(START + 2 * 60 * minute, AWAKE_GAP)  # resumed two hours later
    history.mark_awake(START + 2 * 60 * minute + 5 * AWAKE_GAP, AWAKE_GAP)  # asleep again
    assert history.awake(START - minute) == [
        Period(START, START + 5 * minute, "suspend"),
        Period(START + 120 * minute, START + 120 * minute),
        Period(START + 120 * minute + 5 * AWAKE_GAP, START + 120 * minute + 5 * AWAKE_GAP),
    ]
    later = START + 120 * minute + minute
    assert [p.since for p in history.awake(later)] == [
        START + 120 * minute,  # the one before (its gap counts)
        START + 120 * minute + 5 * AWAKE_GAP,
    ]
    history.close()


async def test_stats_api_after_powerclock_suspends(
    tmp_path: Path, clock: FakeClock, fake: FakePlatform, readings: FakeReadings
) -> None:
    fake.tz = MADRID
    readings.power_state = PowerState(percent=80.0, on_ac=True)  # a laptop
    daemon = Daemon(
        fake,
        paths=Paths(tmp_path / "c", tmp_path / "d"),
        clock=clock,
        readings=readings,
        dry_run=False,  # the fake backend only records the suspend
    )
    await daemon.start()
    try:
        await clock.advance(3600)
        daemon._heartbeat()
        suspend = {"type": "power", "action": "suspend"}
        daemon.engine.upsert(rule(actions=[suspend]))
        run = daemon.engine.run_now("test")
        await daemon.engine.executor.wait(run.id)
        await clock.advance(8 * 3600)  # asleep all night
        daemon._heartbeat()
        async with _http(daemon) as http:
            found = (await http.get("/stats", params={"days": 7})).json()
            assert found["actions"] == {"suspend": 1}
            assert found["saved_hours"] == 8.0
            assert (found["watts"], found["watts_estimated"]) == (15.0, True)
            assert found["kwh"] == pytest.approx(0.11)  # 14 W * 8 h
            await http.patch("/settings", json={"watts": 101, "price_kwh": 0.2})
            found = (await http.get("/stats", params={"days": 7})).json()
            assert (found["kwh"], found["money"], found["price_estimated"]) == (0.8, 0.16, False)
            assert (await http.patch("/settings", json={"port": 1})).status_code == 422
            assert (await http.get("/settings")).json() == {
                "currency": "€",
                "price_kwh": 0.2,
                "tariff": None,
                "watts": 101.0,
            }
    finally:
        await daemon.stop()


def _http(daemon: Daemon) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=daemon.app),
        base_url="http://powerclock",
        headers={"Authorization": f"Bearer {daemon.token}"},
    )


def test_savings_in_words() -> None:
    found: dict[str, Any] = {
        "days": 30,
        "on_hours": 120.5,
        "off_hours": 600.0,
        "saved_hours": 410.0,
        "actions": {"shutdown": 12, "suspend": 30},
        "watts": 60.0,
        "watts_estimated": True,
        "price_kwh": 0.15,
        "price_estimated": True,
        "currency": "€",
        "kwh": 24.19,
        "money": 3.63,
    }
    assert savings_text(found).splitlines() == [
        "Last 30 days: on 120.5 h, off or asleep 600 h.",
        "Thanks to PowerClock: 410 h off (Shut down: 12, Suspend: 30).",
        "Saved about 24.19 kWh, 3.63 € (with typical values: 60 W, 0.15 €/kWh).",
    ]
    assert "has not shut down" in savings_text({**found, "saved_hours": 0, "actions": {}})


def test_events_power_action_type() -> None:
    event = Event(type="power_action", at=datetime(2026, 1, 1, tzinfo=UTC), data={"action": "x"})
    assert event.type == "power_action"
