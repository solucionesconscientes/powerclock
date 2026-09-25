"""Reasons and conditions in words (English here; translated when the language is Spanish)."""

import pytest

from powerclock.labels import (
    capability_label,
    describe_predicate,
    describe_trigger,
    reason_label,
)


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("conditions not met", "conditions not met"),
        ("cancelled before it fired", "cancelled before it fired"),
        (
            "missed: the machine was off or asleep, or the daemon was not running",
            "missed: the computer was off or asleep, or PowerClock was not running",
        ),
        (
            "step 1 (run) failed: exit code 3: disk full",
            "step 1 (Run a program) failed: exit code 3: disk full",
        ),
        ('guard active: {"type":"media_playing"}', "waiting while: Something is playing"),
        (
            'guard still active after 1h: {"type":"process_running","name":"ffmpeg"}',
            "still held after 1h: A program is running: ffmpeg",
        ),
        (
            'waiting until {"type":"net_below","kbps":50.0,"for":"5m","direction":"both",'
            '"interface":null}',
            "waiting until: Network quiet (below): 50 kbit/s for 5m",
        ),
        ("dry run: shutdown (graceful) not executed", "test mode: Shut down was not really done"),
        ("something new", "something new"),  # unknown texts are shown as they are
        (None, ""),
    ],
)
def test_reasons(reason: str | None, text: str) -> None:
    assert reason_label(reason) == text


def test_conditions_in_words() -> None:
    assert describe_predicate({"not": {"type": "ssh_session"}}) == (
        "not (Someone is connected by SSH)"
    )
    both = {
        "all": [
            {"type": "weekday", "days": ["sat", "sun"]},
            {"type": "time_window", "start": "22:00:00", "end": "07:00:00"},
        ]
    }
    assert (
        describe_predicate(both) == "Day of the week: Sat, Sun + Time of day between: 22:00-07:00"
    )
    either = {"any": [{"type": "media_playing"}, {"type": "wifi_ssid", "ssid": "Home"}]}
    assert describe_predicate(either) == (
        "Something is playing or Connected to the Wi-Fi network: Home"
    )
    assert describe_trigger({"type": "process_exit", "name": "ffmpeg"}) == (
        "When a program ends: ffmpeg"
    )


@pytest.mark.parametrize(
    ("capability", "name"),
    [
        ("power.shutdown", "Shut down"),
        ("power.graceful", "Let applications ask to save"),
        ("wake.helper", "Permission to turn the computer on"),
        ("linger", "Work with the session closed"),
        ("something.new", "something.new"),  # a new check still shows up, by its id
    ],
)
def test_capabilities_have_names_for_people(capability: str, name: str) -> None:
    assert capability_label(capability) == name
