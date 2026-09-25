"""Installed applications: desktop entries, the command that opens them, and opening them as
transient units of systemd's user manager (simulated bus: nothing is started)."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from fakebus import FakeBus, FakeCommands, kde_laptop
from powerclock.platform.base import LaunchRequest, NotSupported, WindowPlacement
from powerclock.platform.linux import LinuxPlatform, apps, kwin, session
from powerclock.platform.linux.dbus import DBusError

SYSTEMD = "org.freedesktop.systemd1"
SYSTEMD_PATH = "/org/freedesktop/systemd1"
MANAGER = "org.freedesktop.systemd1.Manager"
UNIT_PATH = "/org/freedesktop/systemd1/unit/app"
HOME = "/home/pc"


def entry(**values: str) -> apps.DesktopEntry:
    fields: dict[str, Any] = {"id": "x", "path": Path("/x.desktop"), "name": "X", "exec": "x"}
    fields.update(values)
    return apps.DesktopEntry(**fields)


def write(root: Path, folder: str, name: str, text: str) -> Path:
    path = root / folder.lstrip("/") / "applications" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def desktop(name: str, command: str, **extra: str) -> str:
    lines = ["[Desktop Entry]", "Type=Application", f"Name={name}", f"Exec={command}"]
    lines += [f"{key}={value}" for key, value in extra.items()]
    return "\n".join(lines) + "\n"


# ── Desktop entries ───────────────────────────────────────────────────────────


def test_parse_reads_the_desktop_entry_group_only() -> None:
    values = apps.parse(
        "[Desktop Entry]\nName=Okular\nName[es]=Okular (visor)\nComment=A\\sviewer\n"
        "[Desktop Action New]\nName=Not this one\n"
    )
    assert values == {"Name": "Okular", "Name[es]": "Okular (visor)", "Comment": "A viewer"}


@pytest.mark.parametrize(
    ("value", "args"),
    [
        ("okular %U", ["okular", "%U"]),
        ('"/opt/My App/run" --flag %f', ["/opt/My App/run", "--flag", "%f"]),
        ('sh -c "echo \\"hi\\" \\$HOME"', ["sh", "-c", 'echo "hi" $HOME']),
        ("  spaced   out  ", ["spaced", "out"]),
    ],
)
def test_split_exec(value: str, args: list[str]) -> None:
    assert apps.split_exec(value) == args


def test_split_exec_refuses_an_open_quote() -> None:
    with pytest.raises(ValueError, match="unbalanced"):
        apps.split_exec('app "open')


def test_command_puts_the_arguments_in_place_of_the_field_code() -> None:
    okular = entry(exec="okular %U", name="Okular")
    assert apps.command(okular, ["--presentation", "a.pdf"]) == [
        "okular",
        "--presentation",
        "a.pdf",
    ]
    assert apps.command(okular) == ["okular"]
    assert apps.command(entry(exec="kate"), ["-l", "3"]) == ["kate", "-l", "3"]  # at the end


def test_command_keeps_options_out_of_the_files_part() -> None:
    floorp = entry(
        exec="/usr/bin/flatpak run --branch=stable --command=floorp --file-forwarding "
        "one.ablaze.floorp @@u %u @@"
    )
    assert apps.command(floorp, ["--kiosk", "https://x.org"])[-5:] == [
        "one.ablaze.floorp",
        "--kiosk",
        "@@u",
        "https://x.org",
        "@@",
    ]
    mpv = entry(exec="mpv --player-operation-mode=pseudo-gui -- %U")
    assert apps.command(mpv, ["--fs", "list.m3u"]) == [
        "mpv",
        "--player-operation-mode=pseudo-gui",
        "--fs",
        "--",
        "list.m3u",
    ]


def test_command_field_codes() -> None:
    app = entry(exec="app %i --name=%c %k %% %d", name="My App", icon="myapp")
    assert apps.command(app) == ["app", "--icon", "myapp", "--name=My App", "/x.desktop", "%"]


def test_entries_follow_the_menu_rules(tmp_path: Path) -> None:
    write(tmp_path, "usr/share", "org.kde.okular.desktop", desktop("Okular", "okular %U"))
    write(tmp_path, "usr/share", "hidden.desktop", desktop("Hidden", "h", Hidden="true"))
    write(tmp_path, "usr/share", "tool.desktop", desktop("Tool", "t", NoDisplay="true"))
    write(tmp_path, "usr/share", "missing.desktop", desktop("Gone", "g", TryExec="/no/such/prog"))
    write(tmp_path, "usr/share", "link.desktop", "[Desktop Entry]\nType=Link\nName=L\nURL=x\n")
    write(tmp_path, "usr/share", "kde/konsole.desktop", desktop("Konsole", "konsole"))
    # the user's own entry wins over the system's
    mine = desktop("My Okular", "okular")
    write(tmp_path, f"{HOME}/.local/share", "org.kde.okular.desktop", mine)
    write(
        tmp_path,
        "var/lib/flatpak/exports/share",
        "one.ablaze.floorp.desktop",
        desktop("Floorp", "flatpak run one.ablaze.floorp", **{"X-Flatpak": "one.ablaze.floorp"}),
    )
    found = apps.entries({"HOME": HOME, "XDG_DATA_DIRS": "/usr/share"}, tmp_path)
    assert set(found) == {"org.kde.okular", "tool", "kde-konsole", "one.ablaze.floorp"}
    assert found["org.kde.okular"].name == "My Okular"
    assert found["tool"].no_display
    assert found["one.ablaze.floorp"].flatpak == "one.ablaze.floorp"


def test_find_accepts_other_spellings() -> None:
    catalog = {"org.kde.okular": entry(id="org.kde.okular")}
    catalog["floorp"] = entry(id="floorp", flatpak="one.ablaze.floorp")
    assert apps.find(catalog, "org.kde.okular.desktop") is catalog["org.kde.okular"]
    assert apps.find(catalog, "ORG.KDE.OKULAR") is catalog["org.kde.okular"]
    assert apps.find(catalog, "one.ablaze.floorp") is catalog["floorp"]
    assert apps.find(catalog, "nope") is None


def test_window_ids() -> None:
    chrome = entry(id="google-chrome", exec="/usr/bin/google-chrome-stable %U", wm_class="Chrome")
    assert chrome.window_ids() == ["google-chrome", "Chrome", "google-chrome-stable"]
    flatpak = entry(id="one.ablaze.floorp", exec="/usr/bin/flatpak run x", flatpak="x")
    assert flatpak.window_ids() == ["one.ablaze.floorp", "x"]


# ── Units and windows ─────────────────────────────────────────────────────────


def test_unit_names() -> None:
    name = session.unit_name("org.kde.okular")
    assert name.startswith("app-powerclock-org.kde.okular-")
    assert name.endswith(".service")
    assert session.unit_pattern("weird app/1") == "app-powerclock-weird_app_1-*.service"


def test_display_ready(tmp_path: Path) -> None:
    assert not session.display_ready({}, tmp_path)
    assert not session.display_ready({"WAYLAND_DISPLAY": "wayland-0"}, tmp_path)
    (tmp_path / "wayland-0").touch()
    assert session.display_ready({"WAYLAND_DISPLAY": "wayland-0"}, tmp_path)


def test_kwin_script() -> None:
    text = kwin.script(
        ["org.kde.okular", "Okular"],
        4242,
        WindowPlacement(screen=2, desktop=3, state="fullscreen", above=True),
    )
    assert 'var ids = ["org.kde.okular", "okular"];' in text
    assert "var pid = 4242;" in text
    assert "workspace.sendClientToScreen(w, workspace.screens[1]);" in text
    assert "w.desktops = [workspace.desktops[2]];" in text
    assert "w.fullScreen = true;" in text
    assert "w.keepAbove = true;" in text
    assert "workspace.windowAdded.connect(place);" in text


# ── Opening an app through the Linux backend ─────────────────────────────────


@pytest.fixture
def plasma(tmp_path: Path) -> tuple[LinuxPlatform, FakeBus]:
    system, bus = kde_laptop()
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "wayland-0").touch()
    bus.prop(SYSTEMD, SYSTEMD_PATH, MANAGER, "Environment", ["WAYLAND_DISPLAY=wayland-0"])
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "StartTransientUnit", ["/job/1"])
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "GetUnit", [UNIT_PATH])
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "StopUnit", ["/job/2"])
    bus.prop(SYSTEMD, UNIT_PATH, "org.freedesktop.systemd1.Unit", "ActiveState", "active")
    bus.prop(SYSTEMD, UNIT_PATH, "org.freedesktop.systemd1.Service", "MainPID", 4242)
    bus.on("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", [1])
    bus.on("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "start")
    bus.on("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", [True])
    write(tmp_path, "usr/share", "org.kde.okular.desktop", desktop("Okular", "/usr/bin/okular %U"))
    write(tmp_path, "usr/share", "htop.desktop", desktop("htop", "htop", Terminal="true"))
    linux = LinuxPlatform(
        system_bus=system,
        session_bus=bus,
        commands=FakeCommands(),
        root=tmp_path,
        env={"HOME": HOME, "XDG_RUNTIME_DIR": str(tmp_path / "run"), "XDG_DATA_DIRS": "/usr/share"},
        uid=1000,
    )
    return linux, bus


async def test_apps_lists_the_menu(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, _ = plasma
    names = [app.name for app in await linux.apps()]
    assert names == ["htop", "Okular"]


async def test_launch_starts_a_transient_unit(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, bus = plasma
    request = LaunchRequest(
        app="org.kde.okular",
        args=("--presentation", "a.pdf"),
        keep_open=True,
        stop_signal="INT",
    )
    detail = await linux.launch(request)
    [[name, mode, properties, aux]] = bus.called("StartTransientUnit")
    assert name.startswith("app-powerclock-org.kde.okular-")
    assert (mode, aux) == ("fail", [])
    values = {key: variant.value for key, variant in properties}
    assert values["ExecStart"] == [
        ["/usr/bin/okular", ["/usr/bin/okular", "--presentation", "a.pdf"], False]
    ]
    assert values["KillSignal"] == 2  # SIGINT
    assert values["Restart"] == "always"
    assert values["StartLimitBurst"] == 3
    assert values["WorkingDirectory"] == HOME
    assert detail == f"Okular --presentation a.pdf ({name})"  # the history shows the args


async def test_a_browser_already_open_takes_the_order(
    plasma: tuple[LinuxPlatform, FakeBus],
) -> None:
    """Chromium browsers pass the order to the copy already open and quit at once; they
    ignore --start-fullscreen there, so the recipe asks KWin for full screen instead."""
    linux, bus = plasma
    gone = DBusError("org.freedesktop.systemd1.NoSuchUnit", "gone")
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "GetUnit", gone)
    window = WindowPlacement(state="fullscreen")
    request = LaunchRequest(
        app="org.kde.okular", args=("--new-window",), window=window, wait_window=timedelta(0)
    )
    detail = await linux.launch(request)
    assert "--new-window" in detail
    assert "passed to the copy already open" in detail
    assert detail.endswith("window placement requested")  # matched by its window class


async def test_launch_places_the_window(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, bus = plasma
    window = WindowPlacement(screen=2, state="fullscreen")
    request = LaunchRequest(app="org.kde.okular", window=window, wait_window=timedelta(0))
    assert (await linux.launch(request)).endswith("window placement requested")
    [[path, name]] = bus.called("loadScript")
    assert name.startswith("powerclock-")
    assert bus.called("start") == [[]]
    await linux.close()  # unloads the script and deletes it
    assert bus.called("unloadScript") == [[name]]
    assert not Path(path).exists()  # noqa: ASYNC240 - a test's check


async def test_launch_explains_what_it_cannot_do(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, _ = plasma
    with pytest.raises(NotSupported, match="not an installed application"):
        await linux.launch(LaunchRequest(app="nope"))
    with pytest.raises(NotSupported, match="runs in a terminal"):
        await linux.launch(LaunchRequest(app="htop"))


async def test_launch_without_systemd_starts_it_directly(tmp_path: Path) -> None:
    system, bus = kde_laptop()  # no systemd on this bus
    write(tmp_path, "usr/share", "org.kde.okular.desktop", desktop("Okular", "/usr/bin/okular"))
    commands = FakeCommands()
    linux = LinuxPlatform(
        system_bus=system,
        session_bus=bus,
        commands=commands,
        root=tmp_path,
        env={"HOME": HOME, "XDG_RUNTIME_DIR": str(tmp_path), "XDG_DATA_DIRS": "/usr/share"},
        uid=1000,
    )
    assert await linux.launch(LaunchRequest(app="org.kde.okular")) == "Okular"
    assert commands.ran[-1][0] == ["/usr/bin/okular"]
    with pytest.raises(NotSupported, match="keeping an app open"):
        await linux.launch(LaunchRequest(app="org.kde.okular", keep_open=True))


async def test_close_app_stops_its_units(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, bus = plasma
    units = [["app-powerclock-org.kde.okular-abc123.service"]]
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "ListUnitsByPatterns", [units])
    bus.prop(SYSTEMD, UNIT_PATH, "org.freedesktop.systemd1.Unit", "ActiveState", "inactive")
    assert await linux.close_app("org.kde.okular", timedelta(seconds=1)) == 1
    assert bus.called("StopUnit") == [["app-powerclock-org.kde.okular-abc123.service", "replace"]]
    [[_states, patterns]] = bus.called("ListUnitsByPatterns")
    assert patterns == ["app-powerclock-org.kde.okular-*.service"]


async def test_desktop_session_and_its_environment(plasma: tuple[LinuxPlatform, FakeBus]) -> None:
    linux, bus = plasma
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "GetUnit", [UNIT_PATH])
    assert await linux.desktop_session() is True  # graphical-session.target is active
    assert await linux.session_env() == {"WAYLAND_DISPLAY": "wayland-0"}
