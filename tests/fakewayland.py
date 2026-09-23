"""A tiny fake Wayland compositor speaking the real wire protocol, for the idle tests."""

import asyncio
import struct
from pathlib import Path

from kse.platform.linux.wayland import message, read_string, string


class FakeCompositor:
    def __init__(self, socket: Path, globals_: dict[str, int]) -> None:
        self.socket = socket
        self.globals = globals_  # interface → version
        self.binds: list[tuple[str, int, int]] = []  # (interface, version, new id)
        self.notification: tuple[int, int, int, int] | None = None  # (opcode, id, ms, seat)
        self.requested = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> "FakeCompositor":
        self._server = await asyncio.start_unix_server(self._client, path=str(self.socket))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def idled(self) -> None:
        await self._event(0)

    async def resumed(self) -> None:
        await self._event(1)

    async def protocol_error(self, text: str) -> None:
        assert self._writer is not None
        self._writer.write(message(1, 0, struct.pack("=II", 1, 3) + string(text)))
        await self._writer.drain()

    async def disconnect(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    async def _event(self, opcode: int) -> None:
        assert self._writer is not None
        assert self.notification is not None
        self._writer.write(message(self.notification[1], opcode))
        await self._writer.drain()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        names = {index: name for index, name in enumerate(self.globals, start=1)}
        try:
            while True:
                object_id, word = struct.unpack("=II", await reader.readexactly(8))
                body = await reader.readexactly((word >> 16) - 8)
                opcode = word & 0xFFFF
                if object_id == 1 and opcode == 1:  # get_registry
                    (registry,) = struct.unpack("=I", body)
                    for index, interface in names.items():
                        payload = (
                            struct.pack("=I", index)
                            + string(interface)
                            + struct.pack("=I", self.globals[interface])
                        )
                        writer.write(message(registry, 0, payload))
                elif object_id == 1 and opcode == 0:  # sync
                    (callback,) = struct.unpack("=I", body)
                    writer.write(message(callback, 0, struct.pack("=I", 1)))
                elif object_id == 2 and opcode == 0:  # registry.bind
                    (name,) = struct.unpack_from("=I", body)
                    interface, offset = read_string(body, 4)
                    version, new_id = struct.unpack_from("=II", body, offset)
                    assert names[name] == interface
                    self.binds.append((interface, version, new_id))
                elif object_id == 5 and opcode in (1, 2):  # get_(input_)idle_notification
                    new_id, timeout_ms, seat = struct.unpack("=III", body)
                    self.notification = (opcode, new_id, timeout_ms, seat)
                    self.requested.set()
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
