import asyncio
from pathlib import Path

import pytest

from fakewayland import FakeCompositor
from kse.platform.linux.wayland import IdleMonitor, WaylandError, find_socket

FULL = {"wl_compositor": 6, "wl_seat": 10, "ext_idle_notifier_v1": 2}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def until(condition: object) -> None:
    for _ in range(200):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


async def test_asks_for_input_idle_notifications(tmp_path: Path) -> None:
    clock = Clock()
    async with FakeCompositor(tmp_path / "wayland-9", FULL) as compositor:
        monitor = IdleMonitor(compositor.socket, granularity=5, clock=clock)
        await monitor.start()
        await asyncio.wait_for(compositor.requested.wait(), 2)
        assert compositor.binds == [("wl_seat", 1, 4), ("ext_idle_notifier_v1", 2, 5)]
        assert compositor.notification == (2, 6, 5000, 4)  # input-only, 5 s, seat 4
        assert monitor.input_only
        assert monitor.running
        assert monitor.idle_seconds() == 0

        await compositor.idled()
        await until(lambda: monitor.idle_seconds() > 0)
        clock.now += 60
        assert monitor.idle_seconds() == 65  # idle since 5 s before "idled" arrived
        await compositor.resumed()
        await until(lambda: monitor.idle_seconds() == 0)
        await monitor.close()
        assert not monitor.running


async def test_version_1_uses_the_plain_notification(tmp_path: Path) -> None:
    async with FakeCompositor(tmp_path / "wayland-9", {**FULL, "ext_idle_notifier_v1": 1}) as fake:
        monitor = IdleMonitor(fake.socket)
        await monitor.start()
        await asyncio.wait_for(fake.requested.wait(), 2)
        assert fake.notification is not None
        assert fake.notification[0] == 1
        assert not monitor.input_only
        await monitor.close()


async def test_compositor_without_the_protocol(tmp_path: Path) -> None:
    async with FakeCompositor(tmp_path / "wayland-9", {"wl_seat": 10}) as fake:
        monitor = IdleMonitor(fake.socket)
        with pytest.raises(WaylandError, match="ext_idle_notifier_v1"):
            await monitor.start()
        assert not monitor.running


async def test_compositor_going_away_resets_the_state(tmp_path: Path) -> None:
    async with FakeCompositor(tmp_path / "wayland-9", FULL) as fake:
        monitor = IdleMonitor(fake.socket)
        await monitor.start()
        await asyncio.wait_for(fake.requested.wait(), 2)
        await fake.idled()
        await until(lambda: monitor.idle_seconds() > 0)
        await fake.disconnect()
        await until(lambda: not monitor.running)
        assert monitor.idle_seconds() == 0
        await monitor.close()


async def test_protocol_error_stops_the_monitor(tmp_path: Path) -> None:
    async with FakeCompositor(tmp_path / "wayland-9", FULL) as fake:
        monitor = IdleMonitor(fake.socket)
        await monitor.start()
        await asyncio.wait_for(fake.requested.wait(), 2)
        await fake.protocol_error("invalid seat")
        await until(lambda: not monitor.running)
        await monitor.close()


def test_find_socket(tmp_path: Path) -> None:
    (tmp_path / "wayland-1").touch()
    (tmp_path / "wayland-1.lock").touch()
    runtime = {"XDG_RUNTIME_DIR": str(tmp_path)}
    assert find_socket(runtime) == tmp_path / "wayland-1"
    assert find_socket({**runtime, "WAYLAND_DISPLAY": "wayland-1"}) == tmp_path / "wayland-1"
    assert find_socket({**runtime, "WAYLAND_DISPLAY": str(tmp_path / "wayland-1")}) is not None
    assert find_socket({**runtime, "WAYLAND_DISPLAY": "wayland-7"}) is None
    (tmp_path / "wayland-1").unlink()
    assert find_socket(runtime) is None
