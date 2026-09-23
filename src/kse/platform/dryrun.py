"""Dry-run wrapper: reads reach the real backend; power and wake-alarm writes are only logged."""

import logging
from contextlib import AbstractAsyncContextManager
from datetime import datetime, tzinfo
from typing import Any

from kse.platform.base import (
    Capability,
    PlatformBackend,
    PowerAction,
    PowerEventCallback,
    PowerMode,
)

log = logging.getLogger(__name__)


class DryRunPlatform(PlatformBackend):
    def __init__(self, inner: PlatformBackend) -> None:
        self.inner = inner
        self.name = f"{inner.name} (dry-run)"
        self.blocked: list[tuple[str, tuple[Any, ...]]] = []

    # Writes that change the machine: logged, never executed.

    async def power(self, action: PowerAction, mode: PowerMode) -> None:
        self._block("power", action, mode)

    async def wake_set(self, when: datetime) -> None:
        self._block("wake_set", when)

    async def wake_clear(self) -> None:
        self._block("wake_clear")

    # Everything else goes to the real backend.

    async def capabilities(self) -> list[Capability]:
        return await self.inner.capabilities()

    async def wake_get(self) -> datetime | None:
        return await self.inner.wake_get()

    async def idle_seconds(self) -> float | None:
        return await self.inner.idle_seconds()

    async def media_playing(self) -> bool | None:
        return await self.inner.media_playing()

    async def wifi_ssid(self) -> str | None:
        return await self.inner.wifi_ssid()

    async def notify(
        self, title: str, body: str, actions: dict[str, str] | None = None
    ) -> str | None:
        return await self.inner.notify(title, body, actions)

    async def open(self, target: str) -> None:
        await self.inner.open(target)

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        await self.inner.subscribe_power_events(callback)

    def inhibit_delay(self) -> AbstractAsyncContextManager[None]:
        return self.inner.inhibit_delay()

    async def wakeup_source(self) -> str | None:
        return await self.inner.wakeup_source()

    def timezone(self) -> tzinfo:
        return self.inner.timezone()

    async def close(self) -> None:
        await self.inner.close()

    def _block(self, method: str, *args: Any) -> None:
        self.blocked.append((method, args))
        log.warning("dry run: %s%r not executed", method, args)
