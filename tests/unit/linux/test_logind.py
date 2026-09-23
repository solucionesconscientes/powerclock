import os
from datetime import UTC, datetime

import pytest

from fakebus import LOGIND, MANAGER, MANAGER_PATH, SESSION_PATH, FakeBus, kde_laptop
from kse.platform.base import NotSupported, PowerAction, PowerEvent
from kse.platform.linux.logind import Logind


@pytest.fixture
def system() -> FakeBus:
    return kde_laptop()[0]


@pytest.fixture
def logind(system: FakeBus) -> Logind:
    return Logind(system, uid=1000)


async def test_can_and_power(logind: Logind, system: FakeBus) -> None:
    assert await logind.can(PowerAction.SHUTDOWN) == "yes"
    await logind.power(PowerAction.SUSPEND)
    assert system.called("Suspend") == [[True]]  # interactive: polkit may ask


async def test_power_refuses_what_logind_does_not_allow(logind: Logind, system: FakeBus) -> None:
    with pytest.raises(NotSupported, match="'na' to CanHibernate"):
        await logind.power(PowerAction.HIBERNATE)
    assert system.called("Hibernate") == []


async def test_challenge_is_allowed(logind: Logind, system: FakeBus) -> None:
    system.on(LOGIND, MANAGER_PATH, MANAGER, "CanReboot", ["challenge"])
    await logind.power(PowerAction.REBOOT)
    assert system.called("Reboot") == [[True]]


async def test_display_session(logind: Logind, system: FakeBus) -> None:
    assert await logind.display() == ("3", SESSION_PATH)
    await logind.lock()
    await logind.terminate_session()
    assert [(path, member) for _, path, _, member, _ in system.calls if member != "Get"] == [
        (SESSION_PATH, "Lock"),
        (SESSION_PATH, "Terminate"),
    ]


async def test_no_graphical_session(logind: Logind, system: FakeBus) -> None:
    system.prop(
        LOGIND, f"{MANAGER_PATH}/user/_1000", "org.freedesktop.login1.User", "Display", ["", "/"]
    )
    with pytest.raises(NotSupported, match="no graphical session"):
        await logind.lock()


async def test_idle_since(logind: Logind, system: FakeBus) -> None:
    assert await logind.idle_since() is None
    since = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    system.prop(LOGIND, MANAGER_PATH, MANAGER, "IdleHint", True)
    system.prop(LOGIND, MANAGER_PATH, MANAGER, "IdleSinceHint", int(since.timestamp() * 1e6))
    assert await logind.idle_since() == since
    assert await logind.inhibit_delay_max() == 30


async def test_inhibitor_releases_its_file_descriptor(logind: Logind, system: FakeBus) -> None:
    read_end, write_end = os.pipe()
    os.close(read_end)
    system.on(LOGIND, MANAGER_PATH, MANAGER, "Inhibit", [write_end])
    async with logind.inhibitor("shutdown:sleep", "testing"):
        os.fstat(write_end)  # still open
    assert system.called("Inhibit") == [["shutdown:sleep", "kse", "testing", "delay"]]
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(write_end)


async def test_power_events(logind: Logind, system: FakeBus) -> None:
    received: list[PowerEvent] = []

    async def on_event(event: PowerEvent) -> None:
        received.append(event)

    await logind.subscribe(on_event)
    await system.emit(MANAGER, "PrepareForSleep", [True])
    await system.emit(MANAGER, "PrepareForSleep", [False])
    await system.emit(MANAGER, "PrepareForShutdown", [True])
    await system.emit(MANAGER, "PrepareForShutdown", [False])  # shutdown cancelled: nothing
    assert received == [
        PowerEvent.BEFORE_SLEEP,
        PowerEvent.AFTER_RESUME,
        PowerEvent.BEFORE_SHUTDOWN,
    ]
