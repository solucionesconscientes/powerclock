"""The countdown before a power action: a small window on top of the others with Cancel and
Postpone 10 minutes. The desktop notification of the daemon offers the same buttons."""

import time
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from powerclock.cli.format import moment
from powerclock.gui.client import DaemonLink
from powerclock.gui.icons import app_icon, themed
from powerclock.gui.tasks import spawn
from powerclock.i18n import _, power_action_label
from powerclock.platform.base import PowerAction

POSTPONE = "10m"
ENDED_GRACE = 3.0  # seconds the dialog stays at 0 s before closing by itself


class CountdownDialog(QDialog):
    def __init__(self, link: DaemonLink, run: dict[str, Any], action: str | None) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.run_id: str = run["id"]
        self.opened_at = time.monotonic()
        self._link = link
        self._ended_at: float | None = None
        self._deadline = moment(run.get("deadline")) or datetime.now(UTC)
        self._total = max(1.0, (self._deadline - datetime.now(UTC)).total_seconds())
        self._action = _action_label(action)
        self.setWindowTitle(_("PowerClock — countdown"))
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(48, 48))
        self.headline = QLabel()
        font = QFont(self.headline.font())
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        self.headline.setFont(font)
        self.rule = QLabel(run.get("rule_name", ""))
        self.rule.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)

        buttons = QDialogButtonBox()
        self.cancel_button = QPushButton(themed("dialog-cancel"), _("Cancel"))
        self.postpone_button = QPushButton(themed("chronometer"), _("Postpone 10 minutes"))
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(self.postpone_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_button.clicked.connect(self._cancel)
        self.postpone_button.clicked.connect(self._postpone)
        self.cancel_button.setDefault(True)

        top = QHBoxLayout()
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.addWidget(self.headline)
        texts.addWidget(self.rule)
        top.addLayout(texts, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addWidget(buttons)
        self.setMinimumWidth(420)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def set_rule(self, name: str) -> None:
        self.rule.setText(name)

    def set_action(self, action: str | None) -> None:
        self._action = _action_label(action)
        self.refresh()

    def set_deadline(self, deadline: datetime) -> None:
        self._deadline = deadline
        self._total = max(self._total, (deadline - datetime.now(UTC)).total_seconds())
        self.refresh()

    def remaining(self) -> int:
        return max(0, round((self._deadline - datetime.now(UTC)).total_seconds()))

    def refresh(self) -> None:
        seconds = self.remaining()
        if seconds == 0:  # the action is on its way: nothing left to cancel here
            self._ended_at = self._ended_at or time.monotonic()
            if time.monotonic() - self._ended_at > ENDED_GRACE:
                self.done(0)
                self.close()
                return
        else:
            self._ended_at = None
        self.headline.setText(
            _("{action} in {seconds} s").format(action=self._action, seconds=seconds)
        )
        left = (self._deadline - datetime.now(UTC)).total_seconds()
        self.bar.setValue(round(1000 * max(0.0, min(1.0, left / self._total))))

    def reject(self) -> None:  # Esc or the window's close button: cancel, like KShutdown
        self._cancel()

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        spawn(self._link.api.post(f"/runs/{self.run_id}/cancel"), self)

    def _postpone(self) -> None:
        spawn(self._link.api.post(f"/runs/{self.run_id}/postpone", json={"delay": POSTPONE}), self)


class Countdowns(QObject):
    """Opens a dialog for each countdown of the daemon and closes it when the countdown ends."""

    def __init__(self, link: DaemonLink) -> None:
        super().__init__()
        self._link = link
        self.dialogs: dict[str, CountdownDialog] = {}
        link.event.connect(self._on_event)
        link.changed.connect(self._sync)

    def _on_event(self, event: dict[str, Any]) -> None:
        run_id = event.get("run_id")
        if run_id is None:
            return
        data = event.get("data", {})
        match event.get("type"):
            case "warning_started":
                run = {
                    "id": run_id,
                    "rule_id": event.get("rule_id"),
                    "deadline": data.get("deadline"),
                }
                self._open(run, data.get("action"))  # the rule's name comes with /pending
            case "postponed" if run_id in self.dialogs and data.get("deadline"):
                deadline = moment(data["deadline"])
                if deadline is not None:
                    self.dialogs[run_id].set_deadline(deadline)
            case "cancelled" | "run_finished":
                self._close(run_id)

    def _sync(self) -> None:
        """Open what the daemon counts down (e.g. the GUI started meanwhile), close the rest."""
        if not self._link.online:
            return
        active = self._link.pending.get("active", [])
        counting = {run["id"]: run for run in active if run["state"] == "warning"}
        for run_id, dialog in list(self.dialogs.items()):
            # Only a /pending requested after the dialog opened can tell it is over.
            if run_id not in counting and self._link.fetched_at > dialog.opened_at:
                self._close(run_id)
        for run_id, run in counting.items():
            if run_id in self.dialogs:
                self.dialogs[run_id].set_rule(run["rule_name"])
            else:
                self._open(run, None)

    def _open(self, run: dict[str, Any], action: str | None) -> None:
        if run["id"] in self.dialogs:
            return
        dialog = CountdownDialog(self._link, run, action)
        dialog.destroyed.connect(lambda _=None, run_id=run["id"]: self.dialogs.pop(run_id, None))
        self.dialogs[run["id"]] = dialog
        if action is None and run.get("rule_id"):
            spawn(self._find_action(dialog, run["rule_id"]), on_error=lambda _error: None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    async def _find_action(self, dialog: CountdownDialog, rule_id: str) -> None:
        """Opened from /pending (the GUI started during the countdown): which power action?"""
        rule = await self._link.api.get(f"/rules/{rule_id}")
        power = next((step for step in rule["actions"] if step["type"] == "power"), None)
        if power is not None and dialog.run_id in self.dialogs:
            dialog.set_action(power["action"])

    def _close(self, run_id: str) -> None:
        dialog = self.dialogs.pop(run_id, None)
        if dialog is not None:
            dialog.done(0)
            dialog.close()


def _action_label(action: str | None) -> str:
    try:
        return power_action_label(PowerAction(action)) if action else _("Power action")
    except ValueError:
        return action or _("Power action")
