from pathlib import Path

import pytest

from fakebus import FakeBus, FakeCommands, kde_laptop
from kse.platform.base import NotSupported, PowerAction
from kse.platform.linux.dbus import PROPERTIES
from kse.platform.linux.desktop import Desktop


def desktop(session: FakeBus, commands: FakeCommands, tmp_path: Path, **env: str) -> Desktop:
    return Desktop(session, commands, {"XDG_RUNTIME_DIR": str(tmp_path), **env})


@pytest.fixture
def session() -> FakeBus:
    return kde_laptop()[1]


@pytest.mark.parametrize(
    ("action", "method"),
    [
        (PowerAction.SHUTDOWN, "logoutAndShutdown"),
        (PowerAction.REBOOT, "logoutAndReboot"),
        (PowerAction.LOGOUT, "logout"),
    ],
)
async def test_kde_graceful(
    session: FakeBus, tmp_path: Path, action: PowerAction, method: str
) -> None:
    assert await desktop(session, FakeCommands(), tmp_path).graceful(action)
    assert session.called(method) == [[]]


async def test_kde_services_that_are_not_running_yet(session: FakeBus, tmp_path: Path) -> None:
    """org.kde.Shutdown is D-Bus activated: it only runs once someone calls it."""
    session.only_activatable("org.kde.Shutdown")
    commands = FakeCommands(available=["kscreen-doctor"])
    kde = desktop(session, commands, tmp_path)
    assert await kde.graceful_method() == "KDE (org.kde.Shutdown)"
    assert await kde.screen_off_method() == "kscreen-doctor --dpms off"
    assert await kde.graceful(PowerAction.SHUTDOWN)
    assert session.called("logoutAndShutdown") == [[]]


async def test_gnome_graceful(tmp_path: Path) -> None:
    session = FakeBus()
    session.owners.add("org.gnome.SessionManager")
    commands = FakeCommands(available=["gnome-session-quit"])
    assert await desktop(session, commands, tmp_path).graceful(PowerAction.SHUTDOWN)
    assert commands.ran[0][0] == ["gnome-session-quit", "--power-off", "--no-prompt"]


async def test_no_session_manager(tmp_path: Path) -> None:
    assert not await desktop(FakeBus(), FakeCommands(), tmp_path).graceful(PowerAction.SHUTDOWN)
    unreachable = FakeBus()
    unreachable.reachable = False
    assert await desktop(unreachable, FakeCommands(), tmp_path).graceful_method() is None


async def test_screen_off_on_kde_passes_the_wayland_socket(
    session: FakeBus, tmp_path: Path
) -> None:
    (tmp_path / "wayland-0").touch()
    commands = FakeCommands(available=["kscreen-doctor"])
    await desktop(session, commands, tmp_path).screen_off()
    argv, env = commands.ran[0]
    assert argv == ["kscreen-doctor", "--dpms", "off"]
    assert env["WAYLAND_DISPLAY"] == str(tmp_path / "wayland-0")


async def test_screen_off_on_gnome(tmp_path: Path) -> None:
    session = FakeBus()
    session.on(
        "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", PROPERTIES, "Set"
    )
    await desktop(session, FakeCommands(), tmp_path).screen_off()
    [[interface, name, value]] = session.called("Set")
    assert (interface, name, value.value) == ("org.gnome.Mutter.DisplayConfig", "PowerSaveMode", 1)


async def test_screen_off_on_x11(tmp_path: Path) -> None:
    commands = FakeCommands(available=["xset"])
    await desktop(FakeBus(), commands, tmp_path, XDG_SESSION_TYPE="x11", DISPLAY=":0").screen_off()
    assert commands.ran[0][0] == ["xset", "dpms", "force", "off"]


async def test_screen_off_unavailable_or_failing(session: FakeBus, tmp_path: Path) -> None:
    with pytest.raises(NotSupported, match="screen"):
        await desktop(FakeBus(), FakeCommands(), tmp_path).screen_off()
    failing = FakeCommands(available=["kscreen-doctor"], results={"kscreen-doctor": (1, "boom")})
    with pytest.raises(OSError, match="boom"):
        await desktop(session, failing, tmp_path).screen_off()


async def test_media_players(session: FakeBus, tmp_path: Path) -> None:
    session.prop(
        "org.mpris.MediaPlayer2.brave.instance1",
        "/org/mpris/MediaPlayer2",
        "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
        "Paused",
    )
    session.owners.add("org.mpris.MediaPlayer2.broken")  # no properties: ignored
    d = desktop(session, FakeCommands(), tmp_path)
    assert await d.players() == {"brave.instance1": "Paused", "smplayer": "Playing"}
    assert await d.media_playing() is True
    unreachable = FakeBus()
    unreachable.reachable = False
    assert await desktop(unreachable, FakeCommands(), tmp_path).media_playing() is None


async def test_open(tmp_path: Path) -> None:
    commands = FakeCommands(available=["xdg-open"])
    await desktop(FakeBus(), commands, tmp_path).open("https://example.org")
    assert commands.ran[0][0] == ["xdg-open", "https://example.org"]
    with pytest.raises(OSError, match="exit code 4"):
        await desktop(FakeBus(), FakeCommands(["xdg-open"], spawn_result=4), tmp_path).open("x")
    with pytest.raises(NotSupported, match="xdg-open is not installed") as info:
        await desktop(FakeBus(), FakeCommands(), tmp_path).open("x")
    assert info.value.fix_hint == "install xdg-utils"
