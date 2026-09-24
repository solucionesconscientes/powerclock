"""Seconds since the last keyboard/mouse input, trying one strategy after another.

1. Wayland ext-idle-notify-v1 (KWin, sway, Hyprland…)
2. GNOME: org.gnome.Mutter.IdleMonitor (milliseconds)
3. logind IdleHint (only as good as the desktop that sets it)
4. xprintidle (X11)

KDE's org.freedesktop.ScreenSaver.GetSessionIdleTime is left out on purpose: it is not
supported on Wayland, and its units on X11 are not reliable enough to decide a suspend.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from powerclock.platform.base import NotSupported
from powerclock.platform.linux.commands import Commands
from powerclock.platform.linux.dbus import Bus, DBusError
from powerclock.platform.linux.logind import Logind
from powerclock.platform.linux.wayland import IdleMonitor, WaylandError, find_socket

log = logging.getLogger(__name__)

MUTTER = "org.gnome.Mutter.IdleMonitor"
MUTTER_PATH = "/org/gnome/Mutter/IdleMonitor/Core"

WAYLAND = "Wayland ext-idle-notify-v1"
GNOME = "GNOME Mutter IdleMonitor"
LOGIND = "logind IdleHint"
XPRINTIDLE = "xprintidle"


class IdleProbe:
    def __init__(
        self, session_bus: Bus, logind: Logind, commands: Commands, env: Mapping[str, str]
    ) -> None:
        self._session = session_bus
        self._logind = logind
        self._commands = commands
        self._env = env
        self._wayland: IdleMonitor | None = None
        self.strategy: str | None = None  # the one that answered last

    @property
    def input_only(self) -> bool:
        """Wayland v2 measures only keyboard/mouse input, ignoring idle inhibitors."""
        return self._wayland is not None and self._wayland.input_only

    async def idle_seconds(self) -> float | None:
        for name, read in (
            (WAYLAND, self._from_wayland),
            (GNOME, self._from_gnome),
            (LOGIND, self._from_logind),
            (XPRINTIDLE, self._from_xprintidle),
        ):
            try:
                value = await read()
            except (DBusError, NotSupported, WaylandError, OSError, ValueError) as exc:
                log.debug("idle: %s unavailable: %s", name, exc)
                continue
            self.strategy = name
            return value
        self.strategy = None
        return None

    async def close(self) -> None:
        if self._wayland is not None:
            await self._wayland.close()
            self._wayland = None

    async def _from_wayland(self) -> float:
        if self._wayland is None or not self._wayland.running:
            socket = find_socket(self._env)
            if socket is None:
                raise NotSupported("idle", "no Wayland compositor socket")
            if self._wayland is not None:
                await self._wayland.close()
            self._wayland = IdleMonitor(socket)
            await self._wayland.start()
        return self._wayland.idle_seconds()

    async def _from_gnome(self) -> float:
        [milliseconds] = await self._session.call(MUTTER, MUTTER_PATH, MUTTER, "GetIdletime")
        return milliseconds / 1000

    async def _from_logind(self) -> float:
        since = await self._logind.idle_since()
        return 0.0 if since is None else max(0.0, (datetime.now(UTC) - since).total_seconds())

    async def _from_xprintidle(self) -> float:
        if not self._env.get("DISPLAY") or self._commands.which("xprintidle") is None:
            raise NotSupported("idle", "xprintidle needs X11 and the xprintidle program")
        code, output = await self._commands.run(["xprintidle"])
        if code != 0:
            raise OSError(f"xprintidle failed: {output}")
        return int(output) / 1000
