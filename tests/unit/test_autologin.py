"""Logging in once after a scheduled power-on: the root helper's ticket and boot step (on
temporary files, never the real /var, /run or /etc), the wake planner that arms it, and
the daemon that locks the screen afterwards (fake backend)."""

import json
import stat
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from powerclock.config import Paths
from powerclock.daemon.core import Daemon, WakeRequest
from powerclock.engine.clock import FakeClock, settle
from powerclock.engine.wake import WakePlanner
from powerclock.helper import powerclock_helper_linux as helper
from powerclock.platform.base import PowerAction, PowerMode
from powerclock.platform.fake import FakeCall, FakePlatform
from powerclock.sensors.fake import FakeReadings
from support import MADRID, START

NOW = 1_790_000_000
PC = {"PKEXEC_UID": "1000"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "usr/share/wayland-sessions").mkdir(parents=True)
    (tmp_path / "usr/share/wayland-sessions/plasma.desktop").write_text(
        "[Desktop Entry]\nName=Plasma (Wayland)\nDesktopNames=KDE\n"
    )
    (tmp_path / "etc/systemd/system").mkdir(parents=True)
    (tmp_path / "etc/sddm.conf.d").mkdir(parents=True)
    (tmp_path / "etc/sddm.conf.d/20-kubuntu.conf").write_text(
        "[Autologin]\nRelogin=false\nSession=plasma\nUser=\n"
    )
    return tmp_path


def manager(root: Path, name: str) -> None:
    link = root / "etc/systemd/system/display-manager.service"
    link.unlink(missing_ok=True)
    link.symlink_to(f"/usr/lib/systemd/system/{name}.service")


def call(root: Path, argv: list[str], now: int = NOW, env: dict[str, str] | None = None) -> int:
    return helper.main(
        argv,
        now=now,
        places=helper.Places(root),
        env=PC if env is None else env,
        user_name=lambda uid: "pc",
    )


def arm(root: Path, session: str = "-", mode: str = "locked", alarm: int = NOW + 3600) -> None:
    assert call(root, ["autologin-arm", str(alarm), session, mode]) == 0


def dmi(root: Path, wake: int) -> None:
    """A DMI table with a BIOS entry (type 0) and a System entry (type 1) with `wake`."""
    bios = bytes([0, 4, 0, 0]) + b"Dell\x00\x00"
    system = bytearray(27)
    system[0], system[1] = 1, 27
    system[0x18] = wake
    path = root / "sys/firmware/dmi/tables/DMI"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bios + bytes(system) + b"Latitude\x00\x00")


# ── The helper ────────────────────────────────────────────────────────────────


def test_arm_writes_a_private_ticket_for_the_caller(root: Path) -> None:
    arm(root, session="plasma")
    ticket = root / "var/lib/powerclock/autologin.json"
    assert json.loads(ticket.read_text()) == {
        "alarm": NOW + 3600,
        "uid": 1000,
        "user": "pc",
        "session": "plasma",
        "mode": "locked",
    }
    assert stat.S_IMODE(ticket.stat().st_mode) == 0o600
    assert call(root, ["autologin-disarm"]) == 0
    assert not ticket.exists()


