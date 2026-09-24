from datetime import UTC, datetime, timedelta

import pytest

from powerclock.engine.scheduler import next_fire
from powerclock.models import AtTrigger, CountdownTrigger, CronTrigger, Idle, ManualTrigger
from support import MADRID, START


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def cron(expr: str) -> CronTrigger:
    return CronTrigger(expr=expr)


def test_at() -> None:
    trigger = AtTrigger(when=datetime.fromisoformat("2026-09-24T12:00:00+02:00"))
    assert next_fire(trigger, START, MADRID) == utc(2026, 9, 24, 10, 0)
    assert next_fire(trigger, utc(2026, 9, 24, 10, 0), MADRID) is None  # strictly after


def test_countdown_counts_from_when_it_was_armed() -> None:
    armed = CountdownTrigger(duration=timedelta(minutes=30), armed_at=START)
    assert next_fire(armed, START, MADRID) == START + timedelta(minutes=30)
    assert next_fire(armed, START + timedelta(hours=1), MADRID) is None
    unarmed = CountdownTrigger(duration=timedelta(minutes=30))
    assert next_fire(unarmed, START, MADRID) is None


@pytest.mark.parametrize("trigger", [ManualTrigger(), Idle(for_=timedelta(minutes=5))])
def test_non_time_triggers_never_fire_on_their_own(trigger: ManualTrigger | Idle) -> None:
    assert next_fire(trigger, START, MADRID) is None


def test_cron_uses_the_rule_time_zone() -> None:
    # START is 08:00 UTC = 10:00 in Madrid (CEST, UTC+2)
    assert next_fire(cron("0 11 * * *"), START, MADRID) == utc(2026, 9, 24, 9, 0)
    assert next_fire(cron("0 11 * * *"), START, UTC) == utc(2026, 9, 24, 11, 0)


def test_cron_weekdays_and_nicknames() -> None:
    # 2026-09-24 is a Thursday: the next weekday-only 07:30 after 10:00 is Friday
    assert next_fire(cron("30 7 * * 1-5"), START, MADRID) == utc(2026, 9, 25, 5, 30)
    assert next_fire(cron("@daily"), START, MADRID) == utc(2026, 9, 24, 22, 0)


def test_cron_that_never_matches() -> None:
    assert next_fire(cron("0 0 30 2 *"), START, MADRID) is None


def test_cron_daily_time_keeps_the_local_hour_across_dst_end() -> None:
    # 2026-10-25: Madrid goes from UTC+2 to UTC+1 at 03:00 local
    after = utc(2026, 10, 24, 12, 0)
    first = next_fire(cron("0 3 * * *"), after, MADRID)
    assert first == utc(2026, 10, 25, 2, 0)  # 03:00 CET
    assert next_fire(cron("0 3 * * *"), first, MADRID) == utc(2026, 10, 26, 2, 0)


def test_cron_in_the_repeated_hour_fires_once() -> None:
    # 02:30 happens twice on 2026-10-25 (00:30 UTC in CEST and 01:30 UTC in CET)
    first = next_fire(cron("30 2 * * *"), utc(2026, 10, 24, 12, 0), MADRID)
    assert first == utc(2026, 10, 25, 0, 30)
    assert next_fire(cron("30 2 * * *"), first, MADRID) == utc(2026, 10, 26, 1, 30)
    # Asked during the second pass of the repeated hour: no second run that day
    assert next_fire(cron("30 2 * * *"), utc(2026, 10, 25, 1, 10), MADRID) == utc(
        2026, 10, 26, 1, 30
    )


def test_cron_in_the_skipped_hour_moves_forward() -> None:
    # 2026-03-29: 02:00 → 03:00 in Madrid; 02:30 does not exist and runs at 03:30 CEST
    first = next_fire(cron("30 2 * * *"), utc(2026, 3, 28, 12, 0), MADRID)
    assert first == utc(2026, 3, 29, 1, 30)
    assert first.astimezone(MADRID).hour == 3
    assert next_fire(cron("30 2 * * *"), first, MADRID) == utc(2026, 3, 30, 0, 30)


def test_cron_every_15_minutes_across_the_skipped_hour_has_no_duplicates() -> None:
    fires = []
    when = utc(2026, 3, 29, 0, 40)  # 01:40 CET
    for _ in range(6):
        when = next_fire(cron("*/15 * * * *"), when, MADRID)
        assert when is not None
        fires.append(when)
    assert fires == [
        utc(2026, 3, 29, 0, 45),  # 01:45 CET
        utc(2026, 3, 29, 1, 0),  # 03:00 CEST (02:00 does not exist)
        utc(2026, 3, 29, 1, 15),
        utc(2026, 3, 29, 1, 30),
        utc(2026, 3, 29, 1, 45),
        utc(2026, 3, 29, 2, 0),
    ]
