"""PowerClock itself, in the Diagnostics tab: its version, updates and uninstalling."""

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from powerclock import __version__
from powerclock.gui.icons import themed
from powerclock.gui.setup import RunRoot, pkexec_runner
from powerclock.gui.tasks import inform, spawn
from powerclock.i18n import _
from powerclock.install import program
from powerclock.install.steps import Setup

Latest = Callable[[], Awaitable[str]]
Run = Callable[[list[str]], int]  # blocking: runs in a worker thread


def run_command(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def restart_gui() -> None:
    """Replace this process with the (updated) PowerClock window."""
    executable = Path(sys.executable).parent / "powerclock-gui"
    os.execv(str(executable), [str(executable)])


class MaintenanceBox(QGroupBox):
    def __init__(
        self,
        setup: Setup,
        *,
        latest: Latest = program.latest_version,
        commands: Callable[[], program.Commands] = program.commands,
        run: Run = run_command,
        run_root: RunRoot | None = None,
        restart: Callable[[], None] = restart_gui,
        quit_app: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("PowerClock", parent)
        self._setup = setup
        self._latest = latest
        self._commands = commands
        self._run = run
        self._run_root = run_root or pkexec_runner(setup)
        self._restart = restart
        self._quit = quit_app or self._quit_application
        self.latest: str | None = None

        how = {
            "installer": _("installed with the PowerClock installer"),
            "pipx": _("installed with pipx"),
            "other": _("installed by hand or from the source code"),
        }[program.installed_by()]
        self.version = QLabel(f"PowerClock {__version__} · {how}")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.check_button = QPushButton(themed("view-refresh"), _("Check for updates"))
        self.update_button = QPushButton(themed("system-software-update"), _("Update"))
        self.update_button.hide()
        self.uninstall_button = QPushButton(themed("edit-delete"), _("Uninstall PowerClock…"))
        self.check_button.clicked.connect(self.check)
        self.update_button.clicked.connect(self.update_now)
        self.uninstall_button.clicked.connect(self.confirm_uninstall)

        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.update_button)
        buttons.addStretch(1)
        buttons.addWidget(self.uninstall_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.version)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.status.hide()

    # ── Updates ───────────────────────────────────────────────────────────────

    def check(self) -> None:
        self.check_button.setEnabled(False)
        self._say(_("Checking…"))
        spawn(self._check(), self, on_error=self._check_failed)

    async def _check(self) -> None:
        latest = await self._latest()
        self.check_button.setEnabled(True)
        if not program.newer(latest):
            self._say(_("You have the newest version."))
            return
        self.latest = latest
        if self._commands().upgrade is None:
            self._say(
                _("PowerClock {version} is out; update it the way you installed it.").format(
                    version=latest
                )
            )
            return
        self._say(_("PowerClock {version} is out.").format(version=latest))
        self.update_button.setText(_("Update to {version}").format(version=latest))
        self.update_button.show()

    def _check_failed(self, error: Exception) -> None:
        self.check_button.setEnabled(True)
        self._say(_("Could not check for updates: {error}").format(error=error))

    def update_now(self) -> None:
        upgrade = self._commands().upgrade
        if upgrade is None:
            return
        self.update_button.setEnabled(False)
        self._say(_("Updating…"))
        spawn(self._update(upgrade), self, on_error=self._check_failed)

    async def _update(self, upgrade: list[str]) -> None:
        if await asyncio.to_thread(self._run, upgrade) != 0:
            self.update_button.setEnabled(True)
            self._say(_("The update failed."))
            return
        service = self._setup.service
        if service is not None and (await asyncio.to_thread(service.status)).installed:
            await asyncio.to_thread(service.restart)  # the daemon runs the new version
        self._say(_("Updated: PowerClock restarts."))
        self._restart()

    # ── Uninstall ─────────────────────────────────────────────────────────────

    def confirm_uninstall(self) -> QMessageBox:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            _("Uninstall PowerClock"),
            _(
                "This removes the service, the menu entry, the start with the session, the "
                "wake-up helper (asks for your password) and the program."
            ),
            parent=self,
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        purge = QCheckBox(_("Also delete my rules and history"))
        box.setCheckBox(purge)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        def answered(result: int) -> None:
            if result == QMessageBox.StandardButton.Yes:
                self.uninstall(remove_data=purge.isChecked())

        box.finished.connect(answered)
        box.open()
        return box

    def uninstall(self, *, remove_data: bool) -> None:
        self.uninstall_button.setEnabled(False)
        self._say(_("Uninstalling…"))
        spawn(self._uninstall(remove_data), self, on_error=self._check_failed)

    async def _uninstall(self, remove_data: bool) -> None:
        report = await asyncio.to_thread(
            self._setup.uninstall, self._run_root, remove_data=remove_data
        )
        remove = self._commands().uninstall
        if remove is not None:
            await asyncio.to_thread(self._run, remove)
        text = _("PowerClock was uninstalled.")
        if report.problems:
            text += "\n\n" + "\n".join(f"• {line}" for line in report.problems)
        if remove is None:
            text += "\n\n" + _("Remove the program the way you installed it.")
        box = inform(self, text, warning=bool(report.problems))
        box.finished.connect(lambda _result: self._quit())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.show()

    @staticmethod
    def _quit_application() -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
