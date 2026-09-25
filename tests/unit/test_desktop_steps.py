"""Sound, media players and desktop settings (M13): the steps in the executor, against the
fake backend; nothing reaches the real desktop."""

from datetime import timedelta
from typing import Any

import pytest

from powerclock.engine.clock import FakeClock, settle
from powerclock.engine.executor import Executor
from powerclock.platform.fake import FakePlatform
from support import MADRID, rule


async def run_steps(executor: Executor, *steps: dict[str, Any]) -> Any:
    return await executor.wait(executor.start(rule(actions=list(steps)), MADRID, cause="manual").id)


async def test_media_player(executor: Executor, fake: FakePlatform) -> None:
    run = await run_steps(
        executor,
        {"type": "media", "command": "open", "player": "VLC", "uri": "https://radio/{date}"},
        {"type": "media", "command": "pause"},
    )
    assert run.state == "done"
    assert [c.args for c in fake.calls_to("control_media")] == [
        ("open", "VLC", "https://radio/2026-09-24"),
        ("pause", None, None),
    ]
    assert run.steps[0].detail == "vlc"
    fake.players = []
    run = await run_steps(executor, {"type": "media", "command": "play"})
    assert run.state == "failed"
    assert "no media player" in (run.reason or "")


async def test_volume_now_and_little_by_little(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    await run_steps(executor, {"type": "volume", "level": 10, "mute": "on"})
    assert (fake.level, fake.muted) == (0.1, True)
    run = executor.start(
        rule(actions=[{"type": "volume", "level": 40, "mute": "off", "fade": "3s"}]),
        MADRID,
        cause="manual",
    )
    await settle()
    assert fake.muted is False  # unmuted first, so the fade is heard
    await clock.advance(3)
    await settle()
    assert run.state == "done"
    levels = [c.args[0] for c in fake.calls_to("set_volume") if c.args[0] is not None]
    assert levels == pytest.approx([0.1, 0.2, 0.3, 0.4])


async def test_sound_and_speech(executor: Executor, fake: FakePlatform) -> None:
    await run_steps(
        executor,
        {"type": "sound", "file": "alarm-clock-elapsed"},
        {"type": "sound", "say": "Copia de {rule} terminada", "language": "es"},
    )
    assert fake.calls_to("play_sound")[0].args == ("alarm-clock-elapsed",)
    assert fake.calls_to("say")[0].args == ("Copia de test terminada", "es")


async def test_desktop_settings(executor: Executor, fake: FakePlatform) -> None:
    run = await run_steps(
        executor,
        {"type": "desktop", "theme": "dark", "brightness": 40, "power_profile": "power-saver"},
        {"type": "desktop", "wallpaper": "/pics/{weekday}.jpg"},
    )
    assert run.steps[0].detail == "BreezeDark, brightness 40 %, power-saver"
    assert fake.calls_to("set_wallpaper")[0].args == ("/pics/thu.jpg",)
    assert fake.calls_to("set_power_profile")[0].args == ("power-saver",)


async def test_network(executor: Executor, fake: FakePlatform) -> None:
    await run_steps(executor, {"type": "network", "connect": "VPN Oficina", "wifi": "on"})
    assert fake.calls_to("network")[0].args == ("VPN Oficina", None, True)


async def test_inhibit_holds_in_the_background(
    executor: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    step = {"type": "inhibit", "do_not_disturb": True, "duration": "1h"}
    run = await run_steps(executor, step, {"type": "notify", "title": "next step runs at once"})
    assert run.state == "done"
    assert run.steps[0].detail == "for 1h"
    assert fake.inhibited_now == {"screen", "notifications"}
    await clock.advance(timedelta(minutes=59).total_seconds())
    assert fake.inhibited_now == {"screen", "notifications"}
    await clock.advance(60)
    await settle()
    assert fake.inhibited_now == set()


async def test_inhibitors_are_given_back_on_shutdown(
    executor: Executor, fake: FakePlatform
) -> None:
    await run_steps(executor, {"type": "inhibit", "no_sleep": True, "duration": "8h"})
    assert "sleep" in fake.inhibited_now
    await executor.shutdown()
    assert fake.inhibited_now == set()


async def test_screenshot(executor: Executor, fake: FakePlatform) -> None:
    run = await run_steps(executor, {"type": "screenshot", "file": "/tmp/{rule}-{date}.png"})
    assert run.steps[0].detail == "/tmp/test-2026-09-24.png"
    assert fake.calls_to("screenshot")[0].args == ("/tmp/test-2026-09-24.png",)


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"type": "media", "command": "open"}, "uri goes with command: open"),
        ({"type": "media", "command": "play", "uri": "x"}, "uri goes with command: open"),
        ({"type": "volume"}, "set a level, mute, or both"),
        ({"type": "volume", "mute": "on", "fade": "1m"}, "fade needs a level"),
        ({"type": "sound"}, "exactly one of: file, say"),
        ({"type": "desktop"}, "at least one of: theme"),
        ({"type": "network"}, "at least one of: connect"),
        ({"type": "inhibit", "screen_on": False, "duration": "1m"}, "at least one of: screen_on"),
    ],
)
def test_steps_explain_what_they_need(step: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        rule(actions=[step])
