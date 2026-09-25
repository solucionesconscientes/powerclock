from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from fakebus import LOGIND, MANAGER, MANAGER_PATH, SESSION_PATH, FakeBus, FakeCommands, kde_laptop
from powerclock.platform.base import NotSupported, PowerAction, PowerMode
from powerclock.platform.linux import LinuxPlatform


def platform(
    tmp_path: Path,
    system: FakeBus,
    session: FakeBus,
    commands: FakeCommands | None = None,
) -> LinuxPlatform:
    return LinuxPlatform(
        system_bus=system,
        session_bus=session,
        commands=commands or FakeCommands(available=["kscreen-doctor", "xdg-open"]),
        root=tmp_path,
        env={"XDG_RUNTIME_DIR": str(tmp_path)},
        uid=1000,
    )


@pytest.fixture
def buses() -> tuple[FakeBus, FakeBus]:
    return kde_laptop()


@pytest.fixture
def linux(tmp_path: Path, buses: tuple[FakeBus, FakeBus]) -> LinuxPlatform:
    return platform(tmp_path, *buses)


def members(bus: FakeBus) -> list[str]:
    return [member for *_, member, _ in bus.calls if not member.startswith("Can")]


async def test_graceful_shutdown_goes_through_kde(
    linux: LinuxPlatform, buses: tuple[FakeBus, FakeBus]
) -> None:
    system, session = buses
    await linux.power(PowerAction.SHUTDOWN, PowerMode.GRACEFUL)
    assert session.called("logoutAndShutdown") == [[]]
    assert system.called("PowerOff") == []


async def test_forced_shutdown_goes_to_logind(
    linux: LinuxPlatform, buses: tuple[FakeBus, FakeBus]
) -> None:
    system, session = buses
    await linux.power(PowerAction.REBOOT, PowerMode.FORCE)
    assert system.called("Reboot") == [[True]]
    assert session.called("logoutAndReboot") == []


async def test_graceful_without_desktop_falls_back_to_logind(tmp_path: Path) -> None:
    system, _ = kde_laptop()
    linux = platform(tmp_path, system, FakeBus())
    await linux.power(PowerAction.SHUTDOWN, PowerMode.GRACEFUL)
    assert system.called("PowerOff") == [[True]]


async def test_shutdown_not_allowed_is_refused_before_asking_the_desktop(
    linux: LinuxPlatform, buses: tuple[FakeBus, FakeBus]
) -> None:
    system, session = buses
    system.on(LOGIND, MANAGER_PATH, MANAGER, "CanPowerOff", ["no"])
    with pytest.raises(NotSupported, match="'no' to CanPowerOff"):
        await linux.power(PowerAction.SHUTDOWN, PowerMode.GRACEFUL)
    assert session.called("logoutAndShutdown") == []
    assert system.called("PowerOff") == []


@pytest.mark.parametrize(
    ("action", "method"),
    [(PowerAction.SUSPEND, "Suspend"), (PowerAction.HYBRID_SLEEP, None)],
)
async def test_sleep_goes_to_logind(
    linux: LinuxPlatform, buses: tuple[FakeBus, FakeBus], action: PowerAction, method: str | None
) -> None:
    system, _ = buses
    if method is None:  # hybrid sleep is "na" on the laptop
        with pytest.raises(NotSupported):
            await linux.power(action, PowerMode.GRACEFUL)
        return
    await linux.power(action, PowerMode.GRACEFUL)
    assert system.called(method) == [[True]]