@pytest.mark.parametrize(
    ("argv", "env", "message"),
    [
        (["autologin-arm", str(NOW + 60), "-", "locked"], {}, "only a regular user"),
        (["autologin-arm", str(NOW + 60), "-", "locked"], {"PKEXEC_UID": "0"}, "regular user"),
        (["autologin-arm", str(NOW + 60), "../../x", "locked"], PC, "not a session name"),
        (["autologin-arm", str(NOW + 60), "gnome", "locked"], PC, "no desktop session"),
        (["autologin-arm", str(NOW + 60), "-", "open"], PC, "must be locked or unlocked"),
        (["autologin-arm", str(NOW - 60), "-", "locked"], PC, "in the future"),
    ],
)
def test_arm_is_strict(
    root: Path,
    argv: list[str],
    env: dict[str, str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert call(root, argv, env=env) == helper.EXIT_USAGE
    assert message in capsys.readouterr().err
    assert not (root / "var/lib/powerclock/autologin.json").exists()


def test_boot_logs_in_once_on_the_scheduled_power_on(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manager(root, "sddm")
    dmi(root, 0x03)  # APM timer: the RTC
    arm(root)
    assert call(root, ["boot"], now=NOW + 3600 + 40) == 0
    assert "automatic log-in for pc through sddm" in capsys.readouterr().out
    config = (root / "run/powerclock/sddm.conf").read_text()
    assert "[Autologin]\nUser=pc\nRelogin=false\nSession=plasma\n" in config  # from SDDM's own
    assert json.loads((root / "run/powerclock/used").read_text()) == {"uid": 1000, "mode": "locked"}
    assert not (root / "var/lib/powerclock/autologin.json").exists()  # one use only
    assert call(root, ["autologin-done"]) == 0
    assert list((root / "run/powerclock").iterdir()) == []


@pytest.mark.parametrize(
    ("now", "wake", "reason"),
    [
        (NOW + 3600 + 700, 0x03, "not the scheduled power-on"),  # too late
        (NOW + 3600 - 300, 0x03, "not the scheduled power-on"),  # before the alarm
        (NOW + 3600 + 30, 0x06, "power button"),
    ],
)
def test_boot_refuses_other_start_ups(
    root: Path, now: int, wake: int, reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    manager(root, "sddm")
    dmi(root, wake)
    arm(root)
    assert call(root, ["boot"], now=now) == 0
    assert reason in capsys.readouterr().out
    assert not (root / "run/powerclock/sddm.conf").exists()
    assert not (root / "var/lib/powerclock/autologin.json").exists()  # used up anyway


def test_boot_with_lightdm_and_with_an_unknown_manager(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manager(root, "lightdm")
    arm(root, session="plasma", mode="unlocked")
    call(root, ["boot"], now=NOW + 3600 + 30)
    assert (
        (root / "run/powerclock/lightdm.conf")
        .read_text()
        .endswith(
            "[Seat:*]\nautologin-user=pc\nautologin-user-timeout=0\nautologin-session=plasma\n"
        )
    )
    manager(root, "gdm3")
    arm(root)
    call(root, ["boot"], now=NOW + 3600 + 30)
    assert "display manager gdm is not supported" in capsys.readouterr().out
    assert not (root / "run/powerclock/used").exists()


def test_boot_without_a_ticket_clears_what_is_left(root: Path) -> None:
    (root / "run/powerclock").mkdir(parents=True)
    (root / "run/powerclock/sddm.conf").write_text("[Autologin]\nUser=pc\n")
    assert call(root, ["boot"]) == 0
    assert not (root / "run/powerclock/sddm.conf").exists()


def test_a_tampered_ticket_is_ignored(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manager(root, "sddm")
    state = root / "var/lib/powerclock"
    state.mkdir(parents=True)
    (state / "autologin.json").write_text(
        json.dumps({"alarm": NOW, "uid": 0, "user": "root", "session": "-", "mode": "locked"})
    )
    call(root, ["boot"], now=NOW + 10)
    assert "not valid" in capsys.readouterr().out
    assert not (root / "run/powerclock/sddm.conf").exists()


def test_wake_type_of_a_short_table(tmp_path: Path) -> None:
    path = tmp_path / "DMI"
    path.write_bytes(bytes([1, 8, 0, 0, 0, 0, 0, 0]) + b"\x00\x00")  # SMBIOS 2.0: no wake type
    assert helper.wake_type(path) is None
    assert helper.wake_type(tmp_path / "missing") is None


# ── The wake planner arms it ──────────────────────────────────────────────────


async def test_planner_arms_and_disarms_the_ticket(fake: FakePlatform, clock: FakeClock) -> None:
    needs: list[tuple[object, str | None]] = [(START + timedelta(hours=1), "locked")]
    planner = WakePlanner(fake, clock, lambda: list(needs))  # type: ignore[arg-type]
    await planner.sync()
    alarm = START + timedelta(hours=1) - timedelta(minutes=3)  # three minutes: it logs in
    assert fake.wake == alarm
    assert fake.login == (alarm, "locked")
    needs[:] = [(START + timedelta(hours=1), None)]
    await planner.sync()
    assert fake.wake == START + timedelta(hours=1) - timedelta(minutes=2)
    assert fake.login is None
    assert [c.method for c in fake.calls if c.method.startswith("autologin")] == [
        "autologin_arm",
        "autologin_disarm",
    ]
    await planner._release()


# ── The daemon locks the screen afterwards ────────────────────────────────────


@pytest.fixture
async def daemon(
    tmp_path: Path, clock: FakeClock, fake: FakePlatform, readings: FakeReadings
) -> AsyncIterator[Daemon]:
    fake.tz = MADRID
    daemon = Daemon(
        fake,
        paths=Paths(tmp_path / "c", tmp_path / "d"),
        clock=clock,
        readings=readings,
        dry_run=False,
    )
    yield daemon
    await daemon.stop()


@pytest.mark.parametrize(("mode", "locks"), [("locked", True), ("unlocked", False)])
async def test_after_logging_in_by_itself(
    daemon: Daemon, fake: FakePlatform, clock: FakeClock, mode: str, locks: bool
) -> None:
    fake.logged_in = mode  # type: ignore[assignment]
    fake.desktop = False
    await daemon.start()
    await clock.advance(10)
    assert fake.calls_to("power") == []  # the desktop is not up yet
    fake.desktop = True
    await clock.advance(2)
    await settle()
    lock = [FakeCall("power", (PowerAction.LOCK, PowerMode.GRACEFUL))]
    assert fake.calls_to("power") == (lock if locks else [])
    assert len(fake.calls_to("autologin_done")) == 1


async def test_rules_with_log_in(daemon: Daemon, fake: FakePlatform) -> None:
    await daemon.start()
    rule = daemon.wake(WakeRequest(at="23:00", log_in="locked"))
    assert rule.log_in == "locked"
    assert rule.wake
