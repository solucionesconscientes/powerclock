from collections.abc import AsyncIterator

import pytest

from kse.engine import Engine
from kse.engine.clock import FakeClock
from kse.engine.evaluator import Evaluator
from kse.engine.executor import Executor
from kse.engine.processes import FakeProcesses
from kse.engine.runs import Event
from kse.platform.fake import FakePlatform
from kse.sensors.fake import FakeSensors
from support import MADRID, START


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
    sensors: FakeSensors,
    processes: FakeProcesses,
    events: list[Event],
) -> AsyncIterator[Engine]:
    engine = Engine(
        fake, tz=MADRID, clock=clock, sensors=sensors, processes=processes, emit=events.append
    )
    await engine.start()
    yield engine
    await engine.stop()
