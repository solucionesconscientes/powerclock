"""SensorHub with fake readings: sampling on demand, averages, sustained states, gaps."""

from typing import Any

import pytest
from pydantic import TypeAdapter

from powerclock.engine.clock import FakeClock
from powerclock.models import Predicate
from powerclock.sensors.base import NetRate, PowerState, ProcessInfo
from powerclock.sensors.fake import FakeReadings
from powerclock.sensors.registry import SensorHub

PREDICATE: TypeAdapter[Predicate] = TypeAdapter(Predicate)


def p(**data: Any) -> Any:
    return PREDICATE.validate_python(data)


@pytest.fixture
def hub(readings: FakeReadings, clock: FakeClock) -> SensorHub:
    return SensorHub(readings, clock)


async def poll(hub: SensorHub, clock: FakeClock, seconds: float, step: float = 5.0) -> None:
    """Run the sampling loop for `seconds` of fake time."""
    elapsed = 0.0
    while elapsed < seconds:
        await hub.sample()
        await clock.advance(step)
        elapsed += step
    await hub.sample()


CPU_5M = {"type": "cpu_below", "percent": 10, "for": "5m"}


async def test_only_what_is_demanded_is_sampled(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    await poll(hub, clock, 60)
    assert readings.reads == {}  # nothing in demand: nothing read
    hub.demand([p(**CPU_5M), p(type="idle", **{"for": "20m"})])
    assert hub.polled == {"cpu", "idle"}
    assert hub.next_due() == 0.0
    await poll(hub, clock, 60)
    assert readings.reads == {"cpu": 13, "idle": 13}
    assert hub.next_due() == 5.0
    hub.demand([])
    await poll(hub, clock, 60)
    assert readings.reads == {"cpu": 13, "idle": 13}
    assert hub.next_due() is None


async def test_other_sensors_are_read_when_asked_and_reused(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    media = p(type="media_playing")
    assert await hub.check(media) is False
    readings.media = True
    assert await hub.check(media) is False  # the reading is still fresh
    await clock.advance(5)
    assert await hub.check(media) is True
    assert readings.reads["media"] == 2


async def test_cpu_below_needs_the_whole_window(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    cpu = p(**CPU_5M)
    hub.demand([cpu])
    readings.cpu_percent = 3.0
    await poll(hub, clock, 295)
    assert await hub.check(cpu) is None  # 4m55s of history: not known yet
    await poll(hub, clock, 5)
    assert await hub.check(cpu) is True
    assert hub.measure(cpu) == (3.0, cpu.for_)


async def test_cpu_below_is_an_average(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    cpu = p(**CPU_5M)
    hub.demand([cpu])
    readings.cpu_percent = 5.0
    await poll(hub, clock, 300)
    readings.cpu_percent = 100.0  # a 5 s spike does not break a 5-minute average
    await clock.advance(5)
    await hub.sample()
    readings.cpu_percent = 5.0
    await poll(hub, clock, 10)
    assert await hub.check(cpu) is True  # (59 * 5 + 100) / 60 = 6.6 %
    readings.cpu_percent = 40.0
    await poll(hub, clock, 60)
    assert await hub.check(cpu) is False  # a real load does


async def test_a_gap_starts_the_history_again(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    cpu = p(**CPU_5M)
    hub.demand([cpu])
    readings.cpu_percent = 3.0
    await poll(hub, clock, 300)
    assert await hub.check(cpu) is True
    clock.jump(3600)  # suspended for an hour
    await hub.sample()
    assert await hub.check(cpu) is None
    await poll(hub, clock, 300)
    assert await hub.check(cpu) is True


async def test_history_is_dropped_when_no_rule_needs_it(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    cpu = p(**CPU_5M)
    hub.demand([cpu])
    await poll(hub, clock, 300)
    hub.demand([])
    hub.demand([cpu])
    await hub.sample()
    assert await hub.check(cpu) is None


async def test_cpu_below_without_samples_is_unknown(hub: SensorHub) -> None:
    assert await hub.check(p(**CPU_5M)) is None


@pytest.mark.parametrize(
    ("net", "down", "up", "expected"),
    [
        ({}, 30.0, 10.0, True),  # both: 40 < 50
        ({}, 30.0, 30.0, False),  # both: 60
        ({"direction": "down"}, 30.0, 30.0, True),
        ({"direction": "up"}, 60.0, 30.0, True),
        ({"direction": "up"}, 10.0, 60.0, False),
    ],
)
async def test_net_below(
    hub: SensorHub,
    readings: FakeReadings,
    clock: FakeClock,
    net: dict[str, Any],
    down: float,
    up: float,
    expected: bool,
) -> None:
    predicate = p(type="net_below", kbps=50, **{"for": "1m"}, **net)
    hub.demand([predicate])
    readings.set_net(down, up)
    await poll(hub, clock, 60)
    assert await hub.check(predicate) is expected


async def test_net_below_on_one_interface(
    hub: SensorHub, readings: FakeReadings, clock: FakeClock
) -> None:
    wifi = p(type="net_below", kbps=50, interface="wlp2s0", **{"for": "1m"})
    missing = p(type="net_below", kbps=50, interface="eth9", **{"for": "1m"})
    hub.demand([wifi, missing])
    readings.rates = {
        "wlp2s0": NetRate(down_kbps=10.0, up_kbps=0.0),
        "total": NetRate(down_kbps=900.0, up_kbps=0.0),
    }
    await poll(hub, clock, 60)
    assert await hub.check(wifi) is True
    assert await hub.check(missing) is None  # no such interface: unknown


async def test_idle_needs_no_history(hub: SensorHub, readings: FakeReadings) -> None:
    idle = p(type="idle", **{"for": "20m"})
    readings.idle_seconds = 1199.0
    assert await hub.check(idle) is False
    readings.idle_seconds = None
    assert await hub.check(idle) is False  # the earlier reading is still fresh


async def test_idle_unknown(hub: SensorHub, readings: FakeReadings) -> None:
    readings.idle_seconds = None
    assert await hub.check(p(type="idle", **{"for": "1m"})) is None


@pytest.mark.parametrize(
    ("threshold", "percent", "expected"),
    [
        ({"below": 15}, 14.0, True),
        ({"below": 15}, 15.0, False),
        ({"above": 90}, 95.0, True),
        ({"above": 90}, 90.0, False),
        ({"below": 15}, None, None),  # no battery at all
    ],
)
async def test_battery_now(
    hub: SensorHub,
    readings: FakeReadings,
    threshold: dict[str, int],
    percent: float | None,
    expected: bool | None,
) -> None:
    readings.power_state = PowerState(percent=percent, on_ac=percent is None)
    assert await hub.check(p(type="battery", **threshold)) is expected


async def test_battery_sustained(hub: SensorHub, readings: FakeReadings, clock: FakeClock) -> None:
    low = p(type="battery", below=15, **{"for": "2m"})
    hub.demand([low])
    readings.power_state = PowerState(percent=14.0, on_ac=False)
    await poll(hub, clock, 60)
    assert await hub.check(low) is None  # below for 1 of 2 minutes
    await poll(hub, clock, 60)
    assert await hub.check(low) is True
    readings.power_state = PowerState(percent=16.0, on_ac=True)
    await poll(hub, clock, 5)
    assert await hub.check(low) is False


async def test_power_source(hub: SensorHub, readings: FakeReadings, clock: FakeClock) -> None:
    unplugged = p(type="power_source", **{"is": "battery", "for": "1m"})
    on_ac = p(type="power_source", **{"is": "ac"})
    hub.demand([unplugged])
    readings.power_state = PowerState(percent=50.0, on_ac=False)
    await poll(hub, clock, 30)
    readings.power_state = PowerState(percent=50.0, on_ac=True)  # plugged in for a moment
    await poll(hub, clock, 5)
    readings.power_state = PowerState(percent=50.0, on_ac=False)
    await poll(hub, clock, 40)
    assert await hub.check(unplugged) is False  # the minute was interrupted
    await poll(hub, clock, 25)
    assert await hub.check(unplugged) is True
    assert await hub.check(on_ac) is False
    assert hub.measure(unplugged) == ("battery", None)
    readings.power_state = PowerState(percent=None, on_ac=True)  # a desktop
    await clock.advance(5)
    assert await hub.check(on_ac) is True
    readings.power_state = PowerState(percent=50.0, on_ac=None)
    await clock.advance(5)
    assert await hub.check(on_ac) is None


async def test_processes_ssh_and_wifi(hub: SensorHub, readings: FakeReadings) -> None:
    readings.running = [ProcessInfo(pid=10, name="ffmpeg", started=1.0)]
    readings.ssh = 1
    readings.ssid = "Casa"
    assert await hub.check(p(type="process_running", name="ffmpeg")) is True
    assert await hub.check(p(type="process_running", name="blender")) is False
    assert await hub.check(p(type="ssh_session")) is True
    assert await hub.check(p(type="wifi_ssid", ssid="Casa")) is True
    assert await hub.check(p(type="wifi_ssid", ssid="Bar")) is False


async def test_unreadable_sensors_are_unknown(hub: SensorHub, readings: FakeReadings) -> None:
    async def broken() -> int:
        raise OSError("no /proc")

    readings.ssh_sessions = broken  # type: ignore[method-assign]
    readings.running = None
    assert await hub.check(p(type="ssh_session")) is None
    assert await hub.check(p(type="process_running", name="ffmpeg")) is None
