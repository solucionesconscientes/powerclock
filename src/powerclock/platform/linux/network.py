"""Wi-Fi network name through NetworkManager (system bus)."""

from powerclock.platform.base import NotSupported
from powerclock.platform.linux.dbus import Bus, DBusError, get_property

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
ACTIVE = "org.freedesktop.NetworkManager.Connection.Active"
ACCESS_POINT = "org.freedesktop.NetworkManager.AccessPoint"


async def wifi_ssid(bus: Bus) -> str | None:
    """SSID of the primary connection if it is Wi-Fi; None otherwise."""
    try:
        primary = await get_property(bus, NM, NM_PATH, NM, "PrimaryConnection")
        if primary == "/":
            return None
        if await get_property(bus, NM, primary, ACTIVE, "Type") != "802-11-wireless":
            return None
        access_point = await get_property(bus, NM, primary, ACTIVE, "SpecificObject")
        if access_point == "/":
            return None
        ssid = await get_property(bus, NM, access_point, ACCESS_POINT, "Ssid")
    except DBusError as exc:
        if exc.name.endswith(("ServiceUnknown", "NoServer", "NameHasNoOwner")):
            raise NotSupported("wifi", "NetworkManager is not running") from exc
        raise
    return bytes(ssid).decode(errors="replace")
