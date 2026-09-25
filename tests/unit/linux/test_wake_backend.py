"""Wake-up alarm on Linux: pkexec + powerclock-helper to write, sysfs to read (all simulated)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fakebus import FakeCommands, kde_laptop
from powerclock.platform.base import NotSupported
from powerclock.platform.linux import LinuxPlatform
from powerclock.platform.linux.helper import packaged

WHEN = datetime(2026, 9, 25, 5, 28, tzinfo=UTC)


def write(root: Path, relative: str, content: str | bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def install_helper(root: Path, outdated: bool = False) -> None:
    helper = b"old helper" if outdated else packaged("powerclock_helper_linux.py").read_bytes()
    write(root, "usr/local/libexec/powerclock-helper", helper)
    write(root, "usr/share/polkit-1/actions/org.powerclock.helper.policy", "<policyconfig/>")


def linux(root: Path, commands: FakeCommands) -> LinuxPlatform:
    system, session = kde_laptop()
    return LinuxPlatform(
        system_bus=system,
        session_bus=session,
        commands=commands,
        root=root,
        env={"XDG_RUNTIME_DIR": str(root)},
        uid=1000,
    )


async def test_wake_set_and_clear_go_through_pkexec(tmp_path: Path) -> None:
    install_helper(tmp_path)
    commands = FakeCommands(available=["pkexec"])
    backend = linux(tmp_path, commands)
    await backend.wake_set(WHEN)
    await backend.wake_clear()
    assert [argv for argv, _ in commands.ran] == [
        ["pkexec", "/usr/local/libexec/powerclock-helper", "wake-set", str(int(WHEN.timestamp()))],
        ["pkexec", "/usr/local/libexec/powerclock-helper", "wake-clear"],
    ]


async def test_wake_needs_the_helper(tmp_path: Path) -> None:
    commands = FakeCommands(available=["pkexec"])
    with pytest.raises(NotSupported, match="powerclock-helper is not installed") as info:
        await linux(tmp_path, commands).wake_set(WHEN)
    assert info.value.fix_hint == "powerclock helper install"
    assert commands.ran == []


async def test_not_authorized(tmp_path: Path) -> None:
    install_helper(tmp_path)
    commands = FakeCommands(
        available=["pkexec"],
        results={"pkexec": (127, "Error executing command as another user: Not authorized")},
    )
    with pytest.raises(NotSupported, match="not authorized") as info:
        await linux(tmp_path, commands).wake_set(WHEN)
    assert "--unattended" in (info.value.fix_hint or "")


async def test_helper_failure(tmp_path: Path) -> None:
    install_helper(tmp_path)
    commands = FakeCommands(available=["pkexec"], results={"pkexec": (1, "cannot program")})
    with pytest.raises(OSError, match="wake-set failed"):
        await linux(tmp_path, commands).wake_set(WHEN)


async def test_naive_datetimes_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await linux(tmp_path, FakeCommands()).wake_set(datetime(2026, 9, 25, 7, 28))  # naive


async def test_wake_get_reads_sysfs(tmp_path: Path) -> None:
    backend = linux(tmp_path, FakeCommands())
    assert await backend.wake_get() is None
    write(tmp_path, "sys/class/rtc/rtc0/wakealarm", "")
    assert await backend.wake_get() is None
    write(tmp_path, "sys/class/rtc/rtc0/wakealarm", f"{int(WHEN.timestamp())}\n")
    assert await backend.wake_get() == WHEN


async def test_wake_get_with_a_local_time_rtc(tmp_path: Path) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/localtime").symlink_to("/usr/share/zoneinfo/Europe/Madrid")
    write(tmp_path, "etc/adjtime", "0.0 0 0.0\n0\nLOCAL\n")
    local_as_utc = int(WHEN.timestamp()) + 2 * 3600  # 07:28 Madrid counted as UTC
    write(tmp_path, "sys/class/rtc/rtc0/wakealarm", str(local_as_utc))
    assert await linux(tmp_path, FakeCommands()).wake_get() == WHEN


async def rows(backend: LinuxPlatform) -> dict[str, tuple[bool, str, str | None]]:
    return {r.id: (r.supported, r.detail, r.fix_hint) for r in await backend.capabilities()}


async def test_doctor_without_helper(tmp_path: Path) -> None:
    report = await rows(linux(tmp_path, FakeCommands()))
    assert report["wake.helper"] == (False, "not installed", "powerclock helper install")
    assert "wake.authorized" not in report
    assert report["wake.alarm"][1] == "none"


@pytest.mark.parametrize(
    ("code", "supported", "text"),
    [
        (0, True, "without a password"),
        (2, False, "password would be needed"),
        (1, False, "not allowed"),
    ],
)
async def test_doctor_with_helper(tmp_path: Path, code: int, supported: bool, text: str) -> None:
    install_helper(tmp_path)
    write(tmp_path, "sys/class/rtc/rtc0/wakealarm", str(int(WHEN.timestamp())))
    commands = FakeCommands(available=["pkexec"], results={"pkcheck": (code, "")})
    report = await rows(linux(tmp_path, commands))
    assert report["wake.helper"][:2] == (True, "installed and up to date")
    assert report["wake.authorized"][0] is supported
    assert text in report["wake.authorized"][1]
    assert report["wake.alarm"][1].startswith("programmed for 2026-09-25")
    assert report["wake.unattended"][0] is False
    pkcheck = next(argv for argv, _ in commands.ran if argv[0] == "pkcheck")
    assert pkcheck[:3] == ["pkcheck", "--action-id", "org.powerclock.helper.wake"]


async def test_doctor_notices_an_outdated_helper(tmp_path: Path) -> None:
    install_helper(tmp_path, outdated=True)
    report = await rows(linux(tmp_path, FakeCommands()))
    assert report["wake.helper"] == (
        False,
        "installed, but from another version of powerclock",
        "powerclock helper install",
    )


async def test_doctor_unattended_rule(tmp_path: Path) -> None:
    install_helper(tmp_path)
    write(tmp_path, "etc/polkit-1/rules.d/50-powerclock-unattended.rules", "// powerclock")
    report = await rows(linux(tmp_path, FakeCommands(results={"pkcheck": (0, "")})))
    assert report["wake.unattended"][:2] == (True, "rule installed: works with the session closed")
