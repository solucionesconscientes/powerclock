"""The user's systemd manager, on the session bus: the desktop session's environment, whether
the session is up, and applications started as transient units of their own.

Starting an app as a unit (like KDE does with app-*.service) gives it the environment the
desktop published to the manager (WAYLAND_DISPLAY, DISPLAY, XAUTHORITY…), even when
PowerClock's service started before the session; it keeps running if PowerClock restarts,
and it can be stopped cleanly, or opened again if it closes (keep_open).
"""

import asyncio
import re
import secrets
import signal
from collections.abc import Mapping
from pathlib import Path

from dbus_fast import Variant

from powerclock.platform.base import StopSignal
from powerclock.platform.linux.dbus import Bus, DBusError, get_property

SYSTEMD = "org.freedesktop.systemd1"
SYSTEMD_PATH = "/org/freedesktop/systemd1"
MANAGER = "org.freedesktop.systemd1.Manager"
UNIT = "org.freedesktop.systemd1.Unit"
SERVICE = "org.freedesktop.systemd1.Service"
GRAPHICAL = "graphical-session.target"
UNIT_PREFIX = "app-powerclock-"
SIGNALS: dict[str, int] = {"TERM": signal.SIGTERM, "INT": signal.SIGINT, "HUP": signal.SIGHUP}
STOP_TIMEOUT = 30  # seconds a closing app gets before it is killed
KEEP_OPEN_BURST = 3  # reopened at most this many times…
KEEP_OPEN_INTERVAL = 3600  # …per this many seconds
START_SETTLE = 2.0  # seconds to notice an app that fails right away
MICRO = 1_000_000


def unit_name(app: str) -> str:
    """app-powerclock-<app>-<random>.service, with what a unit name cannot hold replaced."""
    return f"{UNIT_PREFIX}{_escape(app)}-{secrets.token_hex(3)}.service"


def unit_pattern(app: str) -> str:
    return f"{UNIT_PREFIX}{_escape(app)}-*.service"


def _escape(app: str) -> str:
    return re.sub(r"[^A-Za-z0-9:_.]", "_", app)


class UserManager:
    def __init__(self, bus: Bus) -> None:
        self._bus = bus

    async def environment(self) -> dict[str, str]:
        """The manager's environment, where the desktop session publishes its variables."""
        items = await get_property(self._bus, SYSTEMD, SYSTEMD_PATH, MANAGER, "Environment")
        env: dict[str, str] = {}
        for item in items:
            key, sep, value = str(item).partition("=")
            if sep:
                env[key] = value
        return env

    async def unit_state(self, name: str) -> str | None:
        """ActiveState of a unit ("active", "inactive", "failed"…); None if not loaded."""
        try:
            [path] = await self._bus.call(SYSTEMD, SYSTEMD_PATH, MANAGER, "GetUnit", "s", [name])
        except DBusError as exc:
            if exc.name.endswith("NoSuchUnit"):
                return None
            raise
        return str(await get_property(self._bus, SYSTEMD, path, UNIT, "ActiveState"))

    async def graphical(self) -> bool:
        return await self.unit_state(GRAPHICAL) == "active"

    async def start(
        self,
        name: str,
        argv: list[str],
        *,
        description: str,
        workdir: Path,
        stop_signal: StopSignal = "TERM",
        keep_open: bool = False,
    ) -> None:
        properties: list[list[object]] = [
            ["Description", Variant("s", description)],
            ["ExecStart", Variant("a(sasb)", [[argv[0], argv, False]])],
            ["WorkingDirectory", Variant("s", str(workdir))],
            ["CollectMode", Variant("s", "inactive-or-failed")],
            ["KillSignal", Variant("i", int(SIGNALS[stop_signal]))],
            ["TimeoutStopUSec", Variant("t", STOP_TIMEOUT * MICRO)],
        ]
        if keep_open:
            properties += [
                ["Restart", Variant("s", "always")],
                ["RestartUSec", Variant("t", 5 * MICRO)],
                ["StartLimitIntervalUSec", Variant("t", KEEP_OPEN_INTERVAL * MICRO)],
                ["StartLimitBurst", Variant("u", KEEP_OPEN_BURST)],
            ]
        await self._bus.call(
            SYSTEMD,
            SYSTEMD_PATH,
            MANAGER,
            "StartTransientUnit",
            "ssa(sv)a(sa(sv))",
            [name, "fail", properties, []],
        )

    async def main_pid(self, name: str) -> int | None:
        try:
            [path] = await self._bus.call(SYSTEMD, SYSTEMD_PATH, MANAGER, "GetUnit", "s", [name])
        except DBusError:
            return None
        pid = int(await get_property(self._bus, SYSTEMD, path, SERVICE, "MainPID"))
        return pid or None

    async def settle(self, name: str) -> tuple[str | None, int | None]:
        """Wait a moment after starting: (state, main PID). A unit that failed right away
        says "failed"; one that ended fine (an app that handed over to a running copy of
        itself) is gone (None)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + START_SETTLE
        state: str | None = None
        while True:
            state = await self.unit_state(name)
            pid = await self.main_pid(name) if state == "active" else None
            if state in (None, "failed", "inactive") or pid or loop.time() >= deadline:
                return state, pid
            await asyncio.sleep(0.1)

    async def units(self, pattern: str) -> list[str]:
        """Loaded units whose name matches `pattern` and that are not stopped."""
        states = ["active", "activating", "reloading", "deactivating"]
        [listed] = await self._bus.call(
            SYSTEMD, SYSTEMD_PATH, MANAGER, "ListUnitsByPatterns", "asas", [states, [pattern]]
        )
        return [str(row[0]) for row in listed]

    async def stop(self, name: str) -> None:
        await self._bus.call(SYSTEMD, SYSTEMD_PATH, MANAGER, "StopUnit", "ss", [name, "replace"])


def display_ready(env: Mapping[str, str], runtime_dir: Path) -> bool:
    """The session's variables point at a display that exists (a Wayland socket or an X11
    one), for desktops that do not use graphical-session.target."""
    wayland = env.get("WAYLAND_DISPLAY")
    if wayland:
        socket = Path(wayland) if wayland.startswith("/") else runtime_dir / wayland
        if socket.exists():
            return True
    display = env.get("DISPLAY", "")
    match = re.fullmatch(r":(\d+)(\.\d+)?", display)
    return bool(match and Path(f"/tmp/.X11-unix/X{match[1]}").exists())
