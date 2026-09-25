"""In-memory backend that records every call. Used by all tests; never touches the OS."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from powerclock.platform.base import (
    AppInfo,
    Capability,
    LaunchRequest,
    LogInMode,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerEvent,
    PowerEventCallback,
    PowerMode,
)


@dataclass(frozen=True)
class FakeCall:
    method: str
    args: tuple[Any, ...] = ()


class FakePlatform(PlatformBackend):
    name = "fake"

    def __init__(
        self,
        *,
        idle: float | None = 0.0,
        media: bool | None = False,
        ssid: str | None = None,
        notify_response: str | None = None,
        timezone: tzinfo = UTC,
    ) -> None:
        # Simulated state; tests change these attributes freely.
        self.idle = idle
        self.media = media
        self.ssid = ssid
        self.notify_response = notify_response
        self.tz = timezone
        self.wakeup: str | None = None  # what "woke the machine" last
        self.wake: datetime | None = None
        self.inhibited = False
        self.desktop: bool | None = True  # a desktop session is up
        self.session_vars: dict[str, str] = {}
        self.installed: list[AppInfo] = [
            AppInfo(id="org.kde.okular", name="Okular", icon="okular"),
            AppInfo(id="vlc", name="VLC media player", icon="vlc"),
            AppInfo(
                id="one.ablaze.floorp",
                name="Floorp",
                icon="one.ablaze.floorp",
                flatpak="one.ablaze.floorp",
            ),
        ]
        self.opened: dict[str, int] = {}  # app → instances PowerClock opened
        self.login: tuple[datetime, LogInMode] | None = None  # the armed log-in ticket
        self.logged_in: LogInMode | None = None  # this boot logged in by itself
        self.calls: list[FakeCall] = []
        self._callbacks: list[PowerEventCallback] = []

    def calls_to(self, method: str) -> list[FakeCall]:
        return [call for call in self.calls if call.method == method]

    async def emit(self, event: PowerEvent) -> None:
        """Simulate a power event (before_sleep, after_resume, before_shutdown)."""
        for callback in list(self._callbacks):
            await callback(event)

    async def power(self, action: PowerAction, mode: PowerMode) -> None:
        self._record("power", action, mode)

    async def capabilities(self) -> list[Capability]:
        self._record("capabilities")
        features = [f"power.{action}" for action in PowerAction]
        features += ["wake", "idle", "media", "wifi", "notify", "open", "power_events", "inhibit"]
        return [Capability(id=feature, supported=True, detail="simulated") for feature in features]

    async def wake_set(self, when: datetime) -> None:
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("wake_set needs a timezone-aware datetime")
        self._record("wake_set", when)
        self.wake = when

    async def wake_clear(self) -> None:
        self._record("wake_clear")
        self.wake = None

    async def wake_get(self) -> datetime | None:
        self._record("wake_get")
        return self.wake

    async def idle_seconds(self) -> float | None:
        self._record("idle_seconds")
        return self.idle

    async def media_playing(self) -> bool | None:
        self._record("media_playing")
        return self.media

    async def wifi_ssid(self) -> str | None:
        self._record("wifi_ssid")
        return self.ssid

    async def notify(
        self, title: str, body: str, actions: dict[str, str] | None = None
    ) -> str | None:
        self._record("notify", title, body, tuple(actions or ()))
        return self.notify_response if actions else None

    async def open(self, target: str) -> None:
        self._record("open", target)

    async def apps(self) -> list[AppInfo]:
        self._record("apps")
        return list(self.installed)

    async def launch(self, request: LaunchRequest) -> str:
        self._record("launch", request)
        app = next((a for a in self.installed if request.app in (a.id, a.flatpak)), None)
        if app is None:
            raise NotSupported("launch", f"{request.app!r} is not an installed application")
        self.opened[app.id] = self.opened.get(app.id, 0) + 1
        return f"{app.name} (simulated)"

    async def close_app(self, app: str, grace: timedelta) -> int:
        self._record("close_app", app, grace)
        return self.opened.pop(app, 0)

    async def desktop_session(self) -> bool | None:
        self._record("desktop_session")
        return self.desktop

    async def session_env(self) -> dict[str, str]:
        return dict(self.session_vars)

    async def autologin_arm(self, alarm: datetime, mode: LogInMode) -> None:
        self._record("autologin_arm", alarm, mode)
        self.login = (alarm, mode)

    async def autologin_disarm(self) -> None:
        self._record("autologin_disarm")
        self.login = None

    async def autologin_used(self) -> LogInMode | None:
        return self.logged_in

    async def autologin_done(self) -> None:
        self._record("autologin_done")
        self.logged_in = None

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        self._record("subscribe_power_events")
        self._callbacks.append(callback)

    @asynccontextmanager
    async def inhibit_delay(self) -> AsyncIterator[None]:
        self._record("inhibit_delay")
        self.inhibited = True
        try:
            yield
        finally:
            self.inhibited = False

    async def wakeup_source(self) -> str | None:
        self._record("wakeup_source")
        return self.wakeup

    def timezone(self) -> tzinfo:
        return self.tz

    def _record(self, method: str, *args: Any) -> None:
        self.calls.append(FakeCall(method, args))
