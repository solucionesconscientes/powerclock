"""The Quick tab, the tray menu and the countdown dialog, clicked through against a daemon
with a fake backend: power actions are only recorded."""

from typing import Any

import pytest

from guisupport import pump
from powerclock.engine.clock import FakeClock
from powerclock.gui.client import DaemonLink
from powerclock.gui.countdown import Countdowns
from powerclock.gui.quick import QuickTab
from powerclock.gui.tray import Tray, quick_now
from powerclock.platform.base import PowerAction
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings


def names(link: DaemonLink) -> list[str]:
    return [item["name"] for item in [*link.pending["next"], *link.pending["watching"]]]


# ── Quick tab ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("action", "when", "setup", "expected"),
    [
        ("shutdown", "now", None, {"action": "shutdown", "warning": "1m"}),
        ("reboot", "in", lambda t: t.in_.setText("45m"), {"action": "reboot", "in": "45m"}),
        ("suspend", "idle", lambda t: t.idle.setText("20m"), {"when_idle": "20m"}),
        ("shutdown", "exits", lambda t: t.exits.setEditText("ffmpeg"), {"when_exits": "ffmpeg"}),
        ("shutdown", "cpu", lambda t: t.cpu.setValue(15), {"when_cpu_below": 15.0, "for": "5m"}),
        (
            "shutdown",
            "net",
            lambda t: (t.net.setValue(80), t.net_for.setText("10m")),
            {"when_net_below": 80.0, "for": "10m"},
        ),
    ],
)
async def test_quick_payloads(
    link: DaemonLink, action: str, when: str, setup: Any, expected: dict[str, Any]
) -> None:
    tab = QuickTab(link)
    tab.select(PowerAction(action), when)
    if setup is not None:
        setup(tab)
    payload = tab.payload()
    assert expected.items() <= payload.items()


async def test_quick_options(link: DaemonLink) -> None:
    tab = QuickTab(link)
    tab.select(PowerAction.SUSPEND, "at")
    tab.force.setChecked(True)
    tab.warning.setText("2m")
    tab.wake.setChecked(True)
    payload = tab.payload()
    assert payload["mode"] == "force"
    assert payload["warning"] == "2m"
    assert payload["wake_at"] == "07:30"
    assert payload["at"].endswith(("+00:00", "Z")) or "+" in payload["at"]


@pytest.mark.parametrize(
    ("action", "when", "button"),
    [
        (PowerAction.SHUTDOWN, "now", "Shut down now"),
        (PowerAction.SHUTDOWN, "at", "Schedule shutdown"),
        (PowerAction.SUSPEND, "idle", "Schedule suspend"),
        ("run", "now", "Run now"),
        ("run", "in", "Schedule the program"),
    ],
)
async def test_the_button_says_what_it_will_do(
    link: DaemonLink, action: PowerAction | str, when: str, button: str
) -> None:
    tab = QuickTab(link)
    tab.select(action, when)
    assert tab.ok.text() == button


async def test_run_a_program(link: DaemonLink) -> None:
    tab = QuickTab(link)
    tab.select("run", "in")
    with pytest.raises(ValueError, match="program to run"):
        tab.payload()
    tab.command.setText("backup.sh --full 'my dir'")
    tab.wake_to_run.setChecked(True)
    payload = tab.payload()
    assert payload["command"] == ["backup.sh", "--full", "my dir"]
    assert payload["wake"] is True
    assert "action" not in payload


async def test_wrong_input_is_explained(link: DaemonLink) -> None:
    tab = QuickTab(link)
    tab.select(PowerAction.SHUTDOWN, "in")
    tab.in_.setText("soon")
    tab.submit()
    assert "not a valid duration" in tab.status.text()
    tab.select(PowerAction.SHUTDOWN, "exits")
    tab.exits.setEditText("")
    tab.submit()
    assert "program to wait for" in tab.status.text()


