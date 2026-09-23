from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter

from kse.engine.clock import FakeClock
from kse.engine.evaluator import Evaluator
from kse.models import Predicate
from kse.sensors.fake import FakeSensors
from support import MADRID

PREDICATE = TypeAdapter(Predicate)
MEDIA = {"type": "media_playing"}
SSH = {"type": "ssh_session"}


def predicate(data: dict[str, Any]) -> Predicate:
    return PREDICATE.validate_python(data)


async def evaluate(data: dict[str, Any], *, media: bool | None, ssh: bool | None) -> bool | None:
    sensors = FakeSensors({"media_playing": media, "ssh_session": ssh})
    clock = FakeClock(datetime(2026, 9, 24, 8, 0, tzinfo=UTC))
    return await Evaluator(sensors, clock).evaluate(predicate(data), MADRID)


@pytest.mark.parametrize(
    ("media", "ssh", "all_", "any_"),
    [
        (True, True, True, True),
        (True, False, False, True),
        (False, False, False, False),
        (True, None, None, True),
        (False, None, False, None),
        (None, None, None, None),
    ],
)
async def test_all_and_any_follow_three_valued_logic(
    media: bool | None, ssh: bool | None, all_: bool | None, any_: bool | None
) -> None:
    assert await evaluate({"all": [MEDIA, SSH]}, media=media, ssh=ssh) is all_
    assert await evaluate({"any": [MEDIA, SSH]}, media=media, ssh=ssh) is any_


@pytest.mark.parametrize(("value", "expected"), [(True, False), (False, True), (None, None)])
async def test_not(value: bool | None, expected: bool | None) -> None:
    assert await evaluate({"not": MEDIA}, media=value, ssh=None) is expected


async def test_short_circuit(evaluator: Evaluator, sensors: FakeSensors) -> None:
    sensors.values = {"media_playing": False, "ssh_session": True}
    assert await evaluator.evaluate(predicate({"all": [MEDIA, SSH]}), MADRID) is False
    assert [p.type for p in sensors.checked] == ["media_playing"]


def window(start: str, end: str) -> Predicate:
    return predicate({"type": "time_window", "start": start, "end": end})


@pytest.mark.parametrize(
    ("utc_time", "start", "end", "expected"),
    [
        ((8, 0), "09:00", "11:00", True),  # 10:00 in Madrid
        ((8, 0), "10:00", "11:00", True),  # start is inclusive
        ((8, 0), "09:00", "10:00", False),  # end is exclusive
        ((8, 0), "22:00", "07:00", False),
        ((21, 30), "22:00", "07:00", True),  # 23:30 in Madrid
        ((4, 59), "22:00", "07:00", True),  # 06:59
        ((5, 0), "22:00", "07:00", False),  # 07:00
    ],
)
async def test_time_window_in_the_rule_time_zone(
    sensors: FakeSensors, utc_time: tuple[int, int], start: str, end: str, expected: bool
) -> None:
    clock = FakeClock(datetime(2026, 9, 24, *utc_time, tzinfo=UTC))
    assert await Evaluator(sensors, clock).evaluate(window(start, end), MADRID) is expected


async def test_time_window_depends_on_the_time_zone(evaluator: Evaluator) -> None:
    # 08:00 UTC is 10:00 in Madrid
    assert await evaluator.evaluate(window("09:30", "10:30"), MADRID) is True
    assert await evaluator.evaluate(window("09:30", "10:30"), UTC) is False


async def test_weekday_in_the_rule_time_zone(sensors: FakeSensors) -> None:
    # Thursday 23:30 UTC is already Friday 01:30 in Madrid
    clock = FakeClock(datetime(2026, 9, 24, 23, 30, tzinfo=UTC))
    evaluator = Evaluator(sensors, clock)
    friday = predicate({"type": "weekday", "days": ["fri"]})
    assert await evaluator.evaluate(friday, MADRID) is True
    assert await evaluator.evaluate(friday, UTC) is False


async def test_sensor_predicates_go_to_the_sensors(
    evaluator: Evaluator, sensors: FakeSensors
) -> None:
    idle = predicate({"type": "idle", "for": "10m"})
    assert await evaluator.evaluate(idle, MADRID) is None  # unknown by default
    sensors.values["idle"] = True
    assert await evaluator.evaluate(idle, MADRID) is True
    assert sensors.checked == [idle, idle]


async def test_first_true(evaluator: Evaluator, sensors: FakeSensors) -> None:
    sensors.values = {"media_playing": None, "ssh_session": True}
    guards = [predicate(MEDIA), predicate(SSH)]
    assert await evaluator.first_true(guards, MADRID) == guards[1]
    sensors.values["ssh_session"] = False
    assert await evaluator.first_true(guards, MADRID) is None
