"""Desktop integration: graceful logout/shutdown, screen off, media players and opening files."""

import logging
from collections.abc import Mapping

from dbus_fast import Variant

from kse.platform.base import NotSupported, PowerAction
from kse.platform.linux.commands import Commands
from kse.platform.linux.dbus import PROPERTIES, Bus, DBusError, get_property, has_owner, list_names
from kse.platform.linux.wayland import find_socket

log = logging.getLogger(__name__)

KDE_SHUTDOWN = "org.kde.Shutdown"
KDE_METHODS = {
    PowerAction.SHUTDOWN: "logoutAndShutdown",
    PowerAction.REBOOT: "logoutAndReboot",
    PowerAction.LOGOUT: "logout",
}
GNOME_SESSION = "org.gnome.SessionManager"
GNOME_FLAGS = {
    PowerAction.SHUTDOWN: "--power-off",
    PowerAction.REBOOT: "--reboot",
    PowerAction.LOGOUT: "--logout",
}
MUTTER_DISPLAY = "org.gnome.Mutter.DisplayConfig"
MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"


class Desktop:
    def __init__(self, session_bus: Bus, commands: Commands, env: Mapping[str, str]) -> None:
        self._bus = session_bus
        self._commands = commands
        self._env = env

    def graphical_env(self) -> dict[str, str]:
        """Variables that GUI helpers need; a systemd user service may lack them."""
        extra = {key: self._env[key] for key in ("DISPLAY", "XDG_RUNTIME_DIR") if key in self._env}
        socket = find_socket(self._env)
        if socket is not None:
            extra["WAYLAND_DISPLAY"] = str(socket)
        return extra

    async def graceful_method(self) -> str | None:
        """Which session manager can log out asking applications to save (None: none)."""
        try:
            if await has_owner(self._bus, KDE_SHUTDOWN):
                return f"KDE ({KDE_SHUTDOWN})"
            if await has_owner(self._bus, GNOME_SESSION) and self._commands.which(
                "gnome-session-quit"
            ):
                return "GNOME (gnome-session-quit)"
        except DBusError:
            return None
        return None

    async def graceful(self, action: PowerAction) -> bool:
        """Log out / shut down / reboot through the session manager; False if there is none."""
        method = await self.graceful_method()
        if method is None:
            return False
        if method.startswith("KDE"):
            await self._bus.call(KDE_SHUTDOWN, "/Shutdown", KDE_SHUTDOWN, KDE_METHODS[action])
            return True
        argv = ["gnome-session-quit", GNOME_FLAGS[action], "--no-prompt"]
        code, output = await self._commands.run(argv, self.graphical_env())
        if code != 0:
            raise OSError(f"gnome-session-quit failed: {output}")
        return True

    async def screen_off_method(self) -> str | None:
        if self._commands.which("kscreen-doctor") and await self._owned(KDE_SHUTDOWN):
            return "kscreen-doctor --dpms off"
        if await self._owned(MUTTER_DISPLAY):
            return "GNOME DisplayConfig"
        if self._env.get("XDG_SESSION_TYPE") == "x11" and self._commands.which("xset"):
            return "xset dpms force off"
        return None

    async def screen_off(self) -> None:
        method = await self.screen_off_method()
        if method is None:
            raise NotSupported(
                "power.screen_off",
                "no way to turn off the screen found",
                fix_hint="KDE: install kscreen (kscreen-doctor); X11: install x11-xserver-utils",
            )
        if method == "GNOME DisplayConfig":  # PowerSaveMode 1 = standby
            await self._bus.call(
                MUTTER_DISPLAY,
                "/org/gnome/Mutter/DisplayConfig",
                PROPERTIES,
                "Set",
                "ssv",
                [MUTTER_DISPLAY, "PowerSaveMode", Variant("i", 1)],
            )
            return
        code, output = await self._commands.run(method.split(), self.graphical_env())
        if code != 0:
            raise OSError(f"{method} failed: {output}")

    async def players(self) -> dict[str, str]:
        """MPRIS players and their PlaybackStatus ("Playing", "Paused", "Stopped")."""
        statuses: dict[str, str] = {}
        for name in await list_names(self._bus):
            if not name.startswith(MPRIS_PREFIX):
                continue
            try:
                statuses[name.removeprefix(MPRIS_PREFIX)] = str(
                    await get_property(
                        self._bus,
                        name,
                        MPRIS_PATH,
                        "org.mpris.MediaPlayer2.Player",
                        "PlaybackStatus",
                    )
                )
            except DBusError as exc:  # a player that went away or misbehaves
                log.debug("mpris: %s: %s", name, exc)
        return statuses

    async def media_playing(self) -> bool | None:
        try:
            return "Playing" in (await self.players()).values()
        except DBusError:
            return None  # no session bus (e.g. a server): unknown

    async def open(self, target: str) -> None:
        if self._commands.which("xdg-open") is None:
            raise NotSupported("open", "xdg-open is not installed", fix_hint="install xdg-utils")
        code = await self._commands.spawn(["xdg-open", target], self.graphical_env())
        if code not in (None, 0):
            raise OSError(f"xdg-open could not open {target!r} (exit code {code})")

    async def _owned(self, name: str) -> bool:
        try:
            return await has_owner(self._bus, name)
        except DBusError:
            return False
