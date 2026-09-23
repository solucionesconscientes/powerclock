"""Facts about the machine read from /etc, /proc and /sys (rooted, so tests use a temp dir)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HELPER = "usr/local/libexec/kse-helper"
HELPER_POLICY = "usr/share/polkit-1/actions/org.kse.helper.policy"


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

    def memory_kib(self) -> int | None:
        return _meminfo_value(self._read("proc/meminfo"), "MemTotal")

    def swap_kib(self) -> int:
        lines = (self._read("proc/swaps") or "").splitlines()[1:]
        return sum(int(fields[2]) for line in lines if len(fields := line.split()) >= 3)

    def resume_configured(self) -> bool:
        return "resume=" in (self._read("proc/cmdline") or "")

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


def _meminfo_value(text: str | None, field: str) -> int | None:
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        if name == field:
            return int(rest.split()[0])
    return None
