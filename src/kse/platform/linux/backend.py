"""Linux backend: logind for power, the desktop's session manager for graceful logouts."""

import os
import pwd
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from datetime import tzinfo
from pathlib import Path

from dbus_fast import BusType

from kse.platform.base import (
    Capability,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerEventCallback,
    PowerMode,
)
from kse.platform.linux.commands import Commands, SystemCommands
from kse.platform.linux.dbus import Bus, DBusFastBus
from kse.platform.linux.desktop import Desktop
from kse.platform.linux.host import Host
from kse.platform.linux.idle import IdleProbe
from kse.platform.linux.logind import ALLOWED, METHODS, Logind
from kse.platform.linux.network import wifi_ssid
from kse.platform.linux.notify import Notifier


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
        self.host = Host(root)
        self.logind = Logind(self.system_bus, self.uid)
        self.desktop = Desktop(self.session_bus, self.commands, self.env)
        self.idle = IdleProbe(self.session_bus, self.logind, self.commands, self.env)
        self.notifier = Notifier(self.session_bus)

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

    async def capabilities(self) -> list[Capability]:
        from kse.platform.linux.capabilities import collect

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

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        await self.logind.subscribe(callback)

    def inhibit_delay(self) -> AbstractAsyncContextManager[None]:
        return self.logind.inhibitor("shutdown:sleep", "Updating the wake-up alarm")

    def timezone(self) -> tzinfo:
        return self.host.timezone(self.env)

    async def close(self) -> None:
        await self.idle.close()
        await self.session_bus.close()
        await self.system_bus.close()
