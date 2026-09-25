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

from powerclock import recipes
from powerclock.gui import widgets
from powerclock.gui.client import DaemonLink
from powerclock.gui.icons import themed
from powerclock.gui.summary import Item, quick_items
from powerclock.gui.tasks import spawn
from powerclock.gui.tray import ACTION_ICONS
from powerclock.gui.widgets import (
    AppCombo,
    DurationEdit,
    LocalDateTimeEdit,
    ProcessCombo,
    next_quarter,
)
from powerclock.i18n import _, now_label, power_action_label, schedule_label
from powerclock.models import format_duration
from powerclock.platform.base import PowerAction

RUN = "run"  # the "Run a program" entry of the action list
APP = "app"  # the "Open an application" entry
TASKS = {RUN, APP}  # not power actions: no countdown, force or "turn it back on"
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
        self.action.addItem(themed("applications-other"), _("Open an application"), APP)
        self.command = QLineEdit()
        self.command.setPlaceholderText(_("e.g. /home/pc/bin/backup.sh --full"))
        self.app = AppCombo()
        self.recipe = QComboBox()
        self.args = QLineEdit()
        self.args.setPlaceholderText(_("Optional: a file, a web address, options…"))
        self.recipe_hint = QLabel()
        self.recipe_hint.setWordWrap(True)
        self._loading_apps = False

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
        self.app_rows = [QLabel(_("Application:")), QLabel(_("Recipe:")), QLabel(_("Arguments:"))]
        form.addRow(self.app_rows[0], self.app)
        form.addRow(self.app_rows[1], self.recipe)
        form.addRow("", self.recipe_hint)
        form.addRow(self.app_rows[2], self.args)
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
        self.app.currentTextChanged.connect(lambda _text: self._offer_recipes())
        self.recipe.activated.connect(self._use_recipe)
        link.changed.connect(self.update_pending)
        link.changed.connect(self._load_apps)
        self._offer_recipes()
        self._update_form()
        self.update_pending()
        self._load_apps()

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
        elif action == APP:
            app = self.app.value()
            if not app:
                raise ValueError(_("Pick the application to open."))
            payload["app"] = app
            payload["args"] = shlex.split(self.args.text())
        else:
            payload["action"] = PowerAction(action).value
            payload["warning"] = format_duration(self.warning.value())
            if self.force.isChecked():
                payload["mode"] = "force"
            if self.wake.isChecked():
                payload["wake_at"] = self.wake_at.time().toString("HH:mm")
        if action in TASKS and when in TIME_WHEN and self.wake_to_run.isChecked():
            payload["wake"] = True
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
        kind = self.action.currentData()
        is_task = kind in TASKS
        when = self.when.currentData()
        self.params.setCurrentIndex(WHEN.index(when))
        self.command_label.setVisible(kind == RUN)
        self.command.setVisible(kind == RUN)
        for widget in (*self.app_rows, self.app, self.recipe, self.args):
            widget.setVisible(kind == APP)
        self.recipe_hint.setVisible(kind == APP and bool(self.recipe_hint.text()))
        for widget in (self.warning_label, self.warning, self.force, self.wake, self.wake_at):
            widget.setVisible(not is_task)
        self.wake_at.setEnabled(self.wake.isChecked())
        self.wake_to_run.setVisible(is_task and when in TIME_WHEN)
        if kind == APP:
            self.ok.setText(_("Open now") if when == "now" else _("Schedule opening"))
            return
        action = None if kind == RUN else PowerAction(kind)
        self.ok.setText(now_label(action) if when == "now" else schedule_label(action))

    # ── Applications ──────────────────────────────────────────────────────────

    def _load_apps(self) -> None:
        """Ask the daemon for the installed applications once, when it is reachable."""
        if widgets.APP_CATALOG or self._loading_apps or not self._link.online:
            return
        self._loading_apps = True
        spawn(self._fetch_apps(), self, on_error=self._apps_failed)

    async def _fetch_apps(self) -> None:
        widgets.APP_CATALOG[:] = await self._link.api.get("/apps")
        self._loading_apps = False
        self.app.fill()
        self._offer_recipes()

    def _apps_failed(self, _error: Exception) -> None:
        self._loading_apps = False  # typed ids still work; try again on the next change

    def _offer_recipes(self) -> None:
        chosen = self.app.app()
        found = recipes.for_app(self.app.value(), chosen.get("flatpak") if chosen else None)
        self.recipe.clear()
        self.recipe.addItem(_("(none)"), None)
        for recipe in found:
            self.recipe.addItem(recipe.title(), recipe.id)
        self.recipe.setEnabled(bool(found))
        self._show_recipe_hint(None)

    def _use_recipe(self, index: int) -> None:
        recipe = recipes.get(self.recipe.itemData(index) or "")
        if recipe is not None:
            self.args.setText(shlex.join(recipe.fill({})))
        self._show_recipe_hint(recipe)

    def _show_recipe_hint(self, recipe: recipes.Recipe | None) -> None:
        lines = []
        if recipe is not None:
            for key, label in recipe.inputs.items():
                lines.append(
                    _("Replace <{key}> with: {what}").format(key=key, what=recipe.text(label))
                )
        self.recipe_hint.setText("\n".join(lines))
        self.recipe_hint.setVisible(bool(lines) and self.action.currentData() == APP)

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
