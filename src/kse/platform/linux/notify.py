"""Desktop notifications (org.freedesktop.Notifications), with buttons."""

import asyncio
import contextlib
from typing import Any

from dbus_fast import Variant

from kse.platform.base import NotSupported
from kse.platform.linux.dbus import Bus, DBusError

NOTIFICATIONS = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"


class Notifier:
    def __init__(self, session_bus: Bus) -> None:
        self._bus = session_bus
        self._waiting: dict[int, asyncio.Future[str | None]] = {}
        self._subscribed = False

    async def server(self) -> tuple[str, list[str]]:
        """(name and version of the notification server, its capabilities)."""
        name, vendor, version, _ = await self._bus.call(
            NOTIFICATIONS, PATH, NOTIFICATIONS, "GetServerInformation"
        )
        [capabilities] = await self._bus.call(NOTIFICATIONS, PATH, NOTIFICATIONS, "GetCapabilities")
        return f"{name} {version} ({vendor})", list(capabilities)

    async def notify(
        self, title: str, body: str, actions: dict[str, str] | None = None
    ) -> str | None:
        flat = [item for key, label in (actions or {}).items() for item in (key, label)]
        hints: dict[str, Variant] = {"urgency": Variant("y", 2)} if actions else {}
        expire = 0 if actions else -1  # 0: stays until the user answers
        if actions:
            await self._subscribe()
        try:
            [notification_id] = await self._bus.call(
                NOTIFICATIONS,
                PATH,
                NOTIFICATIONS,
                "Notify",
                "susssasa{sv}i",
                ["KSE", 0, "system-shutdown" if actions else "", title, body, flat, hints, expire],
            )
        except DBusError as exc:
            raise NotSupported("notify", f"no notification server: {exc}") from exc
        if not actions:
            return None
        answer: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._waiting[notification_id] = answer
        try:
            return await answer
        finally:
            self._waiting.pop(notification_id, None)
            if answer.cancelled() or not answer.done():  # the caller gave up: remove it
                with contextlib.suppress(DBusError):
                    await self._bus.call(
                        NOTIFICATIONS,
                        PATH,
                        NOTIFICATIONS,
                        "CloseNotification",
                        "u",
                        [notification_id],
                    )

    async def _subscribe(self) -> None:
        if self._subscribed:
            return
        await self._bus.subscribe(NOTIFICATIONS, "ActionInvoked", self._on_action, path=PATH)
        await self._bus.subscribe(NOTIFICATIONS, "NotificationClosed", self._on_closed, path=PATH)
        self._subscribed = True

    def _on_action(self, body: list[Any]) -> None:
        self._resolve(body[0], str(body[1]))

    def _on_closed(self, body: list[Any]) -> None:
        self._resolve(body[0], None)

    def _resolve(self, notification_id: int, key: str | None) -> None:
        future = self._waiting.get(notification_id)
        if future is not None and not future.done():
            future.set_result(key)
