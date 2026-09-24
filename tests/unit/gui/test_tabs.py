"""Rules, History and Diagnostics tabs, the window and the controller."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from guisupport import pump
from powerclock.daemon.core import Daemon
from powerclock.doctor import WakeTest
from powerclock.engine.clock import FakeClock
from powerclock.gui.client import DaemonLink
from powerclock.gui.controller import Controller
from powerclock.gui.diagnostics import DiagnosticsTab, HandsOffDialog, HelperDialog
from powerclock.gui.history import HistoryTab
from powerclock.gui.rules import RulesTab
from powerclock.gui.window import MainWindow
from powerclock.platform.linux import helper

RULE = {
    "id": "backup",
    "name": "Backup",
    "trigger": {"type": "cron", "expr": "0 3 * * *"},
    "actions": [{"type": "notify", "title": "PowerClock"}],
}


def answer(box: QMessageBox, button: QMessageBox.StandardButton) -> None:
    box.done(button)


async def boxes(count: int = 1, seconds: float = 3.0) -> list[QMessageBox]:
    """The message boxes open once `count` of them are (some wait for a worker thread)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while len(open_boxes()) < count and loop.time() < deadline:
        await pump(10)
        await asyncio.sleep(0.01)
    return open_boxes()


def open_boxes() -> list[QMessageBox]:
    return [
        w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()
    ]


# ── Rules ─────────────────────────────────────────────────────────────────────


async def test_rules_tab(link: DaemonLink, errors: list[Exception]) -> None:
    await link.api.post("/rules", json=RULE)
    tab = RulesTab(link)
    tab.reload()
    await pump()
    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 1).text() == "Backup"
    assert tab.table.item(0, 2).text() == "Repeating (cron): 0 3 * * *"
    assert "03:00" in tab.table.item(0, 3).text()  # 03:00 in Madrid, the next day
    assert not tab.edit_button.isEnabled()
    tab.table.selectRow(0)
    assert tab.edit_button.isEnabled()

    tab.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)  # disable
    await pump()
    assert (await link.api.get("/rules/backup"))["enabled"] is False

    tab.run()
    await pump()
    [entry] = (await link.api.get("/history"))["runs"]
    assert (entry["rule_id"], entry["cause"]) == ("backup", "manual")

    tab.table.selectRow(0)
    tab.delete()
    [box] = await boxes()
    answer(box, QMessageBox.StandardButton.Yes)
    await pump()
    assert await link.api.get("/rules") == []
    assert tab.table.rowCount() == 0
    assert errors == []


async def test_rules_tab_opens_the_editor(link: DaemonLink) -> None:
    await link.api.post("/rules", json=RULE)
    tab = RulesTab(link)
    tab.reload()
    await pump()
    tab.table.selectRow(0)
    tab.edit()
    assert tab.editor is not None
    assert tab.editor.general.fields["name"].get() == "Backup"
    tab.editor.general.fields["name"].set("Nightly backup")
    tab.editor.save()
    await pump()
    assert tab.table.item(0, 1).text() == "Nightly backup"


# ── History ───────────────────────────────────────────────────────────────────


async def test_history_tab(link: DaemonLink) -> None:
    await link.api.post("/rules", json=RULE)
    await link.api.post("/rules/backup/run")
    await pump()
    tab = HistoryTab(link)
    tab.reload()
    await pump()
    assert tab.table.rowCount() == 1
    assert [tab.table.item(0, c).text() for c in (1, 2, 3)] == ["Backup", "done", "by hand"]
    tab.table.selectRow(0)
    assert "1. Show a notification: ok" in tab.steps.toPlainText()


# ── Diagnostics ───────────────────────────────────────────────────────────────


@dataclass
class ServiceState:
    installed: bool


class FakeService:
    def __init__(self, installed: bool) -> None:
        self.installed = installed
        self.calls: list[tuple[str, Any]] = []

    def status(self) -> ServiceState:
        return ServiceState(self.installed)

    def start(self) -> list[str]:
        self.calls.append(("start", None))
        return []

    def install(self, *, dry_run: bool) -> list[str]:
        self.calls.append(("install", dry_run))
        return []


class FakeDesktop:
    def __init__(self) -> None:
        self.menu = False
        self.login = True

    def in_menu(self) -> bool:
        return self.menu

    def at_login(self) -> bool:
        return self.login

    def set_menu(self, on: bool) -> list[str]:
        self.menu = on
        return []

    def set_login(self, on: bool) -> list[str]:
        self.login = on
        return []


def diagnostics(link: DaemonLink, **kwargs: Any) -> DiagnosticsTab:
    options: dict[str, Any] = {
        "desktop": FakeDesktop(),
        "service": FakeService(installed=True),
        "helper": helper,
    }
    options.update(kwargs)
    return DiagnosticsTab(link, **options)


async def test_capabilities_and_status(link: DaemonLink) -> None:
    tab = diagnostics(link)
    tab.reload()
    await pump()
    assert tab.table.rowCount() > 5
    assert tab.table.item(0, 0).text() == "✔ power.shutdown"
    assert "powerclock " in tab.daemon.text()
    assert tab.alarm.text() == "No wake-up alarm programmed."
    assert tab.start_service.isHidden()


