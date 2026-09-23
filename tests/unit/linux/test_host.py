from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from kse.platform.linux.host import Host


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_rtc(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert not host.rtc().present
    write(tmp_path, "sys/class/rtc/rtc0/name", "rtc_cmos 00:00\n")
    write(tmp_path, "sys/class/rtc/rtc0/wakealarm", "")
    write(tmp_path, "etc/adjtime", "0.0 0 0.0\n0\nLOCAL\n")
    rtc = host.rtc()
    assert (rtc.present, rtc.name, rtc.wakealarm, rtc.local_time) == (
        True,
        "rtc_cmos 00:00",
        True,
        True,
    )
    write(tmp_path, "etc/adjtime", "0.0 0 0.0\n0\nUTC\n")
    assert not host.rtc().local_time


def test_machine_facts(tmp_path: Path) -> None:
    write(tmp_path, "sys/class/dmi/id/sys_vendor", "Dell Inc.\n")
    write(tmp_path, "sys/class/dmi/id/product_name", "Latitude 5480\n")
    write(tmp_path, "proc/meminfo", "MemTotal:       16318756 kB\nMemFree: 1 kB\n")
    write(
        tmp_path,
        "proc/swaps",
        "Filename Type Size Used Priority\n"
        "/swapfile file 524284 0 -1\n"
        "/dev/zram0 partition 1000 0 5\n",
    )
    write(tmp_path, "proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x ro quiet\n")
    write(tmp_path, "var/lib/systemd/linger/pc", "")
    host = Host(tmp_path)
    assert host.hardware() == ("Dell Inc.", "Latitude 5480")
    assert host.memory_kib() == 16318756
    assert host.swap_kib() == 525284
    assert not host.resume_configured()
    assert host.linger("pc")
    assert not host.linger("other")
    assert not host.helper_installed()


def test_missing_facts_are_harmless(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.hardware() == (None, None)
    assert host.memory_kib() is None
    assert host.swap_kib() == 0


def test_timezone_from_the_localtime_link(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/localtime").symlink_to("/usr/share/zoneinfo/Europe/Madrid")
    assert Host(tmp_path).timezone({}) == ZoneInfo("Europe/Madrid")


@pytest.mark.parametrize("tz", ["America/New_York", ":America/New_York"])
def test_timezone_from_env(tmp_path: Path, tz: str) -> None:
    assert Host(tmp_path).timezone({"TZ": tz}) == ZoneInfo("America/New_York")


def test_timezone_from_etc_timezone(tmp_path: Path) -> None:
    write(tmp_path, "etc/timezone", "Europe/Lisbon\n")
    assert Host(tmp_path).timezone({"TZ": "not/a-zone"}) == ZoneInfo("Europe/Lisbon")


def test_timezone_from_the_file_or_utc(tmp_path: Path) -> None:
    assert Host(tmp_path).timezone({}) is UTC
    madrid = Path("/usr/share/zoneinfo/Europe/Madrid")
    if not madrid.exists():
        pytest.skip("no system tzdata")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/localtime").write_bytes(madrid.read_bytes())  # a copy, not a link
    zone = Host(tmp_path).timezone({})
    assert str(zone) == "localtime"
    assert zone.utcoffset(__import__("datetime").datetime(2026, 7, 1)).total_seconds() == 7200
