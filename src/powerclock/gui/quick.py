"""The Quick tab, in the spirit of KShutdown: an action, when, a few options and a button
that says what it will do. Below, the quick actions scheduled, each with Cancel and Postpone."""

import shlex
from typing import Any

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from powerclock.gui.client import DaemonLink
from powerclock.gui.icons import themed
from powerclock.gui.summary import Item, quick_items
from powerclock.gui.tasks import spawn
from powerclock.gui.tray import ACTION_ICONS
from powerclock.gui.widgets import DurationEdit, LocalDateTimeEdit, ProcessCombo, next_quarter
from powerclock.i18n import _, now_label, power_action_label, schedule_label
from powerclock.models import format_duration
from powerclock.platform.base import PowerAction

RUN = "run"  # the "Run a program" entry of the action list
WHEN = ("now", "at", "in", "idle", "exits", "cpu", "net")
TIME_WHEN = {"at", "in"}


def when_label(when: str) -> str:
    labels = {
        "now": _("Now"),
        "at": _("At a date and time"),
        "in": _("After a delay"),
        "idle": _("After a period without use"),
        "exits": _("When a program ends"),
        "cpu": _("When the computer goes quiet"),
        "net": _("When the download finishes"),
    }
    return labels[when]


class QuickTab(QWidget):
    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link

        self.action = QComboBox()
        for action in PowerAction:
            self.action.addItem(
                themed(ACTION_ICONS.get(action, "system-run")), power_action_label(action), action
            )
        self.action.addItem(themed("system-run"), _("Run a program"), RUN)
        self.command = QLineEdit()
        self.command.setPlaceholderText(_("e.g. /home/pc/bin/backup.sh --full"))

        self.when = QComboBox()
        for when in WHEN:
            self.when.addItem(when_label(when), when)
        self.at = LocalDateTimeEdit()
        self.at.set_value(next_quarter())
        self.in_ = DurationEdit("30m")
        self.idle = DurationEdit("20m")
        self.exits = ProcessCombo()
        self.cpu = QDoubleSpinBox()
        self.cpu.setRange(1, 100)
        self.cpu.setValue(10)
        self.cpu.setSuffix(" %")
        self.net = QDoubleSpinBox()
        self.net.setRange(1, 1_000_000)
        self.net.setValue(50)
        self.net.setSuffix(" kbit/s")
        self.cpu_for = DurationEdit("5m")
        self.net_for = DurationEdit("5m")
        self.params = QStackedWidget()
        for widget in (
            QWidget(),
            self.at,
            self.in_,
            self.idle,
            self.exits,
            _row(QLabel(_("CPU below")), self.cpu, QLabel(_("for")), self.cpu_for),
            _row(QLabel(_("network below")), self.net, QLabel(_("for")), self.net_for),
        ):
            self.params.addWidget(widget)

        self.force = QCheckBox(_("Force (don't wait for apps to save)"))
        self.warning = DurationEdit("1m", allow_zero=True)
        self.wake = QCheckBox(_("Turn it back on at"))
        self.wake_at = QTimeEdit(QTime(7, 30))
        self.wake_at.setDisplayFormat("HH:mm")
        self.wake_to_run = QCheckBox(_("Turn the computer on to run it"))

        form = QFormLayout()
        form.addRow(_("Action:"), self.action)
        self.command_label = QLabel(_("Program:"))
        form.addRow(self.command_label, self.command)
        form.addRow(_("When:"), _row(self.when, self.params, stretch=True))
        self.warning_label = QLabel(_("Warn me first:"))
        form.addRow(self.warning_label, self.warning)
        form.addRow("", self.force)
        form.addRow("", _row(self.wake, self.wake_at))
        form.addRow("", self.wake_to_run)

        self.ok = QPushButton(themed("dialog-ok-apply"), "")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.submit)
        self.status = QLabel()
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.ok)

        box = QGroupBox(_("New quick action"))
        inner = QVBoxLayout(box)
        inner.addLayout(form)
        inner.addLayout(buttons)

        self.pending = QTableWidget(0, 3)
        self.pending.setHorizontalHeaderLabels([_("Action"), _("When"), ""])
        self.pending.verticalHeader().setVisible(False)
        self.pending.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pending.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.pending.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.empty = QLabel(_("No quick actions scheduled."))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        waiting = QGroupBox(_("Scheduled"))
        waiting_layout = QVBoxLayout(waiting)
        waiting_layout.addWidget(self.pending)
        waiting_layout.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(waiting, 1)

        self.action.currentIndexChanged.connect(self._update_form)
        self.when.currentIndexChanged.connect(self._update_form)
        self.wake.toggled.connect(self._update_form)
        link.changed.connect(self.update_pending)
        self._update_form()
        self.update_pending()

    # ── The form ──────────────────────────────────────────────────────────────

    def select(self, action: PowerAction | str, when: str = "now") -> None:
        self.action.setCurrentIndex(self.action.findData(action))
        self.when.setCurrentIndex(self.when.findData(when))

    def payload(self) -> dict[str, Any]:
        """The /quick request for what the form says; ValueError with a message if it is wrong."""
        action = self.action.currentData()
        when = self.when.currentData()
        payload: dict[str, Any] = {}
        if action == RUN:
            command = shlex.split(self.command.text())
            if not command:
                raise ValueError(_("Write the program to run."))
            payload["command"] = command
            if when in TIME_WHEN and self.wake_to_run.isChecked():
                payload["wake"] = True
        else:
            payload["action"] = PowerAction(action).value
            payload["warning"] = format_duration(self.warning.value())
            if self.force.isChecked():
                payload["mode"] = "force"
            if self.wake.isChecked():
                payload["wake_at"] = self.wake_at.time().toString("HH:mm")
        match when:
            case "at":
                payload["at"] = self.at.value().isoformat()
            case "in":
                payload["in"] = format_duration(self.in_.value())
            case "idle":
                payload["when_idle"] = format_duration(self.idle.value())
            case "exits":
                program = self.exits.value()
                if not program:
                    raise ValueError(_("Write or pick the program to wait for."))
                payload["when_exits"] = program
            case "cpu":
                payload["when_cpu_below"] = self.cpu.value()
                payload["for"] = format_duration(self.cpu_for.value())
            case "net":
                payload["when_net_below"] = self.net.value()
                payload["for"] = format_duration(self.net_for.value())
        return payload

    def submit(self) -> None:
        try:
            payload = self.payload()
        except ValueError as exc:
            self._say(str(exc), error=True)
            return
        self.ok.setEnabled(False)
        spawn(self._send(payload), self, on_error=self._failed)

    async def _send(self, payload: dict[str, Any]) -> None:
        rule = await self._link.api.post("/quick", json=payload)
        self.ok.setEnabled(True)
        self._say("✔ " + rule["name"])
        self._link.refresh()

    def _failed(self, error: Exception) -> None:
        self.ok.setEnabled(True)
        self._say(str(error), error=True)

    def _say(self, text: str, *, error: bool = False) -> None:
        self.status.setStyleSheet("color: #da4453;" if error else "")
        self.status.setText(text)

    def _update_form(self) -> None:
        is_run = self.action.currentData() == RUN
        when = self.when.currentData()
        self.params.setCurrentIndex(WHEN.index(when))
        self.command_label.setVisible(is_run)
        self.command.setVisible(is_run)
        for widget in (self.warning_label, self.warning, self.force, self.wake, self.wake_at):
            widget.setVisible(not is_run)
        self.wake_at.setEnabled(self.wake.isChecked())
        self.wake_to_run.setVisible(is_run and when in TIME_WHEN)
        action = None if is_run else PowerAction(self.action.currentData())
        self.ok.setText(now_label(action) if when == "now" else schedule_label(action))

    # ── What is waiting ───────────────────────────────────────────────────────

    def update_pending(self) -> None:
        items = quick_items(self._link.pending) if self._link.online else []
        self.pending.setRowCount(len(items))
        for row, item in enumerate(items):
            for column, text in enumerate((item.name, item.detail)):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self.pending.setItem(row, column, cell)
            self.pending.setCellWidget(row, 2, self._buttons(item))
        self.pending.setVisible(bool(items))
        self.empty.setVisible(not items)

    def _buttons(self, item: Item) -> QWidget:
        cancel = QPushButton(themed("dialog-cancel"), _("Cancel"))
        cancel.clicked.connect(lambda: self._cancel(item))
        widgets: list[QWidget] = [cancel]
        if item.counting_down or (item.run_id is None and not item.watched):
            postpone = QPushButton(themed("chronometer"), _("+10 min"))
            postpone.setToolTip(_("Postpone 10 minutes"))
            postpone.clicked.connect(lambda: self._postpone(item))
            widgets.append(postpone)
        return _row(*widgets)

    def _cancel(self, item: Item) -> None:
        spawn(self._link.api.post(f"/rules/{item.rule_id}/cancel"), self)

    def _postpone(self, item: Item) -> None:
        path = f"/rules/{item.rule_id}/postpone"
        spawn(self._link.api.post(path, json={"delay": "10m"}), self)


def _row(*widgets: QWidget, stretch: bool = False) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    if not stretch:
        layout.addStretch(1)
    return row
