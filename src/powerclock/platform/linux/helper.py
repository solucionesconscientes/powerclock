"""`powerclock helper install/uninstall`: the exact sudo commands, always shown before running."""

import re
import shlex
import subprocess
from collections.abc import Callable, Iterable, Sequence
from importlib.resources import files
from pathlib import Path

from powerclock.config import atomic_write

HELPER = Path("/usr/local/libexec/powerclock-helper")
POLICY = Path("/usr/share/polkit-1/actions/org.powerclock.helper.policy")
RULES = Path("/etc/polkit-1/rules.d/50-powerclock-unattended.rules")
BOOT_UNIT = Path("/etc/systemd/system/powerclock-boot.service")
BOOT_WANTS = Path("/etc/systemd/system/graphical.target.wants/powerclock-boot.service")
STATE = Path("/var/lib/powerclock")
RUNTIME = Path("/run/powerclock")
# Display managers whose settings folder can point at this boot's log-in setting in /run.
DM_LINKS = {
    "sddm": (Path("/etc/sddm.conf.d/zz-powerclock.conf"), RUNTIME / "sddm.conf"),
    "lightdm": (Path("/etc/lightdm/lightdm.conf.d/99-powerclock.conf"), RUNTIME / "lightdm.conf"),
}
ACTION = "org.powerclock.helper.wake"
_USER = re.compile(r"[a-z_][a-z0-9_.-]*")

Command = list[str]


def packaged(name: str) -> Path:
    return Path(str(files("powerclock.helper") / name))


def render_rules(user: str) -> str:
    if not _USER.fullmatch(user):
        raise ValueError(f"unexpected user name {user!r}")
    return packaged("50-powerclock-unattended.rules.in").read_text().replace("@USER@", user)


def display_managers(root: Path = Path("/")) -> list[str]:
    """The display managers installed (the ones the one-time log-in knows)."""
    found = []
    if (root / "etc/sddm.conf.d").is_dir() or (root / "usr/bin/sddm").exists():
        found.append("sddm")
    if (root / "etc/lightdm").is_dir():
        found.append("lightdm")
    return found


def install_commands(
    *,
    unattended_user: str | None,
    rules_file: Path,
    managers: Iterable[str] | None = None,
) -> list[Command]:
    """Copy the helper, the polkit policy (and the unattended rule) and the boot service
    into place as root, and point the display managers' settings at /run."""
    commands = [
        _install("0755", packaged("powerclock_helper_linux.py"), HELPER),
        _install("0644", packaged("org.powerclock.helper.policy"), POLICY),
    ]
    if unattended_user is not None:
        atomic_write(rules_file, render_rules(unattended_user))
        commands.append(_install("0644", rules_file, RULES))
    commands += [
        _install("0644", packaged("powerclock-boot.service"), BOOT_UNIT),
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", BOOT_UNIT.name],
    ]
    for manager in display_managers() if managers is None else managers:
        link, target = DM_LINKS[manager]
        commands += [
            ["sudo", "mkdir", "-p", str(link.parent)],
            ["sudo", "ln", "-sfn", str(target), str(link)],
        ]
    return commands


def uninstall_commands(helper_present: bool) -> list[Command]:
    commands = [["sudo", str(HELPER), "wake-clear"]] if helper_present else []
    commands += [
        [
            "sudo",
            "rm",
            "-rf",
            str(HELPER),
            str(POLICY),
            str(RULES),
            str(BOOT_UNIT),
            str(BOOT_WANTS),  # what `systemctl disable` removes (it fails if the unit is gone)
            *(str(link) for link, _ in DM_LINKS.values()),
            str(STATE),
            str(RUNTIME),
        ],
        ["sudo", "systemctl", "daemon-reload"],
    ]
    return commands


def shell(command: Sequence[str]) -> str:
    return shlex.join(command)


def script(commands: list[Command]) -> str:
    """The commands as one shell line without their `sudo` (for pkexec, which runs it as root)."""
    return " && ".join(shlex.join(c[1:] if c[:1] == ["sudo"] else c) for c in commands)


def elevated(commands: list[Command]) -> Command:
    """One command that runs them all as root, asking for the password in a desktop window
    (for the GUI, which has no terminal for sudo)."""
    return ["pkexec", "/bin/sh", "-c", script(commands)]


Run = Callable[[Sequence[str]], int]


def run_interactive(command: Sequence[str]) -> int:
    """Runs in the user's terminal, so sudo can ask for the password."""
    return subprocess.run(list(command), check=False).returncode


def run_all(commands: list[Command], run: Run | None = None) -> Command | None:
    """Run in order; return the first command that failed (None: all went well)."""
    run = run or run_interactive
    for command in commands:
        if run(command) != 0:
            return command
    return None


def _install(mode: str, source: Path, target: Path) -> Command:
    return [
        "sudo",
        "install",
        "-D",
        "-o",
        "root",
        "-g",
        "root",
        "-m",
        mode,
        str(source),
        str(target),
    ]
