"""The app's own icons (SVG, so they look right at any size and on every OS) and theme icons
with a fallback."""

from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

from PySide6.QtGui import QIcon

TrayState = Literal["idle", "scheduled", "watching", "wake", "countdown", "offline"]


def path(name: str) -> Path:
    return Path(str(files("powerclock.gui") / "icons" / f"{name}.svg"))


@cache
def app_icon() -> QIcon:
    return QIcon(str(path("powerclock")))


@cache
def tray_icon(state: TrayState) -> QIcon:
    return QIcon(str(path(f"tray-{state}")))


def themed(name: str) -> QIcon:
    """An icon of the desktop's theme (Breeze, Adwaita…); empty where there is no theme."""
    return QIcon.fromTheme(name)
