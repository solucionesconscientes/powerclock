"""OS abstraction: every access to the operating system goes through PlatformBackend.

Generic sensors (CPU, network, processes, battery, users) live in ``kse.sensors``
and use psutil; only what differs between operating systems belongs here.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, tzinfo
from enum import StrEnum
from typing import NoReturn

from pydantic import BaseModel, ConfigDict


class PowerAction(StrEnum):
    SHUTDOWN = "shutdown"
    REBOOT = "reboot"
    SUSPEND = "suspend"
    HIBERNATE = "hibernate"
    HYBRID_SLEEP = "hybrid_sleep"
    LOCK = "lock"
    LOGOUT = "logout"
    SCREEN_OFF = "screen_off"


class PowerMode(StrEnum):
    GRACEFUL = "graceful"  # let applications ask to save their work
    FORCE = "force"  # never used unless explicitly requested


class PowerEvent(StrEnum):
    BEFORE_SLEEP = "before_sleep"
    AFTER_RESUME = "after_resume"
    BEFORE_SHUTDOWN = "before_shutdown"


PowerEventCallback = Callable[[PowerEvent], Awaitable[None]]


class NotSupported(Exception):
    """Raised when the current platform cannot do something. Never fail silently."""

    def __init__(self, feature: str, detail: str, fix_hint: str | None = None) -> None:
        super().__init__(f"{feature}: {detail}")
        self.feature = feature
        self.detail = detail
        self.fix_hint = fix_hint


class Capability(BaseModel):
    """One line of the `kse doctor` report."""

    model_config = ConfigDict(frozen=True)

    id: str
    supported: bool
    detail: str
    fix_hint: str | None = None


class PlatformBackend(ABC):
    """Everything kse needs from the OS.

    Only `power` and `capabilities` are mandatory; any other method a backend
    does not override raises NotSupported. Datetimes are always timezone-aware.
    """

    name: str

    @abstractmethod
    async def power(self, action: PowerAction, mode: PowerMode) -> None: ...

    @abstractmethod
    async def capabilities(self) -> list[Capability]: ...

    async def wake_set(self, when: datetime) -> None:
        """Program the (single) hardware wake alarm."""
        self._unsupported("wake_set")

    async def wake_clear(self) -> None:
        self._unsupported("wake_clear")

    async def wake_get(self) -> datetime | None:
        """Return the programmed wake alarm, or None if there is none."""
        self._unsupported("wake_get")

    async def idle_seconds(self) -> float | None:
        """Seconds since the last user input, or None if it cannot be known right now."""
        self._unsupported("idle_seconds")

    async def media_playing(self) -> bool | None:
        self._unsupported("media_playing")

    async def wifi_ssid(self) -> str | None:
        self._unsupported("wifi_ssid")

    async def notify(
        self, title: str, body: str, actions: dict[str, str] | None = None
    ) -> str | None:
        """Show a desktop notification; `actions` maps each button key to its label.

        Without `actions` it returns None right away. With `actions` it waits until
        the user picks one (returning its key) or the notification closes (None),
        so callers run it as a task and cancel it when it is no longer needed.
        """
        self._unsupported("notify")

    async def open(self, target: str) -> None:
        """Open a file or URL with the user's default application."""
        self._unsupported("open")

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        self._unsupported("subscribe_power_events")

    def inhibit_delay(self) -> AbstractAsyncContextManager[None]:
        """Delay sleep/shutdown while the context is held (e.g. to rewrite the wake alarm)."""
        self._unsupported("inhibit_delay")

    def timezone(self) -> tzinfo:
        """The system's time zone (IANA when possible), for rules without `timezone`."""
        self._unsupported("timezone")

    async def close(self) -> None:
        """Release connections (D-Bus, Wayland…). Safe to call more than once."""
        return

    def _unsupported(self, feature: str) -> NoReturn:
        raise NotSupported(feature, f"not supported by the {self.name!r} backend")
