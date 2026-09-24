"""Against the real machine, READ-ONLY: never calls power(), wake_set() or anything that
changes the system. Excluded by default; run with `uv run pytest -m real`."""

import sys

import pytest

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only"),
]


async def test_capabilities_report() -> None:
    from powerclock.platform.linux import LinuxPlatform

    linux = LinuxPlatform()
    try:
        rows = {row.id: row for row in await linux.capabilities()}
    finally:
        await linux.close()
    assert "power.shutdown" in rows
    assert "timezone" in rows


async def test_readings() -> None:
    from powerclock.platform.linux import LinuxPlatform

    linux = LinuxPlatform()
    try:
        idle = await linux.idle_seconds()
        assert idle is None or idle >= 0
        assert await linux.media_playing() in (True, False, None)
        linux.timezone()
    finally:
        await linux.close()
