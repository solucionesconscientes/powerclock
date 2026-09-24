"""The daemon as a systemd user service (~/.config/systemd/user/powerclock.service)."""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from powerclock.config import atomic_write

UNIT = "powerclock.service"


class Runner(Protocol):
    def __call__(self, argv: Sequence[str]) -> tuple[int, str]: ...


class ServiceError(Exception):
    pass


def run(argv: Sequence[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=60, check=False)
    except FileNotFoundError:
        return 127, f"{argv[0]}: command not found"
    return result.returncode, (result.stdout + result.stderr).strip()


def unit_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    config = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "systemd" / "user" / UNIT


def daemon_executable() -> Path:
    """powerclock-daemon next to the running interpreter (the venv of uv or pipx), else on PATH."""
    sibling = Path(sys.executable).parent / "powerclock-daemon"
    if sibling.exists():
        return sibling
    found = shutil.which("powerclock-daemon")
    if found is None:
        raise ServiceError("powerclock-daemon not found: is powerclock installed?")
    return Path(found)


def render_unit(executable: Path, *, dry_run: bool) -> str:
    environment = "Environment=POWERCLOCK_DRY_RUN=1\n" if dry_run else ""
    return (
        "[Unit]\n"
        "Description=PowerClock daemon (power and task automation)\n"
        "After=dbus.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={executable} --foreground\n"
        f"{environment}"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


@dataclass
class Status:
    installed: bool
    active: str
    enabled: str
    unit: Path


def install(
    *,
    dry_run: bool,
    linger_user: str | None = None,
    runner: Runner | None = None,
    path: Path | None = None,
    executable: Path | None = None,
) -> list[str]:
    """Write the unit, enable and start it; with `linger_user`, keep it running without a
    login. Returns what was done."""
    runner = runner or run
    path = path or unit_path()
    atomic_write(path, render_unit(executable or daemon_executable(), dry_run=dry_run))
    done = [f"wrote {path}"]
    _check(runner, ["systemctl", "--user", "daemon-reload"])
    _check(runner, ["systemctl", "--user", "enable", "--now", UNIT])
    _check(runner, ["systemctl", "--user", "restart", UNIT])  # picks up a changed unit
    done.append(f"enabled and started {UNIT}")
    if linger_user:
        _check(runner, ["loginctl", "enable-linger", linger_user])
        done.append(f"linger enabled for {linger_user}")
    return done


def restart(*, runner: Runner | None = None) -> list[str]:
    """Restart the service (e.g. after an update, to run the new version)."""
    _check(runner or run, ["systemctl", "--user", "restart", UNIT])
    return [f"restarted {UNIT}"]


def start(*, runner: Runner | None = None) -> list[str]:
    """Start the installed service as it is (its unit, dry run or not, is not rewritten)."""
    _check(runner or run, ["systemctl", "--user", "start", UNIT])
    return [f"started {UNIT}"]


def uninstall(*, runner: Runner | None = None, path: Path | None = None) -> list[str]:
    """Stop and remove the service. Rules, history and settings are kept."""
    runner = runner or run
    path = path or unit_path()
    runner(["systemctl", "--user", "disable", "--now", UNIT])  # fine if it was not running
    done = [f"stopped and disabled {UNIT}"]
    if path.exists():
        path.unlink()
        done.append(f"removed {path}")
    _check(runner, ["systemctl", "--user", "daemon-reload"])
    return done


def status(*, runner: Runner | None = None, path: Path | None = None) -> Status:
    runner = runner or run
    path = path or unit_path()
    _, active = runner(["systemctl", "--user", "is-active", UNIT])
    _, enabled = runner(["systemctl", "--user", "is-enabled", UNIT])
    return Status(
        installed=path.exists(), active=active or "unknown", enabled=enabled or "unknown", unit=path
    )


def _check(runner: Runner, argv: list[str]) -> None:
    code, output = runner(argv)
    if code != 0:
        raise ServiceError(f"{' '.join(argv)} failed: {output}")
