"""systemd-logind on the system bus: power actions, sessions, inhibitors and power events."""

import contextlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from kse.platform.base import NotSupported, PowerAction, PowerEvent, PowerEventCallback
from kse.platform.linux.dbus import Bus, get_property

LOGIND = "org.freedesktop.login1"
MANAGER_PATH = "/org/freedesktop/login1"
MANAGER = "org.freedesktop.login1.Manager"
SESSION = "org.freedesktop.login1.Session"
USER = "org.freedesktop.login1.User"

# PowerAction → (Can* query, method)
METHODS = {
    PowerAction.SHUTDOWN: ("CanPowerOff", "PowerOff"),
    PowerAction.REBOOT: ("CanReboot", "Reboot"),
    PowerAction.SUSPEND: ("CanSuspend", "Suspend"),
    PowerAction.HIBERNATE: ("CanHibernate", "Hibernate"),
    PowerAction.HYBRID_SLEEP: ("CanHybridSleep", "HybridSleep"),
}
ALLOWED = ("yes", "challenge")  # challenge: polkit will ask for a password


class Logind:
    def __init__(self, bus: Bus, uid: int | None = None) -> None:
        self._bus = bus
        self._uid = os.getuid() if uid is None else uid

    async def can(self, action: PowerAction) -> str:
        """logind's answer: "yes", "no", "challenge" or "na" (not available)."""
        query, _ = METHODS[action]
        [answer] = await self._bus.call(LOGIND, MANAGER_PATH, MANAGER, query)
        return str(answer)

    async def power(self, action: PowerAction) -> None:
        query, method = METHODS[action]
        answer = await self.can(action)
        if answer not in ALLOWED:
            raise NotSupported(f"power.{action}", f"logind answers {answer!r} to {query}")
        await self._bus.call(LOGIND, MANAGER_PATH, MANAGER, method, "b", [True])

    async def display(self) -> tuple[str, str]:
        """(id, object path) of the user's graphical session; works from a user service."""
        user_path = f"{MANAGER_PATH}/user/_{self._uid}"
        session_id, path = await get_property(self._bus, LOGIND, user_path, USER, "Display")
        if not path or path == "/":
            raise NotSupported("session", "there is no graphical session")
        return str(session_id), str(path)

    async def display_session(self) -> str:
        _, path = await self.display()
        return path

    async def session_property(self, name: str) -> Any:
        session = await self.display_session()
        return await get_property(self._bus, LOGIND, session, SESSION, name)

    async def lock(self) -> None:
        await self._bus.call(LOGIND, await self.display_session(), SESSION, "Lock")

    async def terminate_session(self) -> None:
        """Forced logout: the session's processes are terminated."""
        await self._bus.call(LOGIND, await self.display_session(), SESSION, "Terminate")

    async def idle_since(self) -> datetime | None:
        """When the session went idle according to its desktop, None if it is not idle."""
        if not await get_property(self._bus, LOGIND, MANAGER_PATH, MANAGER, "IdleHint"):
            return None
        micros = await get_property(self._bus, LOGIND, MANAGER_PATH, MANAGER, "IdleSinceHint")
        return datetime.fromtimestamp(micros / 1_000_000, UTC)

    async def inhibit_delay_max(self) -> float:
        micros = await get_property(self._bus, LOGIND, MANAGER_PATH, MANAGER, "InhibitDelayMaxUSec")
        return micros / 1_000_000

    @contextlib.asynccontextmanager
    async def inhibitor(self, what: str, why: str, mode: str = "delay") -> AsyncIterator[None]:
        """Hold a logind inhibitor lock; releasing it is closing its file descriptor."""
        [fd] = await self._bus.call(
            LOGIND, MANAGER_PATH, MANAGER, "Inhibit", "ssss", [what, "kse", why, mode]
        )
        try:
            yield
        finally:
            with contextlib.suppress(OSError, TypeError):
                os.close(fd)

    async def subscribe(self, callback: PowerEventCallback) -> None:
        async def on_sleep(body: list[Any]) -> None:
            await callback(PowerEvent.BEFORE_SLEEP if body[0] else PowerEvent.AFTER_RESUME)

        async def on_shutdown(body: list[Any]) -> None:
            if body[0]:
                await callback(PowerEvent.BEFORE_SHUTDOWN)

        await self._bus.subscribe(MANAGER, "PrepareForSleep", on_sleep, path=MANAGER_PATH)
        await self._bus.subscribe(MANAGER, "PrepareForShutdown", on_shutdown, path=MANAGER_PATH)
