"""The installation window (`powerclock-gui --setup`), opened by the installer: a few
options, Install, the password once, and PowerClock is ready. The same window on every OS;
the steps below it are per OS (install/steps.py)."""

import asyncio
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from powerclock.gui.icons import app_icon, themed
from powerclock.gui.tasks import spawn
from powerclock.i18n import _
from powerclock.install.steps import Command, Options, Report, Setup
from powerclock.platform import dry_run_requested

RunRoot = Callable[[list[Command]], bool]
Launch = Callable[[], None]


def pkexec_runner(setup: Setup) -> RunRoot:
    """Run root commands with pkexec: one password window from the desktop."""

    def run(commands: list[Command]) -> bool:
        if setup.helper is None:
            return False
        return subprocess.run(setup.helper.elevated(commands), check=False).returncode == 0

    return run


def launch_powerclock() -> None:
    """Start PowerClock (the tray and its window) on its own, apart from this window."""
    executable = Path(sys.executable).parent / "powerclock-gui"
    subprocess.Popen(
        [str(executable)] if executable.exists() else [sys.executable, "-m", "powerclock.gui.app"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class SetupWindow(QDialog):
    def __init__(
        self,
        setup: Setup | None = None,
        *,
        run_root: RunRoot | None = None,
        launch: Launch = launch_powerclock,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setup = setup or Setup()
        self._run_root = run_root or pkexec_runner(self.setup)
        self._launch = launch
        self.report: Report | None = None
        self.setWindowTitle(_("Install PowerClock"))
        self.setWindowIcon(app_icon())

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(64, 64))
        title = QLabel("PowerClock")
        font = QFont(title.font())
        font.setPointSizeF(font.pointSizeF() * 1.8)
        font.setBold(True)
        title.setFont(font)
        intro = QLabel(
            _(
                "Schedule shutdown, wake-up and your tasks, at an exact time or when the "
                "conditions you choose are met."
            )
        )
        intro.setWordWrap(True)
        head = QHBoxLayout()
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.addWidget(title)
        texts.addWidget(intro)
        head.addLayout(texts, 1)

        self.login = QCheckBox(_("Start the tray icon when the session starts"))
        self.menu = QCheckBox(_("Show PowerClock in the applications menu"))
        self.helper = QCheckBox(_("Turn the computer on at a time (asks for your password once)"))
        self.unattended = QCheckBox(_("Also work when you are logged out"))
        for box in (self.login, self.menu, self.helper):
            box.setChecked(True)
        if self.setup.helper is None:
            self.helper.setChecked(False)
            self.helper.setEnabled(False)
            self.helper.setToolTip(_("Not available on this system yet"))
        self.helper.toggled.connect(self._update)
        self.dry_run = dry_run_requested()
        notice = QLabel(_("Test mode: PowerClock will not really turn anything off."))
        notice.setVisible(self.dry_run)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)

        self.buttons = QDialogButtonBox()
        self.install_button = QPushButton(themed("dialog-ok-apply"), _("Install"))
        self.open_button = QPushButton(themed("system-run"), _("Open PowerClock"))
        self.close_button = QPushButton(_("Close"))
        self.buttons.addButton(self.install_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.open_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.close_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.open_button.hide()
        self.install_button.setDefault(True)
        self.install_button.clicked.connect(self.install)
        self.open_button.clicked.connect(self._open)
        self.close_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addSpacing(8)
        for widget in (self.login, self.menu, self.helper, self.unattended, notice):
            layout.addWidget(widget)
        layout.addWidget(self.log, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(520)
        self._update()

    def options(self) -> Options:
        return Options(
            menu=self.menu.isChecked(),
            login=self.login.isChecked(),
            helper=self.helper.isChecked(),
            unattended=self.helper.isChecked() and self.unattended.isChecked(),
            dry_run=self.dry_run,
        )

    def install(self) -> None:
        for widget in (self.install_button, self.login, self.menu, self.helper, self.unattended):
            widget.setEnabled(False)
        self.status.setText(_("Installing…"))
        spawn(self._install(self.options()), self, on_error=self._failed)

    async def _install(self, options: Options) -> None:
        self.report = report = await asyncio.to_thread(self.setup.install, options, self._run_root)
        lines = [f"✔ {line}" for line in report.done] + [f"• {line}" for line in report.problems]
        self.log.setPlainText("\n".join(lines))
        self.log.show()
        if report.ok:
            self.status.setText("✔ " + _("PowerClock is ready."))
        else:
            self.status.setText(_("PowerClock is installed, with the notes above."))
        self.open_button.show()
        self.open_button.setDefault(True)
        self.close_button.setText(_("Close"))

    def _failed(self, error: Exception) -> None:
        self.status.setText(f"✘ {error}")
        self.install_button.setEnabled(True)

    def _open(self) -> None:
        self._launch()
        self.accept()

    def _update(self) -> None:
        self.unattended.setEnabled(self.helper.isChecked() and self.helper.isEnabled())
        if not self.helper.isChecked():
            self.unattended.setChecked(False)
