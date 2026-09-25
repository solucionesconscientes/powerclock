"""Media players, volume, sounds, speech and desktop settings on Linux (simulated D-Bus and
programs: nothing is played, changed or captured)."""

from pathlib import Path
from typing import Any

import pytest

from fakebus import FakeBus, FakeCommands, kde_laptop
from powerclock.platform.base import NotSupported
from powerclock.platform.linux import LinuxPlatform
from powerclock.platform.linux.settings import (
    KDE_BRIGHTNESS,
    KDE_BRIGHTNESS_IFACE,
    KDE_BRIGHTNESS_PATH,
    PROFILES,
)

PLAYER = "org.mpris.MediaPlayer2.Player"


def platform(
    tmp_path: Path, commands: FakeCommands, **buses: Any
) -> tuple[LinuxPlatform, FakeBus, FakeBus]:
    system, session = kde_laptop()  # smplayer is playing
    linux = LinuxPlatform(
        system_bus=buses.get("system", system),
        session_bus=buses.get("session", session),
        commands=commands,
        root=tmp_path,
        env={"XDG_RUNTIME_DIR": str(tmp_path), "HOME": str(tmp_path)},
        uid=1000,
    )
    return linux, system, session


async def test_media_goes_to_the_player_playing(tmp_path: Path) -> None:
    linux, _, session = platform(tmp_path, FakeCommands())
    vlc = "org.mpris.MediaPlayer2.vlc"
    session.prop(vlc, "/org/mpris/MediaPlayer2", PLAYER, "PlaybackStatus", "Stopped")
    for member in ("Pause", "OpenUri"):
        session.on(vlc, "/org/mpris/MediaPlayer2", PLAYER, member)
        session.on("org.mpris.MediaPlayer2.smplayer", "/org/mpris/MediaPlayer2", PLAYER, member)
    assert await linux.control_media("pause", None, None) == "smplayer"  # the one playing
    assert await linux.control_media("open", "VLC", "https://radio.es") == "vlc"
    assert session.called("OpenUri") == [["https://radio.es"]]
    with pytest.raises(NotSupported, match="no media player 'spotify'"):
        await linux.control_media("play", "spotify", None)


async def test_volume_with_wpctl(tmp_path: Path) -> None:
    commands = FakeCommands(available=["wpctl"], results={"wpctl": (0, "Volume: 0.67 [MUTED]")})
    linux, _, _ = platform(tmp_path, commands)
    assert await linux.volume() == (0.67, True)
    await linux.set_volume(level=0.3, mute=False)
    assert [argv for argv, _ in commands.ran][1:] == [
        ["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "0.30"],
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
    ]


async def test_volume_needs_a_tool(tmp_path: Path) -> None:
    linux, _, _ = platform(tmp_path, FakeCommands())
    with pytest.raises(NotSupported, match="neither wpctl"):
        await linux.set_volume(level=0.5)


async def test_sounds_by_name_and_speech(tmp_path: Path) -> None:
    theme = tmp_path / "usr/share/sounds/freedesktop/stereo"
    theme.mkdir(parents=True)
    (theme / "alarm-clock-elapsed.oga").write_bytes(b"ogg")
    commands = FakeCommands(available=["pw-play", "spd-say"])
    linux, _, _ = platform(tmp_path, commands)
    await linux.play_sound("alarm-clock-elapsed")
    await linux.say("Hora de la pastilla", "es")
    assert [argv for argv, _ in commands.ran] == [
        ["pw-play", str(theme / "alarm-clock-elapsed.oga")],
        ["spd-say", "--wait", "--language", "es", "--", "Hora de la pastilla"],
    ]
    with pytest.raises(OSError, match="there is no sound"):
        await linux.play_sound("no-such-sound")


async def test_theme_wallpaper_and_network_use_the_desktop_tools(tmp_path: Path) -> None:
    picture = tmp_path / "noche.jpg"
    picture.write_bytes(b"jpg")
    commands = FakeCommands(
        available=["plasma-apply-colorscheme", "plasma-apply-wallpaperimage", "nmcli"]
    )
    linux, _, _ = platform(tmp_path, commands)
    assert await linux.set_theme("dark") == "BreezeDark"
    await linux.set_wallpaper(str(picture))
    await linux.network(connect="VPN Oficina", wifi=False)
    assert [argv for argv, _ in commands.ran] == [
        ["plasma-apply-colorscheme", "BreezeDark"],
        ["plasma-apply-wallpaperimage", str(picture)],
        ["nmcli", "radio", "wifi", "off"],
        ["nmcli", "connection", "up", "id", "VPN Oficina"],
    ]


async def test_brightness_and_power_profile_over_dbus(tmp_path: Path) -> None:
    linux, system, session = platform(tmp_path, FakeCommands())
    session.on(KDE_BRIGHTNESS, KDE_BRIGHTNESS_PATH, KDE_BRIGHTNESS_IFACE, "brightnessMax", [937])
    session.on(KDE_BRIGHTNESS, KDE_BRIGHTNESS_PATH, KDE_BRIGHTNESS_IFACE, "setBrightness")
    system.on(
        PROFILES, "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.DBus.Properties", "Set"
    )
    await linux.set_brightness(40)
    await linux.set_power_profile("power-saver")
    assert session.called("setBrightness") == [[375]]
    [[interface, name, value]] = system.called("Set")
    assert (interface, name, value.value) == (PROFILES, "ActiveProfile", "power-saver")


async def test_inhibitors_are_held_and_given_back(tmp_path: Path) -> None:
    linux, _system, session = platform(tmp_path, FakeCommands())
    session.on(
        "org.freedesktop.ScreenSaver",
        "/org/freedesktop/ScreenSaver",
        "org.freedesktop.ScreenSaver",
        "Inhibit",
        [11],
    )
    session.on(
        "org.freedesktop.ScreenSaver",
        "/org/freedesktop/ScreenSaver",
        "org.freedesktop.ScreenSaver",
        "UnInhibit",
    )
    session.on(
        "org.freedesktop.Notifications",
        "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications",
        "Inhibit",
        [22],
    )
    session.on(
        "org.freedesktop.Notifications",
        "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications",
        "UnInhibit",
    )
    release = await linux.inhibit(screen=True, notifications=True, sleep=False, reason="Radio")
    assert session.called("Inhibit") == [["PowerClock", "Radio"], ["powerclock", "Radio", {}]]
    await release()
    assert session.called("UnInhibit") == [[22], [11]]


async def test_screenshot_with_spectacle(tmp_path: Path) -> None:
    target = tmp_path / "shots" / "a.png"

    class Spectacle(FakeCommands):
        async def run(
            self, argv: Any, env: Any = None, limit: float | None = None
        ) -> tuple[int, str]:
            target.write_bytes(b"png")  # what spectacle would do
            return await super().run(argv, env, limit)

    commands = Spectacle(available=["spectacle"])
    linux, _, _ = platform(tmp_path, commands)
    await linux.screenshot(str(target))
    assert commands.ran[0][0] == [
        "spectacle", "--background", "--nonotify", "--fullscreen", "--output", str(target)
    ]  # fmt: skip
