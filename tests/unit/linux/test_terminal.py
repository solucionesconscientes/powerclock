"""Commands in a terminal window (run steps with terminal: true)."""

import stat
import subprocess
from pathlib import Path

import pytest

from fakebus import FakeBus
from powerclock.platform.linux import LinuxPlatform, terminal
from powerclock.platform.linux.session import MANAGER, SYSTEMD, SYSTEMD_PATH


def installed(folder: Path, *names: str) -> str:
    folder.mkdir(exist_ok=True)
    for name in names:
        program = folder / name
        program.write_text("#!/bin/sh\n")
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return str(folder)


def test_the_desktops_own_terminal_comes_first(tmp_path: Path) -> None:
    path = installed(tmp_path / "bin", "xterm", "konsole", "kgx")
    kde = terminal.pick({"PATH": path, "XDG_CURRENT_DESKTOP": "KDE"})
    assert kde == (f"{path}/konsole", ("-e",))
    gnome = terminal.pick({"PATH": path, "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})
    assert gnome == (f"{path}/kgx", ("--",))
    only_xterm = installed(tmp_path / "other", "xterm")
    assert terminal.pick({"PATH": only_xterm, "XDG_CURRENT_DESKTOP": "KDE"}) == (
        f"{only_xterm}/xterm",
        ("-e",),
    )
    assert terminal.pick({"PATH": str(tmp_path / "none")}) is None


def test_the_command_line() -> None:
    line = terminal.command(
        ("/usr/bin/konsole", ("-e",)),
        ["/home/pc/setup.sh", "--all"],
        shell=False,
        env={"MODE": "fast"},
        result=Path("/tmp/x/exit-code"),
        done="Done:",
    )
    assert line[:6] == ["/usr/bin/konsole", "-e", "/usr/bin/env", "MODE=fast", "/bin/sh", "-c"]
    assert line[7:] == ["powerclock", "/tmp/x/exit-code", "Done:", "/home/pc/setup.sh", "--all"]
    shell = terminal.command(
        ("/usr/bin/xterm", ("-e",)),
        ["echo hi && sudo apt update"],
        shell=True,
        env={},
        result=Path("/tmp/r"),
        done="",
    )
    assert shell[-3:] == ["/bin/sh", "-c", "echo hi && sudo apt update"]
    assert terminal.folder("~/scripts", Path("/home/pc")) == Path("/home/pc/scripts")
    assert terminal.folder(None, Path("/home/pc")) == Path("/home/pc")


@pytest.mark.parametrize(("script", "code"), [("exit 0", 0), ("exit 3", 3)])
def test_the_wrapper_writes_the_exit_code(tmp_path: Path, script: str, code: int) -> None:
    """The real wrapper with sh (no window): the code is written, then it waits for Enter."""
    result = tmp_path / "exit-code"
    argv = ["/bin/sh", "-c", terminal.WRAPPER, "powerclock", str(result), "Done:"]
    done = subprocess.run(
        [*argv, "/bin/sh", "-c", script], input="\n", capture_output=True, text=True, check=False
    )
    assert result.read_text().strip() == str(code)
    assert done.stdout.strip() == f"Done: {code}"
    assert done.returncode == 0  # Enter closes the window


async def test_it_opens_in_the_session(tmp_path: Path) -> None:
    bus = FakeBus()
    bus.prop(SYSTEMD, SYSTEMD_PATH, MANAGER, "Environment", ["WAYLAND_DISPLAY=wayland-0"])
    bus.on(SYSTEMD, SYSTEMD_PATH, MANAGER, "StartTransientUnit", ["/job/1"])
    path = installed(tmp_path / "bin", "konsole")
    linux = LinuxPlatform(
        system_bus=FakeBus(),
        session_bus=bus,
        root=tmp_path,
        env={"HOME": "/home/pc", "PATH": path, "XDG_CURRENT_DESKTOP": "KDE"},
        uid=1000,
    )
    result = tmp_path / "exit-code"
    where = await linux.open_terminal(
        ["./setup.sh"], shell=False, cwd="~/scripts", env={}, result=result
    )
    assert where == "konsole: ./setup.sh"
    [[name, _mode, properties, _aux]] = bus.called("StartTransientUnit")
    assert name.startswith("app-powerclock-terminal-")
    values = {key: variant.value for key, variant in properties}
    [[program, argv, _]] = values["ExecStart"]
    assert program == f"{path}/konsole"
    assert argv[-4:] == ["powerclock", str(result), argv[-2], "./setup.sh"]
    assert values["WorkingDirectory"] == "/home/pc/scripts"
