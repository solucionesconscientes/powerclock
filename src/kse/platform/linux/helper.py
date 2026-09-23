"""`kse helper install/uninstall`: the exact sudo commands, always shown before running."""

import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path

from kse.config import atomic_write

HELPER = Path("/usr/local/libexec/kse-helper")
POLICY = Path("/usr/share/polkit-1/actions/org.kse.helper.policy")
RULES = Path("/etc/polkit-1/rules.d/50-kse-unattended.rules")
ACTION = "org.kse.helper.wake"
_USER = re.compile(r"[a-z_][a-z0-9_.-]*")

Command = list[str]


def packaged(name: str) -> Path:
    return Path(str(files("kse.helper") / name))


def render_rules(user: str) -> str:
    if not _USER.fullmatch(user):
        raise ValueError(f"unexpected user name {user!r}")
    return packaged("50-kse-unattended.rules.in").read_text().replace("@USER@", user)


def install_commands(*, unattended_user: str | None, rules_file: Path) -> list[Command]:
    """Copy the helper and the polkit policy (and the unattended rule) into place as root."""
    commands = [
        _install("0755", packaged("kse_helper_linux.py"), HELPER),
        _install("0644", packaged("org.kse.helper.policy"), POLICY),
    ]
    if unattended_user is not None:
        atomic_write(rules_file, render_rules(unattended_user))
        commands.append(_install("0644", rules_file, RULES))
    return commands


def uninstall_commands(helper_present: bool) -> list[Command]:
    commands = [["sudo", str(HELPER), "wake-clear"]] if helper_present else []
    commands.append(["sudo", "rm", "-f", str(HELPER), str(POLICY), str(RULES)])
    return commands


def shell(command: Sequence[str]) -> str:
    return shlex.join(command)


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
