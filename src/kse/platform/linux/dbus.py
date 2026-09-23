"""Thin D-Bus layer over dbus-fast, behind a small protocol so tests can simulate the bus."""

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast._private.util import replace_idx_with_fds
from dbus_fast.aio import MessageBus

CALL_LIMIT = 30.0  # seconds; a polkit password prompt can take a while

SignalCallback = Callable[[list[Any]], Awaitable[None] | None]

DBUS = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
PROPERTIES = "org.freedesktop.DBus.Properties"


class DBusError(Exception):
    def __init__(self, name: str, message: str = "") -> None:
        super().__init__(f"{name}: {message}" if message else name)
        self.name = name
        self.message = message


class Bus(Protocol):
    async def call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[Any] = (),
    ) -> list[Any]:
        """Call a method and return the reply body. Raises DBusError."""
        ...

    async def subscribe(
        self, interface: str, member: str, callback: SignalCallback, *, path: str | None = None
    ) -> None:
        """Call `callback(body)` for every matching signal."""
        ...

    async def close(self) -> None: ...


async def get_property(bus: Bus, destination: str, path: str, interface: str, name: str) -> Any:
    [value] = await bus.call(destination, path, PROPERTIES, "Get", "ss", [interface, name])
    return value.value if isinstance(value, Variant) else value


async def has_owner(bus: Bus, name: str) -> bool:
    [owned] = await bus.call(DBUS, DBUS_PATH, DBUS, "NameHasOwner", "s", [name])
    return bool(owned)


async def list_names(bus: Bus) -> list[str]:
    [names] = await bus.call(DBUS, DBUS_PATH, DBUS, "ListNames")
    return list(names)


class DBusFastBus:
    """Lazily connected bus; reconnects (and re-subscribes) if the connection drops."""

    def __init__(self, bus_type: BusType) -> None:
        self._bus_type = bus_type
        self._bus: MessageBus | None = None
        self._lock = asyncio.Lock()
        self._subscriptions: list[tuple[str, Callable[[Message], None]]] = []
        self._tasks: set[asyncio.Future[Any]] = set()

    async def call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: Sequence[Any] = (),
    ) -> list[Any]:
        bus = await self._connection()
        message = Message(
            destination=destination,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=list(body),
        )
        async with asyncio.timeout(CALL_LIMIT):
            reply = await bus.call(message)
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else ""
            raise DBusError(reply.error_name or "unknown", str(detail))
        if reply.unix_fds:  # e.g. logind's Inhibit returns a file descriptor
            return replace_idx_with_fds(reply.signature, reply.body, reply.unix_fds)
        return list(reply.body)

    async def subscribe(
        self, interface: str, member: str, callback: SignalCallback, *, path: str | None = None
    ) -> None:
        rule = f"type='signal',interface='{interface}',member='{member}'"
        if path:
            rule += f",path='{path}'"

        def handler(message: Message) -> None:
            if (
                message.message_type != MessageType.SIGNAL
                or message.interface != interface
                or message.member != member
                or (path is not None and message.path != path)
            ):
                return
            result = callback(list(message.body))
            if inspect.isawaitable(result):
                task = asyncio.ensure_future(result)
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        bus = await self._connection()
        self._subscriptions.append((rule, handler))
        await _register(bus, rule, handler)

    async def close(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None

    async def _connection(self) -> MessageBus:
        async with self._lock:
            if self._bus is not None and self._bus.connected:
                return self._bus
            try:
                bus = await MessageBus(
                    bus_address=_address(self._bus_type),
                    bus_type=self._bus_type,
                    negotiate_unix_fd=True,
                ).connect()
            except Exception as exc:  # no socket, auth failure, bad address…
                raise DBusError("org.freedesktop.DBus.Error.NoServer", str(exc)) from exc
            for rule, handler in self._subscriptions:
                await _register(bus, rule, handler)
            self._bus = bus
            return bus


async def _register(bus: MessageBus, rule: str, handler: Callable[[Message], None]) -> None:
    await bus.call(
        Message(
            destination=DBUS,
            path=DBUS_PATH,
            interface=DBUS,
            member="AddMatch",
            signature="s",
            body=[rule],
        )
    )
    bus.add_message_handler(handler)


def _address(bus_type: BusType) -> str | None:
    """A systemd user service may lack DBUS_SESSION_BUS_ADDRESS; the socket is well known."""
    if bus_type == BusType.SESSION and not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        socket = Path(runtime) / "bus"
        if socket.exists():
            return f"unix:path={socket}"
    return None
