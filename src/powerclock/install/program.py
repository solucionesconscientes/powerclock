"""How this copy of PowerClock was installed, whether there is a newer version, and the
commands that update or remove the program itself."""

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from powerclock import __version__

PYPI = "https://pypi.org/pypi/powerclock/json"
Kind = Literal["installer", "pipx", "other"]


def private_uv(data_home: Path | None = None) -> Path:
    """Where the installer keeps its own copy of uv."""
    home = data_home or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return home / "powerclock" / "uv" / "uv"


def installed_by(prefix: Path | None = None) -> Kind:
    """The installer puts PowerClock in uv's tools folder; pipx in its venvs folder."""
    parts = (prefix or Path(sys.prefix)).resolve().parts
    if len(parts) >= 3 and parts[-2] == "tools" and parts[-3] == "uv":
        return "installer"
    if "pipx" in parts and "venvs" in parts:
        return "pipx"
    return "other"


def uv_command() -> str | None:
    uv = private_uv()
    if uv.exists():
        return str(uv)
    return shutil.which("uv")


@dataclass(frozen=True)
class Commands:
    upgrade: list[str] | None
    uninstall: list[str] | None


def commands(kind: Kind | None = None) -> Commands:
    """How to update or remove the program for the way it was installed (None: by hand)."""
    kind = kind or installed_by()
    if kind == "installer" and (uv := uv_command()):
        return Commands(
            [uv, "tool", "upgrade", "powerclock"], [uv, "tool", "uninstall", "powerclock"]
        )
    if kind == "pipx" and (pipx := shutil.which("pipx")):
        return Commands([pipx, "upgrade", "powerclock"], [pipx, "uninstall", "powerclock"])
    return Commands(None, None)


def version_key(version: str) -> tuple[int, ...]:
    """Sort key: 0.1.0 < 0.1.1 < 0.2.0, and a pre-release (0.2.0.dev1, 0.2.0rc1) sorts before
    its release."""
    main = re.match(r"(\d+(?:\.\d+)*)", version)
    numbers = tuple(int(n) for n in main[1].split(".")) if main else (0,)
    numbers = numbers + (0,) * (3 - len(numbers))
    pre = version[main.end() :] if main else version
    return (*numbers, 0 if pre.strip(".") else 1)


def newer(latest: str, current: str = __version__) -> bool:
    return version_key(latest) > version_key(current)


async def latest_version(client: httpx.AsyncClient | None = None) -> str:
    """The newest release on PyPI (an error if PyPI cannot be reached)."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        response = await client.get(PYPI)
        response.raise_for_status()
        return str(response.json()["info"]["version"])
    finally:
        if owned:
            await client.aclose()