async def test_lock_logout_and_screen_off(tmp_path: Path, buses: tuple[FakeBus, FakeBus]) -> None:
    system, session = buses
    commands = FakeCommands(available=["kscreen-doctor"])
    linux = platform(tmp_path, system, session, commands)
    await linux.power(PowerAction.LOCK, PowerMode.GRACEFUL)
    await linux.power(PowerAction.LOGOUT, PowerMode.GRACEFUL)
    await linux.power(PowerAction.LOGOUT, PowerMode.FORCE)
    await linux.power(PowerAction.SCREEN_OFF, PowerMode.GRACEFUL)
    assert [(p, m) for _, p, _, m, _ in system.calls if m in ("Lock", "Terminate")] == [
        (SESSION_PATH, "Lock"),
        (SESSION_PATH, "Terminate"),
    ]
    assert session.called("logout") == [[]]
    assert commands.ran[0][0] == ["kscreen-doctor", "--dpms", "off"]


async def test_timezone_and_close(
    linux: LinuxPlatform, tmp_path: Path, buses: tuple[FakeBus, FakeBus]
) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/localtime").symlink_to("/usr/share/zoneinfo/Europe/Madrid")
    assert linux.timezone() == ZoneInfo("Europe/Madrid")
    await linux.close()
    assert all(bus.closed for bus in buses)


async def test_reads(linux: LinuxPlatform) -> None:
    assert await linux.media_playing() is True
    assert await linux.wifi_ssid() == "Casa"
    assert await linux.idle_seconds() == 0  # no Wayland socket in tmp: logind IdleHint


async def test_capabilities_of_the_kde_laptop(linux: LinuxPlatform, tmp_path: Path) -> None:
    (tmp_path / "sys/class/rtc/rtc0").mkdir(parents=True)
    (tmp_path / "sys/class/rtc/rtc0/wakealarm").touch()
    rows = {row.id: row for row in await linux.capabilities()}
    supported = {row_id for row_id, row in rows.items() if row.supported}
    assert set(rows) == {
        "session",
        "power.shutdown",
        "power.reboot",
        "power.suspend",
        "power.hibernate",
        "power.hybrid_sleep",
        "power.graceful",
        "power.lock",
        "power.logout",
        "power.screen_off",
        "idle",
        "media",
        "notify",
        "wifi",
        "apps",
        "launch",
        "windows",
        "volume",
        "sound",
        "speech",
        "theme",
        "brightness",
        "power_profile",
        "network",
        "screenshot",
        "power_events",
        "inhibit",
        "wake.rtc",
        "wake.helper",
        "wake.alarm",
        "autologin",
        "hardware",
        "linger",
        "timezone",
    }
    assert set(rows) - supported == {
        "power.hibernate",
        "power.hybrid_sleep",
        "wake.helper",
        "linger",
        "apps",  # no desktop entries in the test's root
        "windows",  # no KWin on the fake bus
        "autologin",  # no display manager in the test's root
        # none of these programs or services on the simulated laptop:
        "volume",
        "sound",
        "speech",
        "theme",
        "brightness",
        "power_profile",
        "network",
        "screenshot",
    }
    assert rows["session"].detail == "KDE · wayland"
    assert rows["power.lock"].detail == "logind session 3"
    assert rows["power.hibernate"].fix_hint is not None
    assert "with buttons" in rows["notify"].detail
    assert "Casa" in rows["wifi"].detail


async def test_capabilities_of_a_server(tmp_path: Path) -> None:
    """No desktop session, no session bus, no NetworkManager: a report, never a crash."""
    system = FakeBus()
    for query in ("CanPowerOff", "CanReboot", "CanSuspend", "CanHibernate", "CanHybridSleep"):
        system.on(
            LOGIND, MANAGER_PATH, MANAGER, query, ["yes" if query != "CanHibernate" else "no"]
        )
    session = FakeBus()
    session.reachable = False
    rows = {
        row.id: row
        for row in await platform(tmp_path, system, session, FakeCommands()).capabilities()
    }
    assert rows["power.shutdown"].supported
    for row_id in (
        "session",
        "power.graceful",
        "power.lock",
        "media",
        "notify",
        "wifi",
        "wake.rtc",
    ):
        assert not rows[row_id].supported, row_id
    assert not rows["power_events"].supported  # no logind properties in this fake
