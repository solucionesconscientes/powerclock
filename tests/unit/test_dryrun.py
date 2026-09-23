from datetime import UTC, datetime

from kse.platform.base import PowerAction, PowerEvent, PowerMode
from kse.platform.dryrun import DryRunPlatform
from kse.platform.fake import FakePlatform

WHEN = datetime(2026, 9, 25, 5, 30, tzinfo=UTC)


async def test_writes_are_blocked() -> None:
    fake = FakePlatform()
    dry = DryRunPlatform(fake)
    await dry.power(PowerAction.SHUTDOWN, PowerMode.FORCE)
    await dry.wake_set(WHEN)
    await dry.wake_clear()
    assert fake.calls == []
    assert [method for method, _ in dry.blocked] == ["power", "wake_set", "wake_clear"]


async def test_reads_and_harmless_calls_reach_the_real_backend() -> None:
    fake = FakePlatform(idle=12.0, media=True, ssid="Casa", notify_response="cancel")
    fake.wake = WHEN
    dry = DryRunPlatform(fake)
    assert await dry.idle_seconds() == 12.0
    assert await dry.media_playing() is True
    assert await dry.wifi_ssid() == "Casa"
    assert await dry.wake_get() == WHEN
    assert await dry.capabilities() == await fake.capabilities()
    assert await dry.notify("KSE", "hola", {"cancel": "Cancel"}) == "cancel"
    await dry.open("https://example.org")
    async with dry.inhibit_delay():
        assert fake.inhibited

    received: list[PowerEvent] = []

    async def on_event(event: PowerEvent) -> None:
        received.append(event)

    await dry.subscribe_power_events(on_event)
    await fake.emit(PowerEvent.AFTER_RESUME)
    assert received == [PowerEvent.AFTER_RESUME]
    assert fake.calls_to("power") == []


def test_name_shows_both() -> None:
    assert DryRunPlatform(FakePlatform()).name == "fake (dry-run)"
