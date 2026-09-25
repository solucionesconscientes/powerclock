"""OS abstraction: every access to the operating system goes through PlatformBackend.

Generic sensors (CPU, network, processes, battery, users) live in ``powerclock.sensors``
and use psutil; only what differs between operating systems belongs here.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field


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


class WindowPlacement(BaseModel):
    """Where and how the window of an opened application goes (part of the `launch` step)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    screen: int | None = Field(default=None, ge=1)  # 1 = the first screen; None: any
    desktop: int | None = Field(default=None, ge=1)  # virtual desktop; None: the current one
    state: Literal["normal", "maximized", "fullscreen", "minimized"] = "normal"
    above: bool = False  # keep it above the other windows


StopSignal = Literal["TERM", "INT", "HUP"]
LogInMode = Literal["locked", "unlocked"]  # how the screen is left after logging in by itself


@dataclass(frozen=True)
class AppInfo:
    """An installed application, as the desktop's menu knows it."""

    id: str  # desktop entry id: "org.kde.okular", "one.ablaze.floorp", "google-chrome"
    name: str
    names: dict[str, str] = field(default_factory=dict)  # translations: {"es": "…"}
    icon: str | None = None
    flatpak: str | None = None  # the Flatpak application id, when it is one
    categories: tuple[str, ...] = ()
    terminal: bool = False


@dataclass(frozen=True)
class LaunchRequest:
    """Open an installed application in the user's desktop session."""

    app: str
    args: tuple[str, ...] = ()
    window: WindowPlacement | None = None
    keep_open: bool = False  # open it again if it closes (a few times per hour)
    stop_signal: StopSignal = "TERM"  # what closing it sends (some recorders save on INT)
    wait_window: timedelta = timedelta(seconds=30)  # how long to look for its window


class Capability(BaseModel):
    """One line of the `powerclock doctor` report."""

    model_config = ConfigDict(frozen=True)

    id: str
    supported: bool
    detail: str
    fix_hint: str | None = None


class PlatformBackend(ABC):
    """Everything powerclock needs from the OS.

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

    async def apps(self) -> list[AppInfo]:
        """The applications installed for this user (the desktop's menu, Flatpak, Snap…)."""
        self._unsupported("apps")

    async def launch(self, request: LaunchRequest) -> str:
        """Open an application in the desktop session; returns what was started (for the
        history). Raises NotSupported without a desktop session."""
        self._unsupported("launch")

    async def close_app(self, app: str, grace: timedelta) -> int:
        """Close the instances of `app` that PowerClock opened (killing them after `grace`);
        returns how many."""
        self._unsupported("close_app")

    async def desktop_session(self) -> bool | None:
        """Whether a desktop session is up and apps can be opened in it (None: unknown)."""
        self._unsupported("desktop_session")

    async def autologin_arm(self, alarm: datetime, mode: LogInMode) -> None:
        """Log the user in once if `alarm` powers the computer on (a one-time ticket)."""
        self._unsupported("autologin")

    async def autologin_disarm(self) -> None:
        self._unsupported("autologin")

    async def autologin_used(self) -> LogInMode | None:
        """How the screen should be left if this boot logged the user in by itself (and
        that was not handled yet); None if it did not."""
        self._unsupported("autologin")

    async def autologin_done(self) -> None:
        """Forget this boot's automatic log-in (nothing is left for another one)."""
        self._unsupported("autologin")

    async def session_env(self) -> dict[str, str]:
        """Variables that programs need to reach the desktop session (display, bus…), for
        commands started by a service that began before the session."""
        self._unsupported("session_env")

    async def subscribe_power_events(self, callback: PowerEventCallback) -> None:
        self._unsupported("subscribe_power_events")

    def inhibit_delay(self) -> AbstractAsyncContextManager[None]:
        """Delay sleep/shutdown while the context is held (e.g. to rewrite the wake alarm)."""
        self._unsupported("inhibit_delay")

    async def wakeup_source(self) -> str | None:
        """What the OS says woke the machine last (e.g. "IRQ 51: touchpad"), if it says.

        It may be stale: compare the value before and after a suspend.
        """
        self._unsupported("wakeup_source")

    def timezone(self) -> tzinfo:
        """The system's time zone (IANA when possible), for rules without `timezone`."""
        self._unsupported("timezone")

    async def close(self) -> None:
        """Release connections (D-Bus, Wayland…). Safe to call more than once."""
        return

    def _unsupported(self, feature: str) -> NoReturn:
        raise NotSupported(feature, f"not supported by the {self.name!r} backend")