async def test_submit_cancel_and_postpone(link: DaemonLink, errors: list[Exception]) -> None:
    tab = QuickTab(link)
    tab.select(PowerAction.SHUTDOWN, "in")
    tab.in_.setText("30m")
    tab.submit()
    await pump()
    assert tab.status.text() == "✔ Shut down in 30m"
    tab.select(PowerAction.SUSPEND, "idle")
    tab.submit()
    await pump()
    assert names(link) == ["Shut down in 30m", "Suspend after 20m without use"]
    assert tab.pending.rowCount() == 2
    timed = tab.pending.cellWidget(0, 2)
    watched = tab.pending.cellWidget(1, 2)
    assert len(timed.findChildren(type(tab.ok))) == 2  # Cancel and +10 min
    assert len(watched.findChildren(type(tab.ok))) == 1  # Cancel only
    postpone = timed.findChildren(type(tab.ok))[1]
    postpone.click()
    await pump()
    assert link.pending["next"][0]["at"] == "2026-09-24T08:40:00Z"
    watched.findChildren(type(tab.ok))[0].click()
    await pump()
    assert names(link) == ["Shut down in 30m"]
    assert errors == []


async def test_errors_from_the_daemon_are_shown(link: DaemonLink) -> None:
    tab = QuickTab(link)
    tab.select(PowerAction.SHUTDOWN, "exits")
    tab.exits.setEditText("0")  # not a valid PID
    tab.submit()
    await pump()
    assert "greater than 0" in tab.status.text()
    assert tab.ok.isEnabled()


# ── Tray ──────────────────────────────────────────────────────────────────────


def tray_for(link: DaemonLink) -> Tray:
    return Tray(link, show_window=lambda _tab: None, quit_app=lambda: None)


async def test_tray_follows_the_daemon(link: DaemonLink) -> None:
    tray = tray_for(link)
    assert tray.summary.state == "idle"
    assert not tray.cancel.isEnabled()
    await link.api.post("/quick", json={"action": "shutdown", "in": "2h"})
    await pump()
    assert tray.summary.state == "scheduled"
    assert tray.headline.text().startswith("Shut down in 2h")
    assert tray.cancel.isEnabled()
    assert tray.postpone.isEnabled()
    tray.cancel.trigger()
    await pump()
    assert tray.summary.state == "idle"


async def test_tray_actions_now(
    link: DaemonLink, fake: FakePlatform, clock: FakeClock, errors: list[Exception]
) -> None:
    assert quick_now(PowerAction.LOCK) == {"action": "lock", "warning": "0s"}
    assert quick_now(PowerAction.SHUTDOWN) == {"action": "shutdown"}
    tray = tray_for(link)
    tray.actions[PowerAction.LOCK].trigger()
    await pump()
    assert [call.args[0] for call in fake.calls_to("power")] == [PowerAction.LOCK]
    tray.actions[PowerAction.SHUTDOWN].trigger()
    await pump()
    assert tray.summary.state == "countdown"  # 60 s to cancel it
    tray.cancel.trigger()
    await pump()
    await clock.advance(120)
    assert [call.args[0] for call in fake.calls_to("power")] == [PowerAction.LOCK]
    assert errors == []


# ── Countdown dialog ──────────────────────────────────────────────────────────


async def test_countdown_dialog_cancel(
    link: DaemonLink, fake: FakePlatform, clock: FakeClock
) -> None:
    countdowns = Countdowns(link)
    await link.api.post("/quick", json={"action": "reboot"})
    await pump()
    [dialog] = countdowns.dialogs.values()
    assert dialog.rule.text() == "Restart · You can cancel it until the last second."
    assert "The computer will restart in" in dialog.headline.text()
    dialog.cancel_button.click()
    await pump()
    assert countdowns.dialogs == {}
    await clock.advance(120)
    assert fake.calls_to("power") == []


async def test_countdown_dialog_postpone(link: DaemonLink, clock: FakeClock) -> None:
    countdowns = Countdowns(link)
    await link.api.post("/quick", json={"action": "suspend", "warning": "30s"})
    await pump()
    [dialog] = countdowns.dialogs.values()
    before = dialog._deadline
    dialog.postpone_button.click()
    await pump()
    assert (dialog._deadline - before).total_seconds() == 600
    [active] = link.pending["active"]
    assert active["state"] == "warning"


async def test_countdown_dialog_when_the_gui_starts_late(
    link: DaemonLink, readings: FakeReadings
) -> None:
    await link.api.post("/quick", json={"action": "hibernate"})
    await pump()
    countdowns = Countdowns(link)  # the GUI starts during the countdown
    link.refresh()
    await pump()
    [dialog] = countdowns.dialogs.values()
    assert "will hibernate in" in dialog.headline.text()  # the action comes from the rule
    assert dialog.rule.text().startswith("Hibernate · ")
