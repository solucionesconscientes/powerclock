"""The GUI in the applications menu and at login: freedesktop .desktop files and the icon,
all in the user's own folders (no root)."""

import os
import shutil
import sys
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from powerclock.config import atomic_write

MENU_FILE = "powerclock.desktop"
AUTOSTART_FILE = "powerclock-gui.desktop"
ICON = "powerclock"


def data_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def config_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def menu_path(env: Mapping[str, str] | None = None) -> Path:
    return data_home(env) / "applications" / MENU_FILE


def autostart_path(env: Mapping[str, str] | None = None) -> Path:
    return config_home(env) / "autostart" / AUTOSTART_FILE


def icon_path(env: Mapping[str, str] | None = None) -> Path:
    return data_home(env) / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON}.svg"


def gui_executable() -> Path:
    """powerclock-gui as installed (pipx puts it on the PATH), else next to this Python."""
    found = shutil.which("powerclock-gui")
    return Path(found) if found else Path(sys.executable).parent / "powerclock-gui"


def render(executable: Path, *, tray: bool) -> str:
    command = f"{_quote(executable)} --tray" if tray else _quote(executable)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=PowerClock",
        "GenericName=Power and task scheduler",
        "GenericName[es]=Programador de energía y tareas",
        "Comment=Shut down, suspend, wake up and run tasks at a time or when a condition is met",
        "Comment[es]=Apaga, suspende, enciende y ejecuta tareas a una hora o cuando se cumple "
        "una condición",
        f"Exec={command}",
        f"Icon={ICON}",
        "Terminal=false",
        "Categories=System;Utility;",
        "Keywords=shutdown;suspend;wake;timer;apagar;suspender;encender;temporizador;",
        "StartupNotify=false",
    ]
    if tray:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def in_menu(env: Mapping[str, str] | None = None) -> bool:
    return menu_path(env).exists()


def at_login(env: Mapping[str, str] | None = None) -> bool:
    return autostart_path(env).exists()


def set_menu(on: bool, env: Mapping[str, str] | None = None) -> list[str]:
    """Add PowerClock to the applications menu (with its icon), or take it out."""
    if not on:
        return _remove(menu_path(env), icon_path(env))
    icon = icon_path(env)
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(files("powerclock.gui") / "icons" / "powerclock.svg"), icon)
    atomic_write(menu_path(env), render(gui_executable(), tray=False))
    return [f"wrote {menu_path(env)}", f"wrote {icon}"]


def set_login(on: bool, env: Mapping[str, str] | None = None) -> list[str]:
    """Start the tray icon when the session starts, or not."""
    if not on:
        return _remove(autostart_path(env))
    path = autostart_path(env)
    atomic_write(path, render(gui_executable(), tray=True))
    return [f"wrote {path}"]


def _remove(*paths: Path) -> list[str]:
    done = []
    for path in paths:
        if path.exists():
            path.unlink()
            done.append(f"removed {path}")
    return done


def _quote(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text
