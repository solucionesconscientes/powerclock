"""Connected devices by name: USB products, disk labels and Bluetooth."""

from pathlib import Path

from dbus_fast import Variant

from fakebus import FakeBus
from powerclock.platform.linux import devices


def test_usb_products_and_disk_labels(tmp_path: Path) -> None:
    usb = tmp_path / "sys/bus/usb/devices"
    for name, maker, product in [("1-1", "SanDisk", "Cruzer Blade"), ("1-2", "", "USB Hub")]:
        (usb / name).mkdir(parents=True)
        (usb / name / "product").write_text(product + "\n")
        if maker:
            (usb / name / "manufacturer").write_text(maker + "\n")
    (usb / "usb1").mkdir()  # a root hub without a product file
    labels = tmp_path / "dev/disk/by-label"
    labels.mkdir(parents=True)
    (labels / "COPIAS\\x20DE\\x20SEGURIDAD").symlink_to("../../sdb1")
    assert devices.usb_and_labels(tmp_path) == [
        "SanDisk Cruzer Blade",
        "USB Hub",
        "COPIAS DE SEGURIDAD",
    ]
    assert devices.usb_and_labels(tmp_path / "nothing") == []


async def test_connected_bluetooth_devices() -> None:
    bus = FakeBus()
    objects = {
        "/org/bluez/hci0/dev_1": {
            "org.bluez.Device1": {
                "Alias": Variant("s", "WH-1000XM4"),
                "Connected": Variant("b", True),
            }
        },
        "/org/bluez/hci0/dev_2": {
            "org.bluez.Device1": {"Name": Variant("s", "Mouse"), "Connected": Variant("b", False)}
        },
        "/org/bluez/hci0": {"org.bluez.Adapter1": {}},
    }
    bus.on("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", [objects])
    assert await devices.bluetooth(bus) == ["WH-1000XM4"]
    assert await devices.bluetooth(FakeBus()) == []  # no BlueZ
