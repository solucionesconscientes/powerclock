"""Dry-run wrapper: reads reach the real backend; power and wake-alarm writes are only logged."""

import logging
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, tzinfo
from typing import Any

from powerclock.platform.base import (
    AppInfo,
    Capability,
    LaunchRequest,
    LogInMode,
    MediaCommand,
    PlatformBackend,
    PowerAction,
    PowerEventCallback,
    PowerMode,
    PowerProfile,
    Release,
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

    async def autologin_arm(self, alarm: datetime, mode: LogInMode) -> None:
        self._block("autologin_arm", alarm, mode)

    async def autologin_disarm(self) -> None:
        self._block("autologin_disarm")

    async def autologin_done(self) -> None:
        self._block("autologin_done")

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

    async def apps(self) -> list[AppInfo]:
        return await self.inner.apps()

    async def launch(self, request: LaunchRequest) -> str:
        return await self.inner.launch(request)

    async def close_app(self, app: str, grace: timedelta) -> int:
        return await self.inner.close_app(app, grace)

    async def desktop_session(self) -> bool | None:
        return await self.inner.desktop_session()

    async def devices(self) -> list[str]:
        return await self.inner.devices()

    async def session_env(self) -> dict[str, str]:
        return await self.inner.session_env()

    async def autologin_used(self) -> LogInMode | None:
        return await self.inner.autologin_used()

    # Sound, players and desktop settings are like `run`: they happen in a dry run too.

    async def control_media(
        self, command: MediaCommand, player: str | None, uri: str | None
    ) -> str:
        return await self.inner.control_media(command, player, uri)

    async def volume(self) -> tuple[float | None, bool | None]:
        return await self.inner.volume()

    async def set_volume(self, level: float | None = None, mute: bool | None = None) -> None:
        await self.inner.set_volume(level, mute)

    async def play_sound(self, sound: str) -> None:
        await self.inner.play_sound(sound)

    async def say(self, text: str, language: str | None = None) -> None:
        await self.inner.say(text, language)

    async def set_theme(self, theme: str) -> str:
        return await self.inner.set_theme(theme)

    async def set_wallpaper(self, path: str) -> None:
        await self.inner.set_wallpaper(path)

    async def set_brightness(self, percent: int) -> None:
        await self.inner.set_brightness(percent)

    async def set_power_profile(self, profile: PowerProfile) -> None:
        await self.inner.set_power_profile(profile)

    async def network(
        self, *, connect: str | None = None, disconnect: str | None = None, wifi: bool | None = None
    ) -> None:
        await self.inner.network(connect=connect, disconnect=disconnect, wifi=wifi)

    async def inhibit(
        self, *, screen: bool, notifications: bool, sleep: bool, reason: str
    ) -> Release:
        return await self.inner.inhibit(
            screen=screen, notifications=notifications, sleep=sleep, reason=reason
        )

    async def screenshot(self, path: str) -> None:
        await self.inner.screenshot(path)

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
