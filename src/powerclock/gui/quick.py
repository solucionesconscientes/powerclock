"""The Quick tab, in the spirit of KShutdown: the action as a button, when, a few options and
one button that says what it will do. On the right, the quick actions scheduled, as cards
with Cancel and Postpone (the form takes 61.8 % of the width, the cards 38.2 %)."""

import shlex
from typing import Any

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from powerclock import recipes
from powerclock.gui import style, widgets
from powerclock.gui.cards import ChoiceButtons, ItemCard, WhenPicker, scrollable
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
SEGMENTS = ("now", "at", "in", "when")  # the last one opens the list of conditions
CONDITIONS = ("idle", "exits", "cpu", "net")
BUTTON_ORDER = (  # two rows of five
    PowerAction.SHUTDOWN,
    PowerAction.REBOOT,
    PowerAction.SUSPEND,
    PowerAction.HIBERNATE,
    PowerAction.HYBRID_SLEEP,
    PowerAction.LOCK,
    PowerAction.LOGOUT,
    PowerAction.SCREEN_OFF,
    RUN,
    APP,
)


def button_label(action: PowerAction | str) -> str:
    """Short names for the action buttons (the tooltip has the long one)."""
    labels = {
        PowerAction.HYBRID_SLEEP: _("Hybrid"),
        PowerAction.LOCK: _("Lock"),
        PowerAction.SCREEN_OFF: _("Screen off"),
        RUN: _("Command"),
        APP: _("Application"),
    }
    if action in labels:
        return labels[action]
    return power_action_label(PowerAction(action))


def long_label(action: PowerAction | str) -> str:
    if action == RUN:
        return _("Run a command or a script")
    if action == APP:
        return _("Open an application")
    return power_action_label(PowerAction(action))


