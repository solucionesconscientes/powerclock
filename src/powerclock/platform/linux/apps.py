"""Installed applications, read from their desktop entries (the files behind the menu), and
the command that opens each one with extra arguments.

Follows the freedesktop.org Desktop Entry specification: entries in
$XDG_DATA_HOME/applications come first, then each $XDG_DATA_DIRS one; the Flatpak and Snap
export folders are added in case a service's environment lacks them. The id of an entry
is its path under applications/ with "/" turned into "-", without ".desktop".
"""

import logging
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from powerclock.platform.base import AppInfo

log = logging.getLogger(__name__)

EXTRA_DATA_DIRS = (
    "var/lib/flatpak/exports/share",
    "var/lib/snapd/desktop",
)
FILE_CODES = ("%f", "%F", "%u", "%U")
DEPRECATED_CODES = ("%d", "%D", "%n", "%N", "%v", "%m")
# Arguments after these are files, not options: "flatpak run --file-forwarding … @@u %u @@"
# (files and addresses go inside) and "mpv … -- %U".
FORWARD_MARKERS = ("@@", "@@u", "--")


@dataclass(frozen=True)
class DesktopEntry:
    id: str
    path: Path
    name: str
    exec: str
    names: dict[str, str] = field(default_factory=dict)
    icon: str | None = None
    terminal: bool = False
    no_display: bool = False
    flatpak: str | None = None
    wm_class: str | None = None
    categories: tuple[str, ...] = ()

    def info(self) -> AppInfo:
        return AppInfo(
            id=self.id,
            name=self.name,
            names=dict(self.names),
            icon=self.icon,
            flatpak=self.flatpak,
            categories=self.categories,
            terminal=self.terminal,
        )

    def window_ids(self) -> list[str]:
        """What its windows may be called (Wayland app id, X11 class) to find them."""
        ids = [self.id]
        for extra in (self.flatpak, self.wm_class, _program_name(self.exec)):
            if extra and extra not in ids:
                ids.append(extra)
        return ids


def data_dirs(env: Mapping[str, str], root: Path = Path("/")) -> list[Path]:
    """Where applications/ folders live, most important first."""
    home = Path(env.get("HOME") or Path.home())
    data_home = env.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    dirs = [Path(data_home)]
    dirs += [
        Path(p) for p in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if p
    ]
    dirs += [Path(data_home) / "flatpak" / "exports" / "share"]
    dirs += [Path("/") / extra for extra in EXTRA_DATA_DIRS]
    unique: list[Path] = []
    for directory in dirs:
        path = root / directory.relative_to("/") if directory.is_absolute() else root / directory
        if path not in unique:
            unique.append(path)
    return unique


def entries(env: Mapping[str, str], root: Path = Path("/")) -> dict[str, DesktopEntry]:
    """Every launchable application by id (hidden and uninstallable ones left out)."""
    found: dict[str, DesktopEntry | None] = {}
    for directory in data_dirs(env, root):
        folder = directory / "applications"
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.desktop")):
            entry_id = str(path.relative_to(folder)).replace("/", "-").removesuffix(".desktop")
            if entry_id in found:
                continue  # an earlier folder overrides it (or hides it)
            found[entry_id] = _load(entry_id, path, env)
    return {key: entry for key, entry in found.items() if entry is not None}


def _load(entry_id: str, path: Path, env: Mapping[str, str]) -> DesktopEntry | None:
    try:
        values = parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        log.debug("cannot read %s: %s", path, exc)
        return None
    if values.get("Type") != "Application" or values.get("Hidden") == "true":
        return None
    name, command = values.get("Name"), values.get("Exec")
    if not name or not command:
        return None
    try_exec = values.get("TryExec")
    if try_exec and not _found(try_exec, env):
        return None
    names = {
        key[5:-1]: value
        for key, value in values.items()
        if key.startswith("Name[") and key.endswith("]")
    }
    return DesktopEntry(
        id=entry_id,
        path=path,
        name=name,
        exec=command,
        names=names,
        icon=values.get("Icon") or None,
        terminal=values.get("Terminal") == "true",
        no_display=values.get("NoDisplay") == "true",
        flatpak=values.get("X-Flatpak") or None,
        wm_class=values.get("StartupWMClass") or None,
        categories=tuple(c for c in values.get("Categories", "").split(";") if c),
    )


