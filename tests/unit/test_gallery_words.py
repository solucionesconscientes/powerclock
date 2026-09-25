"""Schedules and steps in words, and the gallery's templates (M15)."""

import pytest

from powerclock.gallery import groups, templates
from powerclock.labels import cron_words, describe_step, describe_trigger
from powerclock.models import Rule


@pytest.mark.parametrize(
    ("expr", "words"),
    [
        ("0 3 * * *", "every day at 03:00"),
        ("30 7 * * 1-5", "on weekdays at 07:30"),
        ("0 10 * * 0,6", "on weekends at 10:00"),
        ("0 20 * * 1,4", "Mon, Thu at 20:00"),
        ("0 9 * * 2-3", "Tue, Wed at 09:00"),
        ("0 8 * * 7", "Sun at 08:00"),
        ("15 9 1 * *", "on day 1 of every month at 09:15"),
        ("*/15 * * * *", "every 15 minutes"),
        ("0 */2 * * *", "every 2 hours"),
        ("5 * * * *", "every hour at minute 5"),
        ("@daily", None),  # shown as it is
        ("0 3 * 1 *", None),
        ("0 3 * * MON", None),
        ("0 3 1 * 1", None),
        ("0 3 * * 5-1", None),
    ],
)
def test_cron_in_words(expr: str, words: str | None) -> None:
    assert cron_words(expr) == words


def test_cron_trigger_in_words() -> None:
    assert describe_trigger({"type": "cron", "expr": "0 3 * * *"}) == "Repeats: every day at 03:00"
    assert describe_trigger({"type": "cron", "expr": "@daily"}) == ("Repeats on a schedule: @daily")


@pytest.mark.parametrize(
    ("step", "words"),
    [
        ({"type": "power", "action": "suspend"}, "Suspend"),
        ({"type": "run", "cmd": ["/home/me/bin/backup.sh", "--full"]}, "run backup.sh"),
        ({"type": "run", "cmd": ["tar czf /tmp/x.tgz ~"], "shell": True}, "run tar"),
        ({"type": "launch", "app": "vlc"}, "open vlc"),
        ({"type": "notify", "title": "Hi"}, "notify: Hi"),
        ({"type": "wait_until", "condition": {"type": "media_playing"}}, None),
        ({"type": "volume", "level": 30}, "Set the volume"),
    ],
)
def test_steps_in_words(step: dict[str, object], words: str | None) -> None:
    text = describe_step(step)
    assert text == words if words else text.startswith("wait until: ")


def test_every_template_is_a_valid_rule() -> None:
    found = templates()
    keys = {key for key, _name in groups()}
    assert len(found) >= 15
    assert len({t.id for t in found}) == len(found)
    for template in found:
        assert template.group in keys, template.id
        assert template.title
        assert template.description
        Rule.model_validate({"id": "from-the-gallery", **template.rule})
    assert {t.group for t in found} == keys  # no empty group
    assert [t.id for t in found if t.needs == "tariff"] == ["cheap-hours"]
