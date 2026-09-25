"""Desktop settings: colour theme, wallpaper, screen brightness (KDE, GNOME, brightnessctl),
power profile (power-profiles-daemon), network connections (NetworkManager's nmcli),
inhibitors (screen on, Do not disturb, no sleep) and screenshots."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from pathlib import Path

from dbus_fast import Variant

from powerclock.platform.base import NotSupported, PowerProfile, Release
from powerclock.platform.linux.commands import Commands
from powerclock.platform.linux.dbus import PROPERTIES, Bus, DBusError, has_owner

KDE_BRIGHTNESS = "org.kde.Solid.PowerManagement"
KDE_BRIGHTNESS_PATH = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
KDE_BRIGHTNESS_IFACE = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"
GNOME_POWER = "org.gnome.SettingsDaemon.Power"
GNOME_POWER_PATH = "/org/gnome/SettingsDaemon/Power"
GNOME_SCREEN = "org.gnome.SettingsDaemon.Power.Screen"
PROFILES = "org.freedesktop.UPower.PowerProfiles"
PROFILES_PATH = "/org/freedesktop/UPower/PowerProfiles"
SCREENSAVER = "org.freedesktop.ScreenSaver"
SCREENSAVER_PATH = "/org/freedesktop/ScreenSaver"
NOTIFICATIONS = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
KDE_SCHEMES = {"dark": "BreezeDark", "light": "BreezeLight"}
SCREENSHOT_LIMIT = 30.0

Hold = Callable[[str, str], "contextlib.AbstractAsyncContextManager[None]"]


class Settings:
    def __init__(
        self,
        session_bus: Bus,
        system_bus: Bus,
        commands: Commands,
        env: Callable[[], Awaitable[Mapping[str, str]]],
        sleep_lock: Hold,
    ) -> None:
        self._session = session_bus
        self._system = system_bus
        self._commands = commands
        self._env = env  # the desktop session's variables (the tools talk to it)
        self._sleep_lock = sleep_lock

    # ── Look ──────────────────────────────────────────────────────────────────

    async def theme(self, theme: str) -> str:
        if self._commands.which("plasma-apply-colorscheme"):
            scheme = KDE_SCHEMES.get(theme, theme)
            await self._run(["plasma-apply-colorscheme", scheme])
            return scheme
        if self._commands.which("gsettings") and theme in ("dark", "light"):
            value = "prefer-dark" if theme == "dark" else "default"
            await self._run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", value]
            )
            return value
        raise NotSupported("theme", "only KDE Plasma and GNOME (light or dark) are supported")

    async def wallpaper(self, path: str) -> None:
        picture = await asyncio.to_thread(_existing, path)
        if self._commands.which("plasma-apply-wallpaperimage"):
            await self._run(["plasma-apply-wallpaperimage", str(picture)])
            return
        if self._commands.which("gsettings"):
            for key in ("picture-uri", "picture-uri-dark"):
                await self._run(
                    ["gsettings", "set", "org.gnome.desktop.background", key, picture.as_uri()]
                )
            return
        raise NotSupported("wallpaper", "only KDE Plasma and GNOME are supported")

    async def brightness(self, percent: int) -> None:
        with contextlib.suppress(DBusError):
            if await has_owner(self._session, KDE_BRIGHTNESS):
                [top] = await self._session.call(
                    KDE_BRIGHTNESS, KDE_BRIGHTNESS_PATH, KDE_BRIGHTNESS_IFACE, "brightnessMax"
                )
                value = max(1, round(int(top) * percent / 100))
                await self._session.call(
                    KDE_BRIGHTNESS,
                    KDE_BRIGHTNESS_PATH,
                    KDE_BRIGHTNESS_IFACE,
                    "setBrightness",
                    "i",
                    [value],
                )
                return
            if await has_owner(self._session, GNOME_POWER):
                await self._session.call(
                    GNOME_POWER,
                    GNOME_POWER_PATH,
                    PROPERTIES,
                    "Set",
                    "ssv",
                    [GNOME_SCREEN, "Brightness", Variant("i", percent)],
                )
                return
        if self._commands.which("brightnessctl"):
            await self._run(["brightnessctl", "set", f"{percent}%"])
            return
        raise NotSupported(
            "brightness", "no way to change the brightness found", fix_hint="install brightnessctl"
        )

    async def power_profile(self, profile: PowerProfile) -> None:
        try:
            await self._system.call(
                PROFILES,
                PROFILES_PATH,
                PROPERTIES,
                "Set",
                "ssv",
                [PROFILES, "ActiveProfile", Variant("s", profile)],
            )
            return
        except DBusError as exc:
            if not self._commands.which("powerprofilesctl"):
                raise NotSupported(
                    "power_profile", f"power-profiles-daemon is not available: {exc}"
                ) from exc
        await self._run(["powerprofilesctl", "set", profile])

    # ── Network ───────────────────────────────────────────────────────────────

    async def network(self, connect: str | None, disconnect: str | None, wifi: bool | None) -> None:
        if not self._commands.which("nmcli"):
            raise NotSupported("network", "nmcli (NetworkManager) is not installed")
        if wifi is not None:
            await self._run(["nmcli", "radio", "wifi", "on" if wifi else "off"])
        if disconnect:
            await self._run(["nmcli", "connection", "down", "id", disconnect])
        if connect:
            await self._run(["nmcli", "connection", "up", "id", connect])

    # ── Inhibitors ────────────────────────────────────────────────────────────

    async def inhibit(
        self, *, screen: bool, notifications: bool, sleep: bool, reason: str
    ) -> Release:
        """Hold what was asked; the returned function gives it all back."""
        releases: list[Callable[[], Awaitable[None]]] = []
        try:
            if screen:
                [cookie] = await self._session.call(
                    SCREENSAVER,
                    SCREENSAVER_PATH,
                    SCREENSAVER,
                    "Inhibit",
                    "ss",
                    ["PowerClock", reason],
                )
                releases.append(partial(self._uninhibit, SCREENSAVER, SCREENSAVER_PATH, cookie))
            if notifications:
                [cookie] = await self._session.call(
                    NOTIFICATIONS,
                    NOTIFICATIONS_PATH,
                    NOTIFICATIONS,
                    "Inhibit",
                    "ssa{sv}",
                    ["powerclock", reason, {}],
                )
                releases.append(partial(self._uninhibit, NOTIFICATIONS, NOTIFICATIONS_PATH, cookie))
            if sleep:
                lock = self._sleep_lock("sleep:idle", reason)
                await lock.__aenter__()
                releases.append(lambda: lock.__aexit__(None, None, None))  # type: ignore[arg-type,return-value]
        except DBusError as exc:
            for release in reversed(releases):
                with contextlib.suppress(Exception):
                    await release()
            raise NotSupported("inhibit", f"the desktop refused: {exc}") from exc

        async def release_all() -> None:
            for release in reversed(releases):
                with contextlib.suppress(Exception):
                    await release()

        return release_all

    async def _uninhibit(self, name: str, path: str, cookie: int) -> None:
        await self._session.call(name, path, name, "UnInhibit", "u", [cookie])

    # ── Screenshots ───────────────────────────────────────────────────────────

    async def screenshot(self, path: str) -> None:
        target = await asyncio.to_thread(_writable, path)
        for argv in (
            ["spectacle", "--background", "--nonotify", "--fullscreen", "--output", str(target)],
            ["gnome-screenshot", "--file", str(target)],
            ["grim", str(target)],
        ):
            if self._commands.which(argv[0]):
                await self._run(argv, limit=SCREENSHOT_LIMIT)
                if not await asyncio.to_thread(target.exists):
                    raise OSError(f"{argv[0]} did not save {target}")
                return
        raise NotSupported(
            "screenshot", "no screenshot tool found (spectacle, gnome-screenshot or grim)"
        )

    async def _run(self, argv: list[str], limit: float | None = None) -> None:
        env = dict(await self._env())
        code, output = await self._commands.run(argv, env, limit=limit)
        if code != 0:
            raise OSError(f"{argv[0]} failed ({code}): {output}")


def _existing(path: str) -> Path:
    picture = Path(path).expanduser()
    if not picture.is_file():
        raise OSError(f"there is no picture {path!r}")
    return picture


def _writable(path: str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