async def test_desktop_checkboxes(link: DaemonLink) -> None:
    desktop = FakeDesktop()
    tab = diagnostics(link, desktop=desktop)
    assert (tab.menu_box.isChecked(), tab.login_box.isChecked()) == (False, True)
    tab.menu_box.setChecked(True)
    tab.login_box.setChecked(False)
    assert (desktop.menu, desktop.login) == (True, False)


async def test_start_the_service(link: DaemonLink, monkeypatch: pytest.MonkeyPatch) -> None:
    installed = FakeService(installed=True)
    tab = diagnostics(link, service=installed)
    tab.start_daemon()
    for _ in range(100):  # the service is asked in a worker thread
        if installed.calls:
            break
        await asyncio.sleep(0.01)
    assert installed.calls == [("start", None)]

    missing = FakeService(installed=False)
    tab = diagnostics(link, service=missing)
    tab.start_daemon()
    await pump()
    [box] = await boxes()  # installing asks first
    assert "starts now and every time you log in" in box.text()
    answer(box, QMessageBox.StandardButton.Yes)
    await pump()
    assert missing.calls == [
        ("install", True)
    ]  # POWERCLOCK_DRY_RUN=1 in the tests: a dry-run service


async def test_helper_dialog_shows_and_runs_the_commands(link: DaemonLink, tmp_path: Path) -> None:
    ran: list[list[str]] = []

    async def elevate(command: list[str]) -> int:
        ran.append(command)  # never executed for real
        return 0

    dialog = HelperDialog(helper, elevate)
    text = dialog.commands.toPlainText()
    assert "sudo install" in text
    assert "/usr/local/libexec/powerclock-helper" in text
    dialog.unattended.setChecked(True)
    assert "50-powerclock-unattended.rules" in dialog.commands.toPlainText()
    dialog.install()
    await pump()
    [command] = ran
    assert command[:3] == ["pkexec", "/bin/sh", "-c"]
    assert "sudo" not in command[3]
    assert command[3].count(" && ") == 2
    assert dialog.result.text().startswith("✔")


async def test_wake_test_in_dry_run_does_nothing(link: DaemonLink) -> None:
    called: list[bool] = []

    async def tester(announce: Any) -> WakeTest:
        called.append(True)
        raise AssertionError("must not run")

    tab = diagnostics(link, wake_tester=tester)
    tab.confirm_wake_test()
    [box] = await boxes()
    assert "Dry run" in box.text()
    box.close()
    assert called == []


async def test_wake_test_asks_counts_down_and_reports(
    link: DaemonLink, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("POWERCLOCK_DRY_RUN")
    alarm = datetime(2026, 9, 24, 10, 2, tzinfo=UTC)

    async def tester(announce: Any) -> WakeTest:
        return WakeTest(alarm, slept=True, resumed_at=alarm, alarm_left=False)

    tab = diagnostics(link, wake_tester=tester)
    tab.confirm_wake_test()
    [box] = await boxes()
    assert "suspends the computer now" in box.text()
    answer(box, QMessageBox.StandardButton.Yes)
    hands_off = tab.dialog
    assert isinstance(hands_off, HandsOffDialog)
    assert "Suspending in 10 s" in hands_off.label.text()
    for _ in range(10):
        hands_off.tick()
    await pump()
    [report] = await boxes()
    assert report.text().startswith("✔ Woke up by itself")
    report.close()


async def test_wake_test_can_be_cancelled(link: DaemonLink) -> None:
    dialog = HandsOffDialog(None, lambda: None)
    assert dialog._timer.isActive()
    dialog.reject()
    assert not dialog._timer.isActive()  # nothing suspends


# ── Window and controller ─────────────────────────────────────────────────────


async def test_window_tabs_and_offline_banner(link: DaemonLink) -> None:
    window = MainWindow(link)
    assert window.banner.isHidden()
    window.show_tab("history")
    assert window.tabs.currentWidget() is window.history
    link._offline("gone")
    assert not window.banner.isHidden()
    assert window.statusBar().currentMessage() == "The PowerClock daemon is not running"
    window.close()


async def test_controller_without_tray(link: DaemonLink, daemon: Daemon) -> None:
    quits: list[bool] = []
    app = SimpleNamespace(quit=lambda: quits.append(True))
    controller = Controller(app, api=link.api, stream=None, tray=False)  # type: ignore[arg-type]
    controller.start(show_window=False)
    await pump()
    assert controller.window is not None  # without a tray the window is the app
    controller.on_request("show")
    controller.window.close()
    await pump()
    assert controller.window is None
    assert quits == [True]
    await controller.stop()


async def test_controller_with_tray(link: DaemonLink, clock: FakeClock) -> None:
    app = SimpleNamespace(quit=lambda: None)
    controller = Controller(app, api=link.api, stream=None, tray=True)  # type: ignore[arg-type]
    controller.start(show_window=False)
    await pump()
    assert controller.window is None  # only the tray icon
    controller.on_request("show")
    assert controller.window is not None
    controller.window.close()
    await pump()
    assert controller.window is None
    await controller.stop()
