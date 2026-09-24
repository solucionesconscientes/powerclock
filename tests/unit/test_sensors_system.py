from collections import namedtuple
from typing import Any

import psutil
import pytest

from kse.platform.fake import FakePlatform
from kse.sensors import system
from kse.sensors.base import PowerState, ProcessInfo
from kse.sensors.system import NetMeter, NetRate, SystemReadings

BatteryInfo = namedtuple("BatteryInfo", "percent secsleft power_plugged")
User = namedtuple("User", "name terminal host started pid")
Io = namedtuple("Io", "bytes_sent bytes_recv")


def test_battery_and_ac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "sensors_battery", lambda: BatteryInfo(71.0, 3600, False))
    assert system.battery() == system.Battery(percent=71.0, plugged=False)
    assert system.power_state() == PowerState(percent=71.0, on_ac=False)
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)  # desktop or server
    assert system.battery() is None
    assert system.power_state() == PowerState(percent=None, on_ac=True)


def test_ssh_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    users = [
        User("pc", "tty2", "", 0.0, 1),  # local console
        User("pc", "pts/1", ":0", 0.0, 2),  # X display
        User("pc", "pts/2", "tmux(1234).%0", 0.0, 3),
        User("pc", "pts/3", "192.168.1.20", 0.0, 4),  # ssh
        User("admin", "pts/4", "vpn.example.org", 0.0, 5),  # ssh
    ]
    monkeypatch.setattr(psutil, "users", lambda: users)
    assert system.ssh_sessions() == 2


def test_process_table(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self, pid: int, name: str | None, started: float | None) -> None:
            self.pid = pid
            self.info = {"name": name, "create_time": started}

    procs = [Proc(10, "ffmpeg", 5.0), Proc(11, None, 6.0), Proc(12, "bash", None)]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: procs)
    assert system.process_table() == [
        ProcessInfo(pid=10, name="ffmpeg", started=5.0),
        ProcessInfo(pid=12, name="bash", started=0.0),
    ]


async def test_system_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "sensors_battery", lambda: BatteryInfo(40.0, 3600, True))
    monkeypatch.setattr(psutil, "users", lambda: [User("pc", "pts/3", "10.0.0.2", 0.0, 4)])
    readings = SystemReadings(FakePlatform(idle=12.0, media=True, ssid=None))
    assert await readings.idle() == 12.0
    assert await readings.media_playing() is True
    assert await readings.wifi() == ""  # not on Wi-Fi
    assert await readings.power() == PowerState(percent=40.0, on_ac=True)
    assert await readings.ssh_sessions() == 1
    assert 0 <= (await readings.cpu() or 0) <= 100
    assert await readings.net() is None  # the first sample only primes the meter


async def test_system_readings_without_backend_support() -> None:
    class Bare(FakePlatform):
        async def idle_seconds(self) -> float | None:
            self._unsupported("idle_seconds")

    readings = SystemReadings(Bare())
    assert await readings.idle() is None


def test_net_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    counters: dict[str, Any] = {
        "lo": Io(0, 0),
        "wlp2s0": Io(bytes_sent=0, bytes_recv=0),
        "docker0": Io(0, 0),
    }
    monkeypatch.setattr(psutil, "net_io_counters", lambda pernic: dict(counters))
    meter = NetMeter(clock=lambda: now[0])
    assert meter.sample() is None  # first sample only primes
    now[0] += 10
    counters.update(
        lo=Io(10**9, 10**9),  # ignored in the total
        wlp2s0=Io(bytes_sent=12_500, bytes_recv=125_000),  # 10 / 100 kbit/s over 10 s
        docker0=Io(10**6, 10**6),  # ignored in the total
    )
    rates = meter.sample()
    assert rates is not None
    assert rates["wlp2s0"] == NetRate(down_kbps=100.0, up_kbps=10.0)
    assert rates["total"] == NetRate(down_kbps=100.0, up_kbps=10.0)
    assert rates["lo"].down_kbps == 800_000


def test_cpu_percent_is_a_number() -> None:
    assert 0 <= system.cpu_percent() <= 100
