from datetime import UTC, datetime

import pytest

import powerclock.platform
from powerclock.platform import dry_run_requested, get_backend
from powerclock.platform.base import (
    Capability,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerEvent,
    PowerMode,
)
from powerclock.platform.dryrun import DryRunPlatform
from powerclock.platform.fake import FakeCall, FakePlatform

WHEN = datetime(2026, 9, 24, 5, 30, tzinfo=UTC)


class MinimalBackend(PlatformBackend):
    name = "minimal"

    async def power(self, action: PowerAction, mode: PowerMode) -> None:
        pass

    async def capabilities(self) -> list[Capability]:
        return []


def test_get_backend_uses_environment() -> None:
    # conftest sets POWERCLOCK_BACKEND=fake and POWERCLOCK_DRY_RUN=1
    backend = get_backend()
    assert isinstance(backend, DryRunPlatform)
    assert isinstance(backend.inner, FakePlatform)
    assert backend.name == "fake (dry-run)"


def test_get_backend_without_dry_run() -> None:
    assert isinstance(get_backend(dry_run=False), FakePlatform)


def test_get_backend_by_name_is_forgiving() -> None:
    assert isinstance(get_backend(" FAKE ", dry_run=False), FakePlatform)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), (" YES ", True), ("on", True), ("0", False), ("", False)],
)
def test_dry_run_flag(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("POWERCLOCK_DRY_RUN", value)
    assert dry_run_requested() is expected
    assert isinstance(get_backend(), DryRunPlatform) is expected


def test_get_backend_unknown_name() -> None:
    with pytest.raises(NotSupported, match="no backend named 'nope'") as info:
        get_backend("nope")
    assert info.value.fix_hint is not None


def test_get_backend_defaults_to_current_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWERCLOCK_BACKEND")
    monkeypatch.setattr(powerclock.platform, "current_os", lambda: "plan9")
    with pytest.raises(NotSupported, match="'plan9'"):
        get_backend()


def test_backend_must_implement_power_and_capabilities() -> None:
    class Incomplete(PlatformBackend):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


async def test_unimplemented_methods_raise_not_supported() -> None:
    backend = MinimalBackend()
    with pytest.raises(NotSupported, match="wake_get") as info:
        await backend.wake_get()
    assert info.value.feature == "wake_get"
    assert "'minimal'" in info.value.detail
    with pytest.raises(NotSupported, match="inhibit_delay"):
        backend.inhibit_delay()


async def test_fake_records_power_calls() -> None:
    fake = FakePlatform()
    await fake.power(PowerAction.SHUTDOWN, PowerMode.GRACEFUL)
    assert fake.calls == [FakeCall("power", (PowerAction.SHUTDOWN, PowerMode.GRACEFUL))]


async def test_fake_wake_alarm() -> None:
    fake = FakePlatform()
    assert await fake.wake_get() is None
    await fake.wake_set(WHEN)
    assert await fake.wake_get() == WHEN
    await fake.wake_clear()
    assert await fake.wake_get() is None
    assert [call.method for call in fake.calls] == [
        "wake_get",
        "wake_set",
        "wake_get",
        "wake_clear",
        "wake_get",
    ]


async def test_fake_wake_rejects_naive_datetime() -> None:
    fake = FakePlatform()
    with pytest.raises(ValueError, match="timezone-aware"):
        await fake.wake_set(datetime(2026, 9, 24, 7, 30))  # naive on purpose
    assert fake.wake is None


async def test_fake_sensors_reflect_simulated_state() -> None:
    fake = FakePlatform(idle=42.0, media=True, ssid="Casa")
    assert await fake.idle_seconds() == 42.0
    assert await fake.media_playing() is True
    assert await fake.wifi_ssid() == "Casa"
    fake.idle = None
    assert await fake.idle_seconds() is None


async def test_fake_notify() -> None:
    fake = FakePlatform(notify_response="cancel")
    assert await fake.notify("PowerClock", "plain") is None
    buttons = {"cancel": "Cancel", "postpone": "Postpone"}
    assert await fake.notify("PowerClock", "countdown", actions=buttons) == "cancel"
    assert fake.calls_to("notify")[1] == FakeCall(
        "notify", ("PowerClock", "countdown", ("cancel", "postpone"))
    )


async def test_fake_open() -> None:
    fake = FakePlatform()
    await fake.open("https://example.org")
    assert fake.calls_to("open") == [FakeCall("open", ("https://example.org",))]


async def test_fake_power_events() -> None:
    fake = FakePlatform()
    received: list[PowerEvent] = []

    async def on_event(event: PowerEvent) -> None:
        received.append(event)

    await fake.subscribe_power_events(on_event)
    await fake.emit(PowerEvent.BEFORE_SLEEP)
    await fake.emit(PowerEvent.AFTER_RESUME)
    assert received == [PowerEvent.BEFORE_SLEEP, PowerEvent.AFTER_RESUME]


async def test_fake_inhibit_delay() -> None:
    fake = FakePlatform()
    async with fake.inhibit_delay():
        assert fake.inhibited
    assert not fake.inhibited
    assert fake.calls_to("inhibit_delay")


async def test_fake_capabilities() -> None:
    capabilities = await FakePlatform().capabilities()
    ids = [capability.id for capability in capabilities]
    assert len(ids) == len(set(ids))
    assert all(capability.supported for capability in capabilities)
    assert {f"power.{action}" for action in PowerAction} <= set(ids)


def test_old_variable_names_still_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The working name was kse: $KSE_DRY_RUN must never silently stop meaning dry run."""
    from powerclock.platform import dry_run_requested

    monkeypatch.delenv("POWERCLOCK_DRY_RUN")
    monkeypatch.setenv("KSE_DRY_RUN", "1")
    assert dry_run_requested()
    monkeypatch.setenv("POWERCLOCK_DRY_RUN", "0")
    assert dry_run_requested()  # either one asking for it is enough
    monkeypatch.delenv("KSE_DRY_RUN")
    assert not dry_run_requested()