def when_label(when: str) -> str:
    labels = {
        "now": _("Now"),
        "at": _("At a time"),
        "in": _("In a while"),
        "when": _("When…"),
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

        icons = {**ACTION_ICONS, RUN: "system-run", APP: "applications-other"}
        self.action = ChoiceButtons(
            [(a, button_label(a), themed(icons.get(a, "system-run"))) for a in BUTTON_ORDER],
            columns=5,
        )
        for action, button in zip(BUTTON_ORDER, self.action.buttons, strict=True):
            button.setToolTip(long_label(action))
        self.command = QLineEdit()
        self.command.setPlaceholderText(_("e.g. /home/pc/bin/backup.sh --full"))
        self.terminal = QCheckBox(_("Open in a terminal (to answer questions or type a password)"))
        self.terminal.setToolTip(
            _(
                "For scripts that ask something or use sudo: they need you in front of the "
                "screen. The window stays open at the end so you can read what happened."
            )
        )
        self.app = AppCombo()
        self.recipe = QComboBox()
        self.args = QLineEdit()
        self.args.setPlaceholderText(_("Optional: a file, a web address, options…"))
        self.recipe_hint = QLabel()
        self.recipe_hint.setWordWrap(True)
        self._loading_apps = False

        self.when = WhenPicker(
            [(when, when_label(when)) for when in SEGMENTS],
            [(when, when_label(when)) for when in CONDITIONS],
        )
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
        self.log_in = QCheckBox(_("and log in (screen locked)"))
        self.log_in.setToolTip(
            _(
                "Only on the start-up that PowerClock causes: any other start-up asks for the "
                "password as usual."
            )
        )

        what = QLabel(_("What to do"))
        style.use_scale(what, 1, bold=True)
        form = QFormLayout()
        form.setVerticalSpacing(style.SPACE[2])
        self.command_label = QLabel(_("Command:"))
        form.addRow(self.command_label, self.command)
        form.addRow("", self.terminal)
        self.app_rows = [QLabel(_("Application:")), QLabel(_("Recipe:")), QLabel(_("Arguments:"))]
        form.addRow(self.app_rows[0], self.app)
        form.addRow(self.app_rows[1], self.recipe)
        form.addRow("", self.recipe_hint)
        form.addRow(self.app_rows[2], self.args)
        when_title = QLabel(_("When"))
        style.use_scale(when_title, 1, bold=True)
        form.addRow(when_title)
        form.addRow(self.when)
        form.addRow(self.params)
        self.warning_label = QLabel(_("Warn me first:"))
        form.addRow(self.warning_label, self.warning)
        form.addRow("", self.force)
        form.addRow("", _row(self.wake, self.wake_at))
        form.addRow("", self.wake_to_run)
        form.addRow("", self.log_in)

        self.ok = style.primary(QPushButton())
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.submit)
        self.status = QLabel()
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.ok)

        left = QWidget()
        inner = QVBoxLayout(left)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(style.SPACE[3])
        inner.addWidget(what)
        inner.addWidget(self.action)
        inner.addLayout(form)
        inner.addStretch(1)
        inner.addLayout(buttons)

        scheduled = QLabel(_("Scheduled"))
        style.use_scale(scheduled, 1, bold=True)
        self.cards: list[ItemCard] = []
        self.pending = QWidget()
        self._cards = QVBoxLayout(self.pending)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(style.SPACE[2])
        self._cards.addStretch(1)
        scroll = scrollable(self.pending)
        self.empty = QLabel(_("No quick actions scheduled."))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        right = QWidget()
        side = QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(style.SPACE[2])
        side.addWidget(scheduled)
        side.addWidget(self.empty)
        side.addWidget(scroll, 1)

        layout = QHBoxLayout(self)
        layout.setSpacing(style.SPACE[4])
        layout.addWidget(scrollable(left), style.MAIN_SHARE[0])
        layout.addWidget(right, style.MAIN_SHARE[1])

        self.action.currentIndexChanged.connect(self._update_form)
        self.when.currentIndexChanged.connect(self._update_form)
        self.wake.toggled.connect(self._update_form)
        self.wake_to_run.toggled.connect(self._update_form)
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
                raise ValueError(_("Write the command to run."))
            payload["command"] = command
            if self.terminal.isChecked():
                payload["terminal"] = True
        elif action == APP:
            app = self.app.value()
            if not app:
                raise ValueError(_("Pick the application to open."))
            payload["app"] = app
            payload["args"] = shlex.split(self.args.text())
            if self.recipe.currentData():
                payload["recipe"] = self.recipe.currentData()
        else:
            payload["action"] = PowerAction(action).value
            payload["warning"] = format_duration(self.warning.value())
            if self.force.isChecked():
                payload["mode"] = "force"
            if self.wake.isChecked():
                payload["wake_at"] = self.wake_at.time().toString("HH:mm")
        if action in TASKS and when in TIME_WHEN and self.wake_to_run.isChecked():
            payload["wake"] = True
        if (
            not self.log_in.isHidden()
            and self.log_in.isChecked()
            and (payload.get("wake") or payload.get("wake_at"))
        ):
            payload["log_in"] = "locked"
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
        tone = style.text_color("failed").name()
        self.status.setStyleSheet(f"color: {tone};" if error else "")
        self.status.setText(text)

    def _update_form(self) -> None:
        kind = self.action.currentData()
        is_task = kind in TASKS
        when = self.when.currentData()
        self.params.setCurrentIndex(WHEN.index(when))
        self.command_label.setVisible(kind == RUN)
        self.command.setVisible(kind == RUN)
        self.terminal.setVisible(kind == RUN)
        for widget in (*self.app_rows, self.app, self.recipe, self.args):
            widget.setVisible(kind == APP)
        self.recipe_hint.setVisible(kind == APP and bool(self.recipe_hint.text()))
        for widget in (self.warning_label, self.warning, self.force, self.wake, self.wake_at):
            widget.setVisible(not is_task)
        self.wake_at.setEnabled(self.wake.isChecked())
        self.wake_to_run.setVisible(is_task and when in TIME_WHEN)
        waking = (is_task and when in TIME_WHEN and self.wake_to_run.isChecked()) or (
            not is_task and self.wake.isChecked()
        )
        self.log_in.setVisible(waking)
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
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for item in items:
            can_postpone = item.counting_down or (item.run_id is None and not item.watched)
            card = ItemCard(item, self._cancel, self._postpone if can_postpone else None)
            self._cards.insertWidget(len(self.cards), card)
            self.cards.append(card)
        self.empty.setVisible(not items)

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
