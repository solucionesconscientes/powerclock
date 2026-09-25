"""Linux backend: logind for power, the desktop's session manager for graceful logouts, and
systemd's user manager and KWin to open applications in the desktop session."""

import asyncio
import os
import pwd
import shutil
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

from dbus_fast import BusType

from powerclock.platform.base import (
    AppInfo,
    Capability,
    LaunchRequest,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerEventCallback,
    PowerMode,
)
from powerclock.platform.linux import apps, session
from powerclock.platform.linux.commands import Commands, SystemCommands
from powerclock.platform.linux.dbus import Bus, DBusError, DBusFastBus
from powerclock.platform.linux.desktop import Desktop
from powerclock.platform.linux.helper import HELPER
from powerclock.platform.linux.host import Host
from powerclock.platform.linux.idle import IdleProbe
from powerclock.platform.linux.kwin import WindowPlacer
from powerclock.platform.linux.logind import ALLOWED, METHODS, Logind
from powerclock.platform.linux.network import wifi_ssid
from powerclock.platform.linux.notify import Notifier

# D-Bus errors that mean "systemd's user manager is not there" (not "it said no").
NO_MANAGER = ("ServiceUnknown", "NoServer", "NameHasNoOwner", "Disconnected", "NoReply")


class LinuxPlatform(PlatformBackend):
    name = "linux"

    def __init__(
        self,
        *,
        system_bus: Bus | None = None,
        session_bus: Bus | None = None,
        commands: Commands | None = None,
        root: Path = Path("/"),
        env: Mapping[str, str] | None = None,
        uid: int | None = None,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.uid = os.getuid() if uid is None else uid
        self.system_bus = system_bus or DBusFastBus(BusType.SYSTEM)
        self.session_bus = session_bus or DBusFastBus(BusType.SESSION)
        self.commands = commands or SystemCommands()
        self.root = root
        self.host = Host(root)
        self.logind = Logind(self.system_bus, self.uid)
        self.desktop = Desktop(self.session_bus, self.commands, self.env)
        self.idle = IdleProbe(self.session_bus, self.logind, self.commands, self.env)
        self.notifier = Notifier(self.session_bus)
        self.session = session.UserManager(self.session_bus)
        self.windows = WindowPlacer(self.session_bus, self.runtime_dir)

    @property
    def runtime_dir(self) -> Path:
        return Path(self.env.get("XDG_RUNTIME_DIR") or f"/run/user/{self.uid}")

    @property
    def home(self) -> Path:
        return Path(self.env.get("HOME") or Path.home())

    @property
    def user(self) -> str:
        try:
            return pwd.getpwuid(self.uid).pw_name
        except KeyError:
            return str(self.uid)

    async def power(self, action: PowerAction, mode: PowerMode) -> None:
        graceful = mode is PowerMode.GRACEFUL
        match action:
            case PowerAction.LOCK:
                await self.logind.lock()
            case PowerAction.SCREEN_OFF:
                await self.desktop.screen_off()
            case PowerAction.LOGOUT:
                if not (graceful and await self.desktop.graceful(action)):
                    await self.logind.terminate_session()
            case PowerAction.SHUTDOWN | PowerAction.REBOOT:
                answer = await self.logind.can(action)
                if answer not in ALLOWED:  # checked before asking the desktop too
                    query, _ = METHODS[action]
                    raise NotSupported(f"power.{action}", f"logind answers {answer!r} to {query}")
                if not (graceful and await self.desktop.graceful(action)):
                    await self.logind.power(action)
            case _:
                await self.logind.power(action)

    async def wake_set(self, when: datetime) -> None:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("wake_set needs a timezone-aware datetime")
        await self._helper("wake-set", str(int(when.timestamp())))

    async def wake_clear(self) -> None:
        await self._helper("wake-clear")

    async def wake_get(self) -> datetime | None:
        return self.host.wake_alarm(self.env)  # sysfs is readable without privileges

    async def _helper(self, *args: str) -> None:
        """Run powerclock-helper as root through pkexec (polkit action
        org.powerclock.helper.wake)."""
        if not self.host.helper_installed():
            raise NotSupported(
                "wake", "powerclock-helper is not installed", fix_hint="powerclock helper install"
            )
        if self.commands.which("pkexec") is None:
            raise NotSupported("wake", "pkexec is not installed", fix_hint="install polkit")
        code, output = await self.commands.run(["pkexec", str(HELPER), *args])
        if code in (126, 127):  # dismissed / not authorized
            raise NotSupported(
                "wake",
                f"not authorized to program the wake-up alarm: {output}",
                fix_hint="without a graphical session: powerclock helper install --unattended",
            )
        if code != 0:
            raise OSError(f"powerclock-helper {args[0]} failed ({code}): {output}")

    async def capabilities(self) -> list[Capability]:
        from powerclock.platform.linux.capabilities import collect

        return await collect(self)

    async def idle_seconds(self) -> float | None:
        return await self.idle.idle_seconds()

    async def media_playing(self) -> bool | None:
        return await self.desktop.media_playing()

    async def wifi_ssid(self) -> str | None:
        return await wifi_ssid(self.system_bus)

    async def notify(
        self, title: str, body: str, actions: dict[str, str] | None = None
    ) -> str | None:
        return await self.notifier.notify(title, body, actions)

    async def open(self, target: str) -> None:
        await self.desktop.open(target)

    # ── Applications ──────────────────────────────────────────────────────────

    async def apps(self) -> list[AppInfo]:
        catalog = await self._catalog()
        shown = (entry.info() for entry in catalog.values() if not entry.no_display)
        return sorted(shown, key=lambda app: app.name.lower())

    async def launch(self, request: LaunchRequest) -> str:
        env = await self.session_env()
        catalog = await self._catalog(env)
        entry = apps.find(catalog, request.app)
        if entry is None:
            raise NotSupported(
                "launch",
                f"{request.app!r} is not an installed application",
                fix_hint="powerclock apps lists the installed ones",
            )
        if entry.terminal:
            raise NotSupported(
                "launch",
                f"{entry.name} runs in a terminal",
                fix_hint="use a run step instead, e.g. konsole -e …",
            )
        argv = apps.command(entry, list(request.args))
        program = (
            argv[0] if Path(argv[0]).is_absolute() else shutil.which(argv[0], path=env.get("PATH"))
        )
        if program is None:
            raise OSError(f"{argv[0]} (from {entry.path.name}) is not installed")
        detail, pid = await self._start(entry, [program, *argv[1:]], request)
        if request.window is not None:
            detail += await self._place(entry, pid, request)
        return detail

    async def _start(
        self, entry: apps.DesktopEntry, argv: list[str], request: LaunchRequest
    ) -> tuple[str, int | None]:
        name = session.unit_name(entry.id)
        try:
            await self.session.start(
                name,
                argv,
                description=f"{entry.name} (PowerClock)",
                workdir=self.home,
                stop_signal=request.stop_signal,
                keep_open=request.keep_open,
            )
        except DBusError as exc:
            if not exc.name.endswith(NO_MANAGER):
                raise OSError(f"systemd could not start {entry.name}: {exc}") from exc
            return await self._spawn(entry, argv, request), None
        state, pid = await self.session.settle(name)
        if state == "failed":
            raise OSError(f"{entry.name} failed to start (journalctl --user -u {name})")
        return f"{entry.name} ({name})", pid

    async def _spawn(
        self, entry: apps.DesktopEntry, argv: list[str], request: LaunchRequest
    ) -> str:
        """Without systemd's user manager: start it directly, with the display we can find."""
        if request.keep_open:
            raise NotSupported(
                "launch.keep_open", "keeping an app open needs systemd's user manager"
            )
        code = await self.commands.spawn(argv, self.desktop.graphical_env())
        if code not in (None, 0):
            raise OSError(f"{entry.name} ended with exit code {code}")
        return entry.name

    async def _place(
        self, entry: apps.DesktopEntry, pid: int | None, request: LaunchRequest
    ) -> str:
        assert request.window is not None
        if not await self.windows.available():
            return " · window placement needs KDE Plasma (KWin)"
        try:
            await self.windows.place(entry.window_ids(), pid, request.window, request.wait_window)
        except (DBusError, OSError) as exc:
            return f" · window not placed: {exc}"
        return " · window placement requested"

    async def close_app(self, app: str, grace: timedelta) -> int:
        entry = apps.find(await self._catalog(), app)
        app_id = entry.id if entry is not None else app.removesuffix(".desktop")
        try:
            units = await self.session.units(session.unit_pattern(app_id))
            for unit in units:
                await self.session.stop(unit)
        except DBusError as exc:
            raise NotSupported(
                "close_app",
                f"systemd's user manager is not reachable: {exc}",
                fix_hint="close it by its process name instead",
            ) from exc
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace.total_seconds() + session.STOP_TIMEOUT
        pending = list(units)
        while pending and loop.time() < deadline:
            await asyncio.sleep(0.2)
            states = [await self.session.unit_state(unit) for unit in pending]
            pending = [
                u
                for u, s in zip(pending, states, strict=True)
                if s not in (None, "inactive", "failed")
            ]
        return len(units)

    async def desktop_session(self) -> bool | None:
        try:
            if await self.session.graphical():
                return True
            env = await self.session.environment()
        except DBusError:
            env = {**self.env, **self.desktop.graphical_env()}
        return session.display_ready(env, self.runtime_dir)

    async def session_env(self) -> dict[str, str]:
        try:
            return await self.session.environment()
        except DBusError:
            return self.desktop.graphical_env()

    async def _catalog(self, env: Mapping[str, str] | None = None) -> dict[str, apps.DesktopEntry]:
        if env is None:
            env = await self.session_env()
        merged = {**self.env, **env}
        return await asyncio.to_thread(apps.entries, merged, self.root)

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        await self.logind.subscribe(callback)

    def inhibit_delay(self) -> AbstractAsyncContextManager[None]:
        return self.logind.inhibitor("shutdown:sleep", "Updating the wake-up alarm")

    async def wakeup_source(self) -> str | None:
        return self.host.wakeup_source()

    def timezone(self) -> tzinfo:
        return self.host.timezone(self.env)

    async def close(self) -> None:
        await self.windows.close()
        await self.idle.close()
        await self.session_bus.close()
        await self.system_bus.close()
