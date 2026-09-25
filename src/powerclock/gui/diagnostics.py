"""The Diagnostics tab: PowerClock in the background, what works on this computer and how to
fix the rest, the permission to turn the computer on (the root helper) and its test, and
PowerClock in the menu and at login."""

import asyncio
import getpass
from collections.abc import Awaitable, Callable
from datetime import datetime
from types import ModuleType
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from powerclock.cli.format import local, relative, span
from powerclock.config import Paths
from powerclock.doctor import WakeTest, run_wake_test, verdict_message
from powerclock.gui.client import DaemonLink
from powerclock.gui.energy import EnergyBox
from powerclock.gui.icons import themed
from powerclock.gui.maintenance import MaintenanceBox
from powerclock.gui.summary import not_running_text, test_mode_text
from powerclock.gui.tasks import ask, inform, show_error, spawn
from powerclock.i18n import _
from powerclock.install.autostart import desktop_module
from powerclock.install.helper import helper_module
from powerclock.install.service import service_module
from powerclock.install.steps import Setup
from powerclock.labels import capability_label
from powerclock.platform import dry_run_requested, get_backend
from powerclock.platform.base import NotSupported

WAKE_TEST_SECONDS = 120
HANDS_OFF = 10  # seconds between confirming the wake test and suspending

RunElevated = Callable[[list[str]], Awaitable[int]]
WakeTester = Callable[[Callable[[datetime], None]], Awaitable[WakeTest]]


async def run_elevated(command: list[str]) -> int:
    """Run a command (pkexec…) without blocking the GUI; returns its exit code."""
    process = await asyncio.create_subprocess_exec(*command)
    return await process.wait()


async def test_wake(announce: Callable[[datetime], None]) -> WakeTest:
    backend = get_backend()
    try:
        return await run_wake_test(backend, WAKE_TEST_SECONDS, announce=announce)
    finally:
        await backend.close()


def _module(factory: Callable[[], ModuleType]) -> ModuleType | None:
    try:
        return factory()
    except NotSupported:
        return None


