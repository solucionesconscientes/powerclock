"""Sensors for tests: FakeSensors answers predicates directly, FakeReadings feeds the hub."""

from collections import Counter

from powerclock.sensors.base import NetRate, PowerState, ProcessInfo, SensorPredicate


class FakeSensors:
    def __init__(self, values: dict[str, bool | None] | None = None) -> None:
        self.values = dict(values or {})  # missing keys are unknown (None)
        self.checked: list[SensorPredicate] = []

    async def check(self, predicate: SensorPredicate) -> bool | None:
        self.checked.append(predicate)
        return self.values.get(predicate.type)


class FakeReadings:
    """Simulated machine state; tests change these attributes freely. `reads` counts the
    readings of each sensor, to check that only the sensors in use are sampled."""

    def __init__(self) -> None:
        self.idle_seconds: float | None = 0.0
        self.cpu_percent: float | None = 50.0
        self.rates: dict[str, NetRate] | None = {"total": NetRate(down_kbps=0.0, up_kbps=0.0)}
        self.running: list[ProcessInfo] | None = []
        self.power_state: PowerState | None = PowerState(percent=80.0, on_ac=True)
        self.ssh: int | None = 0
        self.media: bool | None = False
        self.ssid: str | None = ""
        self.desktop_up: bool | None = True
        self.connected: list[str] | None = []
        self.temps: dict[str, float] | None = {"coretemp": 45.0}
        self.reads: Counter[str] = Counter()

    def start(self, name: str, pid: int, started: float = 1.0) -> None:
        assert self.running is not None
        self.running.append(ProcessInfo(pid=pid, name=name, started=started))

    def stop(self, pid: int) -> None:
        assert self.running is not None
        self.running = [process for process in self.running if process.pid != pid]

    def set_net(self, down_kbps: float, up_kbps: float = 0.0) -> None:
        self.rates = {"total": NetRate(down_kbps=down_kbps, up_kbps=up_kbps)}

    async def idle(self) -> float | None:
        self.reads["idle"] += 1
        return self.idle_seconds

    async def cpu(self) -> float | None:
        self.reads["cpu"] += 1
        return self.cpu_percent

    async def net(self) -> dict[str, NetRate] | None:
        self.reads["net"] += 1
        return self.rates

    async def processes(self) -> list[ProcessInfo] | None:
        self.reads["processes"] += 1
        return None if self.running is None else list(self.running)

    async def power(self) -> PowerState | None:
        self.reads["power"] += 1
        return self.power_state

    async def ssh_sessions(self) -> int | None:
        self.reads["ssh"] += 1
        return self.ssh

    async def media_playing(self) -> bool | None:
        self.reads["media"] += 1
        return self.media

    async def wifi(self) -> str | None:
        self.reads["wifi"] += 1
        return self.ssid

    async def desktop(self) -> bool | None:
        self.reads["desktop"] += 1
        return self.desktop_up

    async def devices(self) -> list[str] | None:
        self.reads["devices"] += 1
        return None if self.connected is None else list(self.connected)

    async def temperatures(self) -> dict[str, float] | None:
        self.reads["temperature"] += 1
        return None if self.temps is None else dict(self.temps)
