"""Facts about the machine read from /etc, /proc and /sys (rooted, so tests use a temp dir)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HELPER = "usr/local/libexec/powerclock-helper"
HELPER_POLICY = "usr/share/polkit-1/actions/org.powerclock.helper.policy"
HELPER_RULES = "etc/polkit-1/rules.d/50-powerclock-unattended.rules"
WAKEALARM = "sys/class/rtc/rtc0/wakealarm"


@dataclass(frozen=True)
class Rtc:
    present: bool
    name: str | None
    wakealarm: bool
    local_time: bool  # the RTC keeps local time instead of UTC (/etc/adjtime says LOCAL)


class Host:
    def __init__(self, root: Path = Path("/")) -> None:
        self.root = root

    def _read(self, relative: str) -> str | None:
        try:
            return (self.root / relative).read_text(errors="replace").strip()
        except OSError:
            return None

    def rtc(self) -> Rtc:
        base = self.root / "sys/class/rtc/rtc0"
        adjtime = (self._read("etc/adjtime") or "").splitlines()
        return Rtc(
            present=base.exists(),
            name=self._read("sys/class/rtc/rtc0/name"),
            wakealarm=(base / "wakealarm").exists(),
            local_time=len(adjtime) >= 3 and adjtime[2].strip() == "LOCAL",
        )

    def hardware(self) -> tuple[str | None, str | None]:
        return self._read("sys/class/dmi/id/sys_vendor"), self._read(
            "sys/class/dmi/id/product_name"
        )

    def linger(self, user: str) -> bool:
        return (self.root / "var/lib/systemd/linger" / user).exists()

    def helper_installed(self) -> bool:
        return (self.root / HELPER).exists() and (self.root / HELPER_POLICY).exists()

    def helper_matches(self, packaged: Path) -> bool:
        """Is the installed helper the one shipped with this version of powerclock?"""
        try:
            return (self.root / HELPER).read_bytes() == packaged.read_bytes()
        except OSError:
            return False

    def display_manager(self) -> str | None:
        """The display manager systemd starts (sddm, lightdm, gdm…), if any."""
        try:
            target = (self.root / "etc/systemd/system/display-manager.service").readlink()
        except OSError:
            return None
        name = target.name.removesuffix(".service")
        return "gdm" if name == "gdm3" else name

    def boot_unit_enabled(self) -> bool:
        """powerclock-boot.service (the one-time log-in) is installed and enabled."""
        wants = self.root / "etc/systemd/system/graphical.target.wants/powerclock-boot.service"
        return wants.is_symlink() or wants.exists()

    def unattended_installed(self) -> bool | None:
        # rules.d is root:polkitd 0750: a normal user cannot even see inside.
        return _exists(self.root / HELPER_RULES)

    def wake_alarm(self, env: Mapping[str, str]) -> datetime | None:
        """The programmed RTC alarm (readable without privileges), or None."""
        raw = self._read(WAKEALARM)
        if not raw:
            return None
        value = int(raw)
        if self.rtc().local_time:  # local wall-clock time counted as if it were UTC
            wall = datetime.fromtimestamp(value, UTC).replace(tzinfo=self.timezone(env))
            return wall.astimezone(UTC)
        return datetime.fromtimestamp(value, UTC)

    def memory_kib(self) -> int | None:
        return _meminfo_value(self._read("proc/meminfo"), "MemTotal")

    def swap_kib(self) -> int:
        lines = (self._read("proc/swaps") or "").splitlines()[1:]
        return sum(int(fields[2]) for line in lines if len(fields := line.split()) >= 3)

    def resume_configured(self) -> bool:
        return "resume=" in (self._read("proc/cmdline") or "")

    def wakeup_source(self) -> str | None:
        """The last wake-up IRQ (/sys/power/pm_wakeup_irq), its device and input names."""
        irq = self._read("sys/power/pm_wakeup_irq")
        if not irq or not irq.isdigit():
            return None
        label = None
        for line in (self._read("proc/interrupts") or "").splitlines():
            number, _, rest = line.strip().partition(":")
            if number == irq and rest.split():
                label = rest.split()[-1]
                break
        if label is None:
            return f"IRQ {irq}"
        names = []
        for name_file in sorted((self.root / "sys/class/input").glob("input*/name")):
            if label in str(name_file.parent.resolve()):
                names.append(name_file.read_text().strip())
        return f"IRQ {irq}: {label}" + (f" ({', '.join(names)})" if names else "")

    def timezone(self, env: Mapping[str, str]) -> tzinfo:
        """IANA zone from $TZ, the /etc/localtime link or /etc/timezone; else the raw file."""
        for name in (
            env.get("TZ", "").lstrip(":"),
            self._localtime_key(),
            self._read("etc/timezone"),
        ):
            if name:
                try:
                    return ZoneInfo(name)
                except (ZoneInfoNotFoundError, ValueError, OSError):
                    continue
        try:
            with (self.root / "etc/localtime").open("rb") as file:
                return ZoneInfo.from_file(file, key="localtime")
        except (OSError, ValueError):
            return UTC

    def _localtime_key(self) -> str | None:
        try:
            target = str((self.root / "etc/localtime").readlink())
        except OSError:
            return None
        _, found, key = target.partition("zoneinfo/")
        return key if found else None


def _exists(path: Path) -> bool | None:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except PermissionError:
        return None  # unknown
    return True


def _meminfo_value(text: str | None, field: str) -> int | None:
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        if name == field:
            return int(rest.split()[0])
    return None