class DiagnosticsTab(QWidget):
    def __init__(
        self,
        link: DaemonLink,
        *,
        desktop: ModuleType | None = None,
        service: ModuleType | None = None,
        helper: ModuleType | None = None,
        elevate: RunElevated = run_elevated,
        wake_tester: WakeTester = test_wake,
        maintenance: MaintenanceBox | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._link = link
        self._desktop = desktop or _module(desktop_module)
        self._service = service or _module(service_module)
        self._helper = helper or _module(helper_module)
        self._elevate = elevate
        self._wake_tester = wake_tester
        self.dialog: QDialog | None = None

        # The daemon
        self.daemon = QLabel()
        self.daemon.setWordWrap(True)
        self.start_service = QPushButton(themed("media-playback-start"), _("Start PowerClock"))
        self.start_service.clicked.connect(self.start_daemon)
        daemon_box = QGroupBox(_("PowerClock in the background"))
        daemon_row = QHBoxLayout(daemon_box)
        daemon_row.addWidget(self.daemon, 1)
        daemon_row.addWidget(self.start_service)

        # What works here
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([_("Function"), _("Detail"), _("How to fix")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        refresh = QPushButton(themed("view-refresh"), _("Check again"))
        refresh.clicked.connect(self.reload)
        checks_box = QGroupBox(_("What works on this computer"))
        checks = QVBoxLayout(checks_box)
        checks.addWidget(self.table)
        checks.addWidget(refresh, 0, Qt.AlignmentFlag.AlignRight)

        # Wake-ups
        self.alarm = QLabel()
        self.install_helper = QPushButton(
            themed("system-software-install"), _("Allow turning the computer on…")
        )
        self.install_helper.clicked.connect(self.open_helper_dialog)
        self.test_button = QPushButton(themed("chronometer"), _("Test a wake-up in 2 minutes…"))
        self.test_button.clicked.connect(self.confirm_wake_test)
        wake_box = QGroupBox(_("Turning on and waking up"))
        wake = QVBoxLayout(wake_box)
        wake.addWidget(self.alarm)
        wake_buttons = QHBoxLayout()
        wake_buttons.addWidget(self.install_helper)
        wake_buttons.addWidget(self.test_button)
        wake_buttons.addStretch(1)
        wake.addLayout(wake_buttons)

        # Desktop
        self.menu_box = QCheckBox(_("Show PowerClock in the applications menu"))
        self.login_box = QCheckBox(_("Start the tray icon when the session starts"))
        desktop_box = QGroupBox(_("Desktop"))
        desktop_layout = QVBoxLayout(desktop_box)
        desktop_layout.addWidget(self.menu_box)
        desktop_layout.addWidget(self.login_box)
        if self._desktop is None:
            desktop_box.setEnabled(False)
            desktop_box.setToolTip(_("Not available on this system yet"))
        else:
            self.menu_box.setChecked(self._desktop.in_menu())
            self.login_box.setChecked(self._desktop.at_login())
        self.menu_box.toggled.connect(lambda on: self._set_desktop("set_menu", on))
        self.login_box.toggled.connect(lambda on: self._set_desktop("set_login", on))

        self.energy = EnergyBox(link)  # tariff, consumption and price

        setup = Setup(service=self._service, helper=self._helper, desktop=self._desktop)
        self.maintenance = maintenance or MaintenanceBox(setup)

        layout = QVBoxLayout(self)
        layout.addWidget(daemon_box)
        layout.addWidget(checks_box, 1)
        layout.addWidget(wake_box)
        layout.addWidget(desktop_box)
        layout.addWidget(self.energy)
        layout.addWidget(self.maintenance)

        link.changed.connect(self.update_status)
        self.update_status()

    # ── Status ────────────────────────────────────────────────────────────────

    def update_status(self) -> None:
        link = self._link
        self.start_service.setVisible(not link.online and self._service is not None)
        if not link.online or link.health is None:
            self.daemon.setText(not_running_text() + (f"\n{link.error}" if link.error else ""))
        else:
            health = link.health
            parts = [
                f"powerclock {health['version']}",
                health["backend"],
                health["timezone"],
                _("running for {time}").format(time=span(health["uptime"])),
            ]
            text = " · ".join(parts)
            if health.get("dry_run"):
                text += "\n" + test_mode_text()
            for problem in health.get("rules_errors", []):
                text += "\n✘ rules.json: " + problem
            self.daemon.setText(text)
        wake = link.pending.get("wake") or {}
        if wake.get("error"):
            self.alarm.setText("✘ " + _("wake-up alarm") + ": " + wake["error"])
        elif wake.get("at"):
            self.alarm.setText(
                "⏰ "
                + _("Next wake-up alarm: {time} ({relative})").format(
                    time=local(wake["at"]), relative=relative(wake["at"])
                )
            )
        else:
            self.alarm.setText(_("No wake-up alarm programmed."))
        self.install_helper.setEnabled(self._helper is not None)
        self.energy.setEnabled(link.online)

    def reload(self) -> None:
        spawn(self._load(), self)

    async def _load(self) -> None:
        self.show_capabilities(await self._link.api.get("/capabilities"))
        self.energy.show_settings(await self._link.api.get("/settings"))

    def show_capabilities(self, rows: list[dict[str, Any]]) -> None:
        self.table.setRowCount(len(rows))
        for row, capability in enumerate(rows):
            mark = "✔" if capability["supported"] else "✘"
            name = QTableWidgetItem(f"{mark} {capability_label(capability['id'])}")
            name.setToolTip(capability["id"])
            color = "#27ae60" if capability["supported"] else "#da4453"
            name.setForeground(QBrush(QColor(color)))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(capability["detail"]))
            self.table.setItem(row, 2, QTableWidgetItem(capability.get("fix_hint") or ""))
        self.table.resizeRowsToContents()

    # ── The service ───────────────────────────────────────────────────────────

    def start_daemon(self) -> None:
        service = self._service
        if service is None:
            return
        spawn(self._start_daemon(service), self)

    async def _start_daemon(self, service: ModuleType) -> None:
        state = await asyncio.to_thread(service.status)
        if state.installed:
            await asyncio.to_thread(service.start)
            self._link.refresh()
            return
        dry_run = dry_run_requested()
        text = _(
            "This sets PowerClock to work in the background: "
            "it starts now and every time you log in."
        )
        if dry_run:
            text += "\n\n" + _("Test mode: PowerClock will not really turn anything off.")

        def install() -> None:
            spawn(self._install_service(service, dry_run), self)

        ask(self, text, install)

    async def _install_service(self, service: ModuleType, dry_run: bool) -> None:
        await asyncio.to_thread(lambda: service.install(dry_run=dry_run))
        self._link.refresh()

    # ── The helper ────────────────────────────────────────────────────────────

    def open_helper_dialog(self) -> None:
        if self._helper is not None:
            self.dialog = HelperDialog(self._helper, self._elevate, self)
            self.dialog.open()

    # ── The wake-up test ──────────────────────────────────────────────────────

    def confirm_wake_test(self) -> None:
        if dry_run_requested():
            inform(self, _("Test mode: the test would suspend the computer, so nothing was done."))
            return
        text = _(
            "This programs a wake-up in {seconds} s and suspends the computer now. "
            "Save your work and do not touch it until it wakes up by itself."
        ).format(seconds=WAKE_TEST_SECONDS)
        ask(self, text + "\n\n" + _("Suspend now?"), self._hands_off)

    def _hands_off(self) -> None:
        self.dialog = HandsOffDialog(self, self._run_wake_test)
        self.dialog.open()

    def _run_wake_test(self) -> None:
        self.test_button.setEnabled(False)
        spawn(self._wake_test(), self, on_error=self._wake_failed)

    async def _wake_test(self) -> None:
        result = await self._wake_tester(lambda _alarm: None)
        self.test_button.setEnabled(True)
        inform(self, verdict_message(result, local), warning=result.verdict != "ok")

    def _wake_failed(self, error: Exception) -> None:
        self.test_button.setEnabled(True)
        hint = getattr(error, "fix_hint", None)
        inform(self, f"{error}" + (f" ({hint})" if hint else ""), warning=True)

    # ── Desktop ───────────────────────────────────────────────────────────────

    def _set_desktop(self, function: str, on: bool) -> None:
        if self._desktop is None:
            return
        try:
            getattr(self._desktop, function)(on)
        except OSError as exc:
            show_error(exc, self)


class HelperDialog(QDialog):
    """Shows the exact commands that install the helper (the permission to turn the computer
    on), then runs them with pkexec, which asks for the password in a desktop window."""

    def __init__(
        self, helper: ModuleType, elevate: RunElevated, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._helper = helper
        self._elevate = elevate
        self.setWindowTitle(_("Allow turning the computer on"))
        intro = QLabel(
            _(
                "To turn the computer on at a time, PowerClock needs a small program that runs "
                "as administrator. It can only program the wake-up alarm. It is installed once; "
                "after that, no password is asked."
            )
        )
        intro.setWordWrap(True)
        self.unattended = QCheckBox(_("Also work when you are logged out"))
        self.unattended.setToolTip(
            _("PowerClock can turn the computer on and off even when nobody is logged in.")
        )
        self.commands = QPlainTextEdit()
        self.commands.setReadOnly(True)
        self.commands.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.result = QLabel()
        self.result.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.run_button = QPushButton(
            themed("dialog-password"), _("Install (asks for the password)")
        )
        buttons.addButton(self.run_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self.run_button.clicked.connect(self.install)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.unattended)
        layout.addWidget(QLabel(_("These commands run as administrator:")))
        layout.addWidget(self.commands, 1)
        layout.addWidget(self.result)
        layout.addWidget(buttons)
        self.resize(640, 360)
        self.unattended.toggled.connect(self._show_commands)
        self._show_commands()

    def command_list(self) -> list[list[str]]:
        user = getpass.getuser() if self.unattended.isChecked() else None
        rules_file = Paths.default().data / "50-powerclock-unattended.rules"
        return self._helper.install_commands(unattended_user=user, rules_file=rules_file)

    def _show_commands(self) -> None:
        self.commands.setPlainText("\n".join(self._helper.shell(c) for c in self.command_list()))

    def install(self) -> None:
        self.run_button.setEnabled(False)
        spawn(self._install(), self, on_error=self._failed)

    async def _install(self) -> None:
        code = await self._elevate(self._helper.elevated(self.command_list()))
        self.run_button.setEnabled(True)
        if code == 0:
            self.result.setText(
                "✔ "
                + _("Done: PowerClock can turn the computer on. Try it with «{test}».").format(
                    test=_("Test a wake-up in 2 minutes…").rstrip("…")
                )
            )
        else:
            self.result.setText("✘ " + _("Not installed (exit code {code}).").format(code=code))

    def _failed(self, error: Exception) -> None:
        self.run_button.setEnabled(True)
        self.result.setText(f"✘ {error}")


class HandsOffDialog(QDialog):
    """The seconds before the wake-up test suspends: a touchpad or a pointing stick can wake
    the computer up, so hands off."""

    def __init__(
        self, parent: QWidget | None, go: Callable[[], None], seconds: int = HANDS_OFF
    ) -> None:
        super().__init__(parent)
        self._go = go
        self._left = seconds
        self.setWindowTitle(_("Wake-up test"))
        self.label = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self._show()

    def tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.accept()
            self._go()
            return
        self._show()

    def reject(self) -> None:
        self._timer.stop()
        super().reject()

    def _show(self) -> None:
        self.label.setText(
            _("Suspending in {seconds} s: hands off the keyboard, touchpad and stick…").format(
                seconds=self._left
            )
        )
