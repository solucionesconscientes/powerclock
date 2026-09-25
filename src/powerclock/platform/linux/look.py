"""The desktop's font, for the GUI: Qt from pip does not load the Plasma or GNOME platform
theme, so it would use "Sans Serif 9" instead of Noto Sans 10 or Cantarell 11."""

import configparser
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

Font = tuple[str, float]  # family, size in points
PLASMA_DEFAULT: Font = ("Noto Sans", 10.0)  # what Plasma uses when kdeglobals says nothing
Run = Callable[[list[str]], str]


def desktop_font(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    run: Run | None = None,
) -> Font | None:
    """Plasma's general font (kdeglobals, or its default), else GNOME's (gsettings)."""
    env = os.environ if env is None else env
    home = home or Path.home()
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper()
    if "KDE" in desktop:
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        return kde_font(config / "kdeglobals") or PLASMA_DEFAULT
    if any(name in desktop for name in ("GNOME", "UNITY", "CINNAMON", "BUDGIE", "PANTHEON")):
        run = run or _gsettings
        try:
            return gnome_font(run(["org.gnome.desktop.interface", "font-name"]))
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def kde_font(path: Path) -> Font | None:
    """[General] font=Noto Sans,10,-1,5,400,0,0,0,0,0,0,0,0,0,0,1"""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return None
    value = parser.get("General", "font", fallback="")
    family, _, rest = value.partition(",")
    size = rest.split(",", 1)[0]
    try:
        points = float(size)
    except ValueError:
        return None
    return (family.strip(), points) if family.strip() and points > 0 else None


def gnome_font(value: str) -> Font | None:
    """'Cantarell 11' (gsettings prints it quoted); the size is the last word."""
    match = re.fullmatch(r"'?(.+?)\s+(\d+(?:\.\d+)?)'?", value.strip())
    if match is None:
        return None
    family = re.sub(r"\s+(Regular|Medium|Bold|Italic|Light)$", "", match[1])
    return family, float(match[2])


def _gsettings(args: list[str]) -> str:
    program = shutil.which("gsettings")
    if program is None:
        raise OSError("gsettings is not installed")
    done = subprocess.run(  # a fixed program with fixed arguments
        [program, "get", *args], capture_output=True, text=True, timeout=2, check=True
    )
    return done.stdout
