"""Connected devices, by name: USB products (/sys/bus/usb), disk and stick labels
(/dev/disk/by-label) and connected Bluetooth devices (BlueZ over D-Bus)."""

import contextlib
from pathlib import Path

from powerclock.platform.linux.dbus import Bus, DBusError

BLUEZ = "org.bluez"
DEVICE = "org.bluez.Device1"


def usb_and_labels(root: Path = Path("/")) -> list[str]:
    names: list[str] = []
    for device in sorted((root / "sys/bus/usb/devices").glob("*")):
        product = _read(device / "product")
        if product:
            maker = _read(device / "manufacturer")
            names.append(f"{maker} {product}".strip() if maker else product)
    labels = root / "dev/disk/by-label"
    if labels.is_dir():
        names += [_unescape(link.name) for link in sorted(labels.iterdir())]
    return names


async def bluetooth(bus: Bus) -> list[str]:
    """Names of the connected Bluetooth devices (none if BlueZ is not there)."""
    with contextlib.suppress(DBusError):
        [objects] = await bus.call(
            BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"
        )
        found = []
        for interfaces in objects.values():
            device = interfaces.get(DEVICE)
            if device and _value(device.get("Connected")):
                found.append(str(_value(device.get("Alias")) or _value(device.get("Name")) or ""))
        return [name for name in found if name]
    return []


def _value(item: object) -> object:
    return getattr(item, "value", item)


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def _unescape(name: str) -> str:
    """udev writes spaces and other bytes in labels as \\x20."""
    out, index = bytearray(), 0
    raw = name.encode()
    while index < len(raw):
        if raw[index : index + 2] == b"\\x" and index + 4 <= len(raw):
            with contextlib.suppress(ValueError):
                out.append(int(raw[index + 2 : index + 4], 16))
                index += 4
                continue
        out.append(raw[index])
        index += 1
    return out.decode(errors="replace")
