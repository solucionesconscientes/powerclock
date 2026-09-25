"""What the tray and the Quick tab say, from /pending (pure functions)."""

from datetime import UTC, datetime
from typing import Any

from powerclock.gui.summary import quick_items, summarize, when_text

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


def pending(**parts: Any) -> dict[str, Any]:
    return {"next": [], "active": [], "watching": [], "wake": {}, **parts}


def test_offline_and_idle() -> None:
    assert summarize(False, pending(), NOW).state == "offline"
    idle = summarize(True, pending(), NOW)
    assert (idle.state, idle.headline, idle.can_cancel) == ("idle", "Nothing scheduled", False)


def test_next_timed_action() -> None:
    summary = summarize(
        True,
        pending(
            next=[
                {"rule_id": "quick-1", "name": "Shut down at 23:30", "at": "2026-09-24T21:30:00Z"}
            ]
        ),
        NOW,
    )
    assert summary.state == "scheduled"
    assert summary.headline == "Shut down at 23:30 · in 13h 30m"
    assert (summary.can_cancel, summary.can_postpone) == (True, True)
    [item] = summary.quick
    assert item.detail.endswith("(in 13h 30m)")  # the day and time depend on the time zone


def test_watched_quick_action_cannot_be_postponed() -> None:
    watch = {
        "rule_id": "quick-2",
        "name": "Suspend after 20m without use",
        "trigger": {"type": "idle", "for": "20m"},
        "state": False,
        "armed": True,
        "value": 65.0,
        "measured": None,
        "checked_at": "2026-09-24T08:00:00Z",
    }
    summary = summarize(True, pending(watching=[watch]), NOW)
    assert summary.headline == "Suspend after 20m without use · idle for 1m 05s"
    [item] = summary.quick
    assert item.watched
    assert (summary.can_cancel, summary.can_postpone) == (True, False)


def test_countdown_comes_first() -> None:
    run = {
        "id": "run1",
        "rule_id": "quick-3",
        "rule_name": "Restart",
        "state": "warning",
        "deadline": "2026-09-24T08:00:42Z",
    }
    summary = summarize(True, pending(active=[run]), NOW)
    assert (summary.state, summary.headline) == ("countdown", "Restart: acts in 42 s")
    [item] = quick_items(pending(active=[run]), NOW)
    assert (item.run_id, item.counting_down) == ("run1", True)
    assert summary.can_postpone


def test_rules_that_are_not_quick_actions_are_not_listed() -> None:
    entry = {"rule_id": "backup", "name": "Backup", "at": "2026-09-25T01:00:00Z"}
    summary = summarize(True, pending(next=[entry]), NOW)
    assert summary.state == "scheduled"
    assert summary.quick == []
    assert not summary.can_cancel


def test_when_text() -> None:
    today = datetime.now(UTC).astimezone().replace(hour=23, minute=30, second=0, microsecond=0)
    assert when_text(today) == "today 23:30"
    assert when_text(None) == "-"
    assert when_text(datetime(2020, 1, 2, 3, 4).astimezone()) == "2020-01-02 03:04"  # local time
