from datetime import timedelta

import pytest

from powerclock.models import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0s", timedelta(0)),
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("2h", timedelta(hours=2)),
        ("1d", timedelta(days=1)),
        ("90m", timedelta(minutes=90)),
        ("1h30m", timedelta(minutes=90)),
        ("1d2h3m4s", timedelta(days=1, hours=2, minutes=3, seconds=4)),
    ],
)
def test_parse_duration(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "5", "m", "5x", "-5m", "1.5h", "5 m", " 5m", "5M", "30m1h", "1h1h", "5 minutes"],
)
def test_parse_duration_rejects_malformed_text(text: str) -> None:
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration(text)


def test_parse_duration_rejects_overflow() -> None:
    with pytest.raises(ValueError, match="too large"):
        parse_duration("99999999999d")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (timedelta(0), "0s"),
        (timedelta(seconds=45), "45s"),
        (timedelta(minutes=90), "1h30m"),
        (timedelta(days=1, seconds=1), "1d1s"),
    ],
)
def test_format_duration(value: timedelta, expected: str) -> None:
    assert format_duration(value) == expected


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 61, 3599, 3600, 86_399, 86_400, 90_061, 10**7])
def test_format_and_parse_round_trip(seconds: int) -> None:
    value = timedelta(seconds=seconds)
    assert parse_duration(format_duration(value)) == value


@pytest.mark.parametrize(
    ("value", "message"),
    [(timedelta(seconds=-1), "negative"), (timedelta(milliseconds=1500), "resolution")],
)
def test_format_duration_rejects(value: timedelta, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        format_duration(value)
