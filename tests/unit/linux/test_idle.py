import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fakebus import LOGIND, MANAGER, MANAGER_PATH, FakeBus, FakeCommands, kde_laptop
from fakewayland import FakeCompositor
from powerclock.platform.linux.idle import GNOME, WAYLAND, XPRINTIDLE, IdleProbe
from powerclock.platform.linux.idle import LOGIND as LOGIND_STRATEGY
from powerclock.platform.linux.logind import Logind

MUTTER = "org.gnome.Mutter.IdleMonitor"


def probe(
    tmp_path: Path,
    *,
    session: FakeBus | None = None,
    system: FakeBus | None = None,
    commands: FakeCommands | None = None,
    **env: str,
) -> IdleProbe:
    system = system or FakeBus()
    return IdleProbe(
        session or FakeBus(),
        Logind(system, uid=1000),
        commands or FakeCommands(),
        {"XDG_RUNTIME_DIR": str(tmp_path), **env},
    )


async def test_wayland_first(tmp_path: Path) -> None:
    globals_ = {"wl_seat": 10, "ext_idle_notifier_v1": 2}
    async with FakeCompositor(tmp_path / "wayland-0", globals_) as compositor:
        idle = probe(tmp_path, system=kde_laptop()[0])
        assert await idle.idle_seconds() == 0
        assert idle.strategy == WAYLAND
        assert idle.input_only
        await asyncio.wait_for(compositor.requested.wait(), 2)
        await compositor.idled()
        for _ in range(200):
            if (value := await idle.idle_seconds()) is not None and value > 0:
                break
            await asyncio.sleep(0.005)
        assert value is not None
        assert value >= 5
        await idle.close()


async def test_gnome(tmp_path: Path) -> None:
    session = FakeBus()
    session.on(MUTTER, "/org/gnome/Mutter/IdleMonitor/Core", MUTTER, "GetIdletime", [90_500])
    idle = probe(tmp_path, session=session)
    assert await idle.idle_seconds() == 90.5
    assert idle.strategy == GNOME


async def test_logind(tmp_path: Path) -> None:
    system = kde_laptop()[0]
    idle = probe(tmp_path, system=system)
    assert await idle.idle_seconds() == 0  # IdleHint false
    since = datetime.now(UTC) - timedelta(minutes=10)
    system.prop(LOGIND, MANAGER_PATH, MANAGER, "IdleHint", True)
    system.prop(LOGIND, MANAGER_PATH, MANAGER, "IdleSinceHint", int(since.timestamp() * 1e6))
    assert await idle.idle_seconds() == pytest.approx(600, abs=5)
    assert idle.strategy == LOGIND_STRATEGY


async def test_xprintidle(tmp_path: Path) -> None:
    commands = FakeCommands(available=["xprintidle"], results={"xprintidle": (0, "12000")})
    idle = probe(tmp_path, commands=commands, DISPLAY=":0")
    assert await idle.idle_seconds() == 12
    assert idle.strategy == XPRINTIDLE


async def test_nothing_works(tmp_path: Path) -> None:
    idle = probe(tmp_path, commands=FakeCommands(available=["xprintidle"]))  # but no DISPLAY
    assert await idle.idle_seconds() is None
    assert idle.strategy is None
