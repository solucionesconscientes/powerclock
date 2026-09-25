from collections.abc import AsyncIterator

import pytest

from powerclock.engine import Engine, wol
from powerclock.engine.clock import FakeClock
from powerclock.engine.evaluator import Evaluator
from powerclock.engine.executor import Executor
from powerclock.engine.processes import FakeProcesses
from powerclock.engine.runs import Event
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings, FakeSensors
from support import MADRID, START


@pytest.fixture(autouse=True)
def _no_real_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never reach the real D-Bus or run real helper programs
    (kscreen-doctor, xdg-open…): every Linux test injects fakes."""

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a unit test tried to use the real system")

    def forbidden_sync(*args: object, **kwargs: object) -> None:
        raise AssertionError("a unit test tried to run a real system command")

    monkeypatch.setattr(wol, "_udp", forbidden)  # a real Wake-on-LAN packet on the network
    try:
        from powerclock.platform.linux import service
        from powerclock.platform.linux.commands import SystemCommands
        from powerclock.platform.linux.dbus import DBusFastBus
    except ImportError:  # not on Linux
        return
    for name in ("call", "subscribe"):
        monkeypatch.setattr(DBusFastBus, name, forbidden)
    for name in ("run", "spawn"):
        monkeypatch.setattr(SystemCommands, name, forbidden)
    monkeypatch.setattr(service, "run", forbidden_sync)  # systemctl, loginctl
    from powerclock.platform.linux import helper

    monkeypatch.setattr(helper, "run_interactive", forbidden_sync)  # sudo


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def fake() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def sensors() -> FakeSensors:
    return FakeSensors()


@pytest.fixture
def readings() -> FakeReadings:
    return FakeReadings()


@pytest.fixture
def processes() -> FakeProcesses:
    return FakeProcesses()


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
def evaluator(sensors: FakeSensors, clock: FakeClock) -> Evaluator:
    return Evaluator(sensors, clock)


@pytest.fixture
async def executor(
    fake: FakePlatform,
    evaluator: Evaluator,
    clock: FakeClock,
    processes: FakeProcesses,
    events: list[Event],
) -> AsyncIterator[Executor]:
    executor = Executor(fake, evaluator, clock, emit=events.append, processes=processes)
    yield executor
    await executor.shutdown()


@pytest.fixture
async def engine(
    fake: FakePlatform,
    clock: FakeClock,
    readings: FakeReadings,
    processes: FakeProcesses,
    events: list[Event],
) -> AsyncIterator[Engine]:
    engine = Engine(
        fake, tz=MADRID, clock=clock, readings=readings, processes=processes, emit=events.append
    )
    await engine.start()
    yield engine
    await engine.stop()
