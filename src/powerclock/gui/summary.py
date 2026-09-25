"""What PowerClock is up to, in a few words: the tray's icon, tooltip and menu, and the list
of quick actions. Pure functions of /pending, so they are easy to test."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from powerclock.cli.format import moment, relative, watch_detail
from powerclock.gui.icons import TrayState
from powerclock.i18n import _, can_cancel_text
from powerclock.labels import reason_label

QUICK_PREFIX = "quick-"
WAKE_FIRST = timedelta(minutes=5)  # a wake alarm this much before the next rule is "for it"


@dataclass(frozen=True)
class Item:
    """A quick action waiting to act: at a time, for a condition, or running."""

    rule_id: str
    name: str
    detail: str
    run_id: str | None = None  # set when it is already running (e.g. counting down)
    counting_down: bool = False
    watched: bool = False  # waits for a condition: it has no time to postpone


@dataclass(frozen=True)
class Summary:
    state: TrayState
    headline: str  # one line: the tray's tooltip and menu
    countdown: dict[str, Any] | None = None  # the run counting down, if any
    quick: list[Item] = field(default_factory=list)
    upcoming: int = 0  # timed or watched rules, quick or not
    title: str = ""  # the «Next» band: what…
    detail: str = ""  # …and when

    @property
    def can_cancel(self) -> bool:
        return self.countdown is not None or bool(self.quick)

    @property
    def can_postpone(self) -> bool:
        return self.countdown is not None or any(
            item.run_id is None and not item.watched for item in self.quick
        )


def summarize(online: bool, pending: dict[str, Any], now: datetime | None = None) -> Summary:
    if not online:
        text = _("PowerClock isn't running")
        return Summary("offline", text, title=text, detail=not_running_text())
    now = now or datetime.now(UTC)
    active = pending.get("active", [])
    upcoming = pending.get("next", [])
    watching = pending.get("watching", [])
    countdown = next((run for run in active if run.get("state") == "warning"), None)
    quick = quick_items(pending, now)
    total = len(upcoming) + len(watching)
    wake = moment((pending.get("wake") or {}).get("at"))
    if countdown is not None:
        text = countdown_text(countdown, now)
        deadline = moment(countdown.get("deadline"))
        seconds = max(0, round((deadline - now).total_seconds())) if deadline else 0
        detail = remaining_text(seconds)
        return Summary("countdown", text, countdown, quick, total, countdown["rule_name"], detail)
    first_at = moment(upcoming[0]["at"]) if upcoming else None
    if wake is not None and wake > now and (first_at is None or wake < first_at - WAKE_FIRST):
        title = _("Turn the computer on")
        when = f"{when_text(wake, now)} · {relative(wake, now)}"
        return Summary("wake", f"{title} · {relative(wake, now)}", None, quick, total, title, when)
    if upcoming:
        first = upcoming[0]
        headline = f"{first['name']} · {relative(first['at'], now)}"
        detail = f"{when_text(first['at'], now)} · {relative(first['at'], now)}"
        if wake is not None and first_at is not None and wake > first_at:
            detail += " · " + _("turns the computer back on {when}").format(
                when=when_text(wake, now)
            )
        return Summary("scheduled", headline, None, quick, total, first["name"], detail)
    if watching:
        detail = watch_detail(watching[0])
        headline = f"{watching[0]['name']} · {detail}"
        return Summary("watching", headline, None, quick, total, watching[0]["name"], detail)
    if active:
        name = active[0]["rule_name"]
        return Summary(
            "scheduled", f"{name} · {_('running')}", None, quick, total, name, _("running")
        )
    text = _("Nothing scheduled")
    return Summary(
        "idle", text, quick=quick, title=text, detail=_("Nothing will turn off or on by itself.")
    )


def not_running_text() -> str:
    return _("PowerClock isn't running. Your rules won't run until you start it.")


def test_mode_text() -> str:
    return _("Test mode: nothing really turns off or on; actions are only noted down.")


def when_text(value: str | datetime | None, now: datetime | None = None) -> str:
    """A moment for people: "today 23:30", "tomorrow 07:30" or "2026-10-02 07:30"."""
    when = moment(value)
    if when is None:
        return "-"
    here = when.astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    clock = here.strftime("%H:%M")
    if here.date() == today:
        return _("today {time}").format(time=clock)
    if here.date() == today + timedelta(days=1):
        return _("tomorrow {time}").format(time=clock)
    return here.strftime("%Y-%m-%d %H:%M")


def remaining_text(seconds: int) -> str:
    """The «Next» band during a countdown."""
    return _("acts in {seconds} s").format(seconds=seconds) + " · " + can_cancel_text()


def countdown_text(run: dict[str, Any], now: datetime | None = None) -> str:
    deadline = moment(run.get("deadline"))
    if deadline is None:
        return run["rule_name"]
    seconds = max(0, round((deadline - (now or datetime.now(UTC))).total_seconds()))
    return _("{rule}: acts in {seconds} s").format(rule=run["rule_name"], seconds=seconds)


def quick_items(pending: dict[str, Any], now: datetime | None = None) -> list[Item]:
    """Quick actions (created with powerclock shutdown…, the tray or the Quick tab) not done yet."""
    items: list[Item] = []
    seen: set[str] = set()
    for run in pending.get("active", []):
        if run["rule_id"].startswith(QUICK_PREFIX):
            counting = run.get("state") == "warning"
            detail = countdown_text(run, now) if counting else reason_label(run.get("reason"))
            detail = detail or _("running")
            items.append(Item(run["rule_id"], run["rule_name"], detail, run["id"], counting))
            seen.add(run["rule_id"])
    for entry in pending.get("next", []):
        if entry["rule_id"].startswith(QUICK_PREFIX) and entry["rule_id"] not in seen:
            detail = f"{when_text(entry['at'], now)} ({relative(entry['at'], now)})"
            items.append(Item(entry["rule_id"], entry["name"], detail))
    for watch in pending.get("watching", []):
        if watch["rule_id"].startswith(QUICK_PREFIX) and watch["rule_id"] not in seen:
            detail = watch_detail(watch)
            items.append(Item(watch["rule_id"], watch["name"], detail, watched=True))
    return items
