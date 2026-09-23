import asyncio

import pytest

from fakebus import NM, NOTIFICATIONS, FakeBus, kde_laptop
from kse.engine.clock import settle
from kse.platform.base import NotSupported
from kse.platform.linux.network import wifi_ssid
from kse.platform.linux.notify import Notifier

BUTTONS = {"cancel": "Cancel", "postpone": "Postpone 10 min"}


@pytest.fixture
def session() -> FakeBus:
    return kde_laptop()[1]


async def test_plain_notification(session: FakeBus) -> None:
    assert await Notifier(session).notify("KSE", "hola") is None
    [[app, replaces, icon, title, body, actions, hints, expire]] = session.called("Notify")
    assert (app, replaces, icon) == ("KSE", 0, "")
    assert (title, body, actions, hints, expire) == ("KSE", "hola", [], {}, -1)


async def test_button_answer(session: FakeBus) -> None:
    notifier = Notifier(session)
    answer = asyncio.create_task(notifier.notify("KSE", "Shut down in 60 s", BUTTONS))
    await settle()
    [[*_, actions, hints, expire]] = session.called("Notify")
    assert actions == ["cancel", "Cancel", "postpone", "Postpone 10 min"]
    assert hints["urgency"].value == 2
    assert expire == 0
    await session.emit(NOTIFICATIONS, "ActionInvoked", [99, "cancel"])  # somebody else's
    await session.emit(NOTIFICATIONS, "ActionInvoked", [42, "postpone"])
    assert await answer == "postpone"
    assert session.called("CloseNotification") == []


async def test_closed_without_answer(session: FakeBus) -> None:
    answer = asyncio.create_task(Notifier(session).notify("KSE", "x", BUTTONS))
    await settle()
    await session.emit(NOTIFICATIONS, "NotificationClosed", [42, 2])
    assert await answer is None


async def test_cancelling_removes_the_notification(session: FakeBus) -> None:
    answer = asyncio.create_task(Notifier(session).notify("KSE", "x", BUTTONS))
    await settle()
    answer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answer
    assert session.called("CloseNotification") == [[42]]


async def test_server_information(session: FakeBus) -> None:
    assert await Notifier(session).server() == ("Plasma 6.6.6 (KDE)", ["body", "actions"])


async def test_no_notification_server() -> None:
    with pytest.raises(NotSupported, match="no notification server"):
        await Notifier(FakeBus()).notify("KSE", "x")


async def test_wifi_ssid() -> None:
    system = kde_laptop()[0]
    assert await wifi_ssid(system) == "Casa"
    active = "/org/freedesktop/NetworkManager/ActiveConnection/7"
    system.prop(NM, active, f"{NM}.Connection.Active", "Type", "802-3-ethernet")
    assert await wifi_ssid(system) is None
    system.prop(NM, "/org/freedesktop/NetworkManager", NM, "PrimaryConnection", "/")
    assert await wifi_ssid(system) is None


async def test_wifi_without_network_manager() -> None:
    with pytest.raises(NotSupported, match="NetworkManager"):
        await wifi_ssid(FakeBus())