def parse(text: str) -> dict[str, str]:
    """The keys of the [Desktop Entry] group, with the string escapes (\\s \\n \\t \\r \\\\)
    resolved."""
    values: dict[str, str] = {}
    group = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values.setdefault(key.strip(), _unescape(value.strip()))
    return values


def _unescape(value: str) -> str:
    out, index = [], 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            nxt = value[index + 1]
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(nxt, "\\" + nxt))
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def split_exec(value: str) -> list[str]:
    """The arguments of an Exec value: separated by spaces; inside double quotes a backslash
    escapes ", `, $ and \\."""
    args: list[str] = []
    current: list[str] = []
    quoted = in_arg = False
    index = 0
    while index < len(value):
        char = value[index]
        if quoted:
            if char == "\\" and index + 1 < len(value) and value[index + 1] in '"`$\\':
                current.append(value[index + 1])
                index += 2
                continue
            if char == '"':
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted = in_arg = True
        elif char in " \t":
            if in_arg:
                args.append("".join(current))
                current, in_arg = [], False
        else:
            current.append(char)
            in_arg = True
        index += 1
    if quoted:
        raise ValueError(f"unbalanced quote in Exec={value!r}")
    if in_arg:
        args.append("".join(current))
    return args


def command(entry: DesktopEntry, args: list[str] | tuple[str, ...] = ()) -> list[str]:
    """The command that opens `entry` with `args`: they take the place of its %f/%u field
    code (or go at the end). After "--" or inside a Flatpak file-forwarding section only
    files and addresses belong, so options (starting with "-") go just before it."""
    options = [arg for arg in args if arg.startswith("-")]
    positional = [arg for arg in args if not arg.startswith("-")]
    out: list[str] = []
    placed = False
    for token in split_exec(entry.exec):
        if token in FILE_CODES:
            if not placed:
                if out and out[-1] in FORWARD_MARKERS:
                    marker = out.pop()
                    out += [*options, marker, *positional]
                else:
                    out += list(args)
                placed = True
            continue
        if token == "%i":
            out += ["--icon", entry.icon] if entry.icon else []
            continue
        if token in DEPRECATED_CODES:
            continue
        out.append(_field_codes(token, entry))
    if not placed:
        out += list(args)
    return out


def _field_codes(token: str, entry: DesktopEntry) -> str:
    """Field codes inside an argument ("--name=%c"): %c name, %k file, %% a percent sign;
    file codes inside an argument cannot take a list, so they go away."""
    out, index = [], 0
    while index < len(token):
        if token[index] == "%" and index + 1 < len(token):
            code = token[index + 1]
            out.append({"c": entry.name, "k": str(entry.path), "%": "%"}.get(code, ""))
            index += 2
        else:
            out.append(token[index])
            index += 1
    return "".join(out)


def find(catalog: Mapping[str, DesktopEntry], app: str) -> DesktopEntry | None:
    """An entry by id, also accepting ".desktop", its Flatpak id or any capitalisation."""
    key = app.strip().removesuffix(".desktop")
    if key in catalog:
        return catalog[key]
    lowered = key.lower()
    for entry in catalog.values():
        if entry.id.lower() == lowered or (entry.flatpak or "").lower() == lowered:
            return entry
    return None


def _found(program: str, env: Mapping[str, str]) -> bool:
    if Path(program).is_absolute():
        return os.access(program, os.X_OK)
    return shutil.which(program, path=env.get("PATH")) is not None


def _program_name(exec_value: str) -> str | None:
    try:
        args = split_exec(exec_value)
    except ValueError:
        return None
    if not args:
        return None
    if Path(args[0]).name == "flatpak":
        return None  # its windows carry the Flatpak id instead
    return Path(args[0]).name
