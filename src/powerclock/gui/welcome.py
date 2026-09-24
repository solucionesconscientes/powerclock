"""The first time the window opens: what PowerClock is and where things are. Shown once."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from powerclock.config import Paths, atomic_write
from powerclock.gui.icons import app_icon
from powerclock.i18n import _


def _file(paths: Paths | None) -> Path:
    return (paths or Paths.default()).config / "gui.json"


def welcomed(paths: Paths | None = None) -> bool:
    try:
        return bool(json.loads(_file(paths).read_text()).get("welcomed"))
    except (OSError, ValueError, AttributeError):
        return False


def remember_welcomed(paths: Paths | None = None) -> None:
    atomic_write(_file(paths), json.dumps({"welcomed": True}) + "\n")


class WelcomeDialog(QDialog):
    def __init__(self, paths: Paths | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paths = paths
        self.setWindowTitle(_("Welcome to PowerClock"))
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        points = [
            _(
                "PowerClock works in the background: your rules keep running with this window "
                "closed, after restarting, and with nobody logged in if you chose so."
            ),
            _("The icon in the tray shows what comes next; click it to open this window."),
            _(
                "Quick: shut down, suspend or run a program at a time, after a while or when "
                "something happens (a program ends, nobody uses the computer…)."
            ),
            _(
                "Rules: for what repeats, such as a nightly backup that turns the computer on, "
                "runs and shuts it down again."
            ),
            _("Before any power action there is a countdown you can cancel."),
            _("Diagnostics: what works on this computer, updates and uninstalling."),
        ]
        text = QLabel("".join(f"<p>• {point}</p>" for point in points))
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.setMinimumWidth(480)
        self.finished.connect(lambda _result: remember_welcomed(self._paths))
