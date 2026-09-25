"""Simulated D-Bus, external commands and a KDE laptop, for the Linux backend tests."""

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from powerclock.platform.linux.dbus import DBUS, PROPERTIES, DBusError, SignalCallback

Key = tuple[str, str, str, str]
LOGIND = "org.freedesktop.login1"
MANAGER_PATH = "/org/freedesktop/login1"
MANAGER = "org.freedesktop.login1.Manager"
SESSION_PATH = "/org/freedesktop/login1/session/_33"
NM = "org.freedesktop.NetworkManager"
NOTIFICATIONS = "org.freedesktop.Notifications"


class FakeBus:
    def __init__(self) -> None:
        self.owners: set[str] = set()
        self.activatable: set[str] = set()  # started by D-Bus on the first call
        self.properties: dict[Key, Any] = {}
        self.methods: dict[Key, Any] = {}  # reply body, exception or callable(body)
        self.calls: list[tuple[str, str, str, str, list[Any]]] = []
        self.subscriptions: list[tuple[str, str, str | None, SignalCallback]] = []
        self.reachable = True
        self.closed = False

    def on(self, destination: str, path: str, interface: str, member: str, reply: Any = ()) -> None:
        self.owners.add(destination)
        self.methods[(destination, path, interface, member)] = reply

    def prop(self, destination: str, path: str, interface: str, name: str, value: Any) -> None:
        self.owners.add(destination)
        self.properties[(destination, path, interface, name)] = value

    def only_activatable(self, name: str) -> None:
        """Like org.kde.Shutdown: not running until something calls it."""
        self.owners.discard(name)
        self.activatable.add(name)

    def called(self, member: str) -> list[list[Any]]:
        return [body for *_, name, body in self.calls if name == member]

    async def call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[Any] = (),
    ) -> list[Any]:
        if not self.reachable:
            raise DBusError("org.freedesktop.DBus.Error.NoServer", "bus not reachable")
        args = list(body)
        if destination == DBUS and member == "NameHasOwner":
            return [args[0] in self.owners]
        if destination == DBUS and member == "ListNames":
            return [sorted(self.owners)]
        if destination == DBUS and member == "ListActivatableNames":
            return [sorted(self.activatable)]
        if destination in self.activatable:
            self.owners.add(destination)  # D-Bus activation
        self.calls.append((destination, path, interface, member, args))
        if interface == PROPERTIES and member == "Get":
            key = (destination, path, args[0], args[1])
            if destination not in self.owners:
                raise DBusError("org.freedesktop.DBus.Error.ServiceUnknown", destination)
            if key not in self.properties:
                raise DBusError("org.freedesktop.DBus.Error.UnknownProperty", str(key))
            return [self.properties[key]]
        reply = self.methods.get((destination, path, interface, member))
        if reply is None:
            if destination not in self.owners:
                raise DBusError("org.freedesktop.DBus.Error.ServiceUnknown", destination)
            raise DBusError("org.freedesktop.DBus.Error.UnknownMethod", member)
        if callable(reply):
            reply = reply(args)
        if isinstance(reply, Exception):
            raise reply
        return list(reply)

    async def subscribe(
        self, interface: str, member: str, callback: SignalCallback, *, path: str | None = None
    ) -> None:
        self.subscriptions.append((interface, member, path, callback))

    async def emit(self, interface: str, member: str, body: list[Any]) -> None:
        for sub_interface, sub_member, _, callback in list(self.subscriptions):
            if (sub_interface, sub_member) == (interface, member):
                result = callback(body)
                if inspect.isawaitable(result):
                    await result

    async def close(self) -> None:
        self.closed = True


class FakeCommands:
    def __init__(
        self,
        available: Sequence[str] = (),
        results: Mapping[str, tuple[int, str]] | None = None,
        spawn_result: int | None = None,
    ) -> None:
        self.available = set(available)
        self.results = dict(results or {})
        self.spawn_result = spawn_result
        self.ran: list[tuple[list[str], dict[str, str]]] = []

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.available else None

    async def run(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None, limit: float | None = None
    ) -> tuple[int, str]:
        self.ran.append((list(argv), dict(env or {})))
        return self.results.get(argv[0], (0, ""))

    async def spawn(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int | None:
        self.ran.append((list(argv), dict(env or {})))
        return self.spawn_result


def kde_laptop(uid: int = 1000) -> tuple[FakeBus, FakeBus]:
    """(system bus, session bus) of a KDE Plasma Wayland laptop like the development one."""
    system, session = FakeBus(), FakeBus()
    answers = {
        "CanPowerOff": "yes",
        "CanReboot": "yes",
        "CanSuspend": "yes",
        "CanHibernate": "na",
        "CanHybridSleep": "na",
    }
    for query, answer in answers.items():
        system.on(LOGIND, MANAGER_PATH, MANAGER, query, [answer])
    for method in ("PowerOff", "Reboot", "Suspend", "Hibernate", "HybridSleep"):
        system.on(LOGIND, MANAGER_PATH, MANAGER, method)
    system.prop(
        LOGIND,
        f"{MANAGER_PATH}/user/_{uid}",
        "org.freedesktop.login1.User",
        "Display",
        ["3", SESSION_PATH],
    )
    for name, value in {"Type": "wayland", "Desktop": "KDE"}.items():
        system.prop(LOGIND, SESSION_PATH, "org.freedesktop.login1.Session", name, value)
    for member in ("Lock", "Terminate"):
        system.on(LOGIND, SESSION_PATH, "org.freedesktop.login1.Session", member)
    for name, value in {
        "IdleHint": False,
        "IdleSinceHint": 0,
        "InhibitDelayMaxUSec": 30_000_000,
    }.items():
        system.prop(LOGIND, MANAGER_PATH, MANAGER, name, value)
    active = "/org/freedesktop/NetworkManager/ActiveConnection/7"
    access_point = "/org/freedesktop/NetworkManager/AccessPoint/1"
    system.prop(NM, "/org/freedesktop/NetworkManager", NM, "PrimaryConnection", active)
    system.prop(NM, active, f"{NM}.Connection.Active", "Type", "802-11-wireless")
    system.prop(NM, active, f"{NM}.Connection.Active", "SpecificObject", access_point)
    system.prop(NM, access_point, f"{NM}.AccessPoint", "Ssid", b"Casa")

    for method in ("logout", "logoutAndShutdown", "logoutAndReboot"):
        session.on("org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown", method)
    notifications = "/org/freedesktop/Notifications"
    session.on(
        NOTIFICATIONS,
        notifications,
        NOTIFICATIONS,
        "GetServerInformation",
        ["Plasma", "KDE", "6.6.6", "1.2"],
    )
    session.on(
        NOTIFICATIONS, notifications, NOTIFICATIONS, "GetCapabilities", [["body", "actions"]]
    )
    session.on(NOTIFICATIONS, notifications, NOTIFICATIONS, "Notify", [42])
    session.on(NOTIFICATIONS, notifications, NOTIFICATIONS, "CloseNotification")
    player = "org.mpris.MediaPlayer2.smplayer"
    session.prop(
        player,
        "/org/mpris/MediaPlayer2",
        "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
        "Playing",
    )
    return system, session


Reply = Callable[[list[Any]], Any]
