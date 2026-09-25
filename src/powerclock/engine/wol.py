"""Wake-on-LAN: the "magic packet" (6 bytes 0xFF, then the MAC address 16 times) sent by
UDP broadcast. Plain sockets, the same on every system."""

import asyncio
import socket
from collections.abc import Awaitable, Callable

REPEAT = 3  # UDP may lose a packet: send it a few times

Sender = Callable[[bytes, str, int], Awaitable[None]]


def magic_packet(mac: str) -> bytes:
    digits = "".join(ch for ch in mac if ch not in ":-")
    address = bytes.fromhex(digits)
    if len(address) != 6:
        raise ValueError(f"not a MAC address: {mac}")
    return b"\xff" * 6 + address * 16


async def send(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    await _udp(magic_packet(mac), broadcast, port)


async def _udp(packet: bytes, host: str, port: int) -> None:
    await asyncio.to_thread(_send_blocking, packet, host, port)


def _send_blocking(packet: bytes, host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(REPEAT):
            sock.sendto(packet, (host, port))
