"""The rule editor: forms for the trigger, conditions, guards, steps and options, and the
same rule as JSON. The two views stay in step when switching tabs."""

import json
from typing import Any

from pydantic import ValidationError
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from powerclock.connection import format_detail
from powerclock.gui import forms, style, widgets
from powerclock.gui.client import DaemonLink
from powerclock.gui.forms import ActionEditor, EditorList, ModelForm, PredicateEditor, TriggerEditor
from powerclock.gui.icons import app_icon
from powerclock.gui.tasks import spawn
from powerclock.gui.widgets import AppCombo
from powerclock.i18n import _
from powerclock.models import Guards, Rule

GENERAL = ("name", "enabled")
OPTIONS = (
    "warning",
    "wake",
    "log_in",
    "one_shot",
    "on_missed",
    "on_error",
    "dry_run",
    "timezone",
)
PLACEHOLDER_ID = "new-rule"  # only to validate a new rule locally; the daemon picks its id


class RuleEditor(QDialog):
    def __init__(
        self, link: DaemonLink, rule: dict[str, Any] | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._link = link
        self._original = rule
        if link is not None and link.health is not None:  # before the forms are built
            forms.SETTINGS["tariff"] = link.health.get("tariff")
        self.setWindowIcon(app_icon())
        self.setWindowTitle(
            _("New rule") if rule is None else _("Edit rule: {name}").format(name=rule["name"])
        )

        self.general = ModelForm(Rule, only=GENERAL)
        self.rule_id = QLineEdit()
        self.rule_id.setPlaceholderText(_("automatic"))
        self.rule_id.setReadOnly(rule is not None)
        self.rule_id.setFrame(rule is None)
        form = self.general.layout()
        assert isinstance(form, QFormLayout)
        form.insertRow(0, _("Id:"), self.rule_id)
        self.trigger = TriggerEditor()
        self.conditions = EditorList(PredicateEditor, _("Add a condition"))
        self.guards = EditorList(PredicateEditor, _("Add a reason to wait"))
        self.guard_timing = ModelForm(Guards, only=("retry", "max_wait"))
        self.actions = EditorList(ActionEditor, _("Add a step"))
        self.on_failure = EditorList(ActionEditor, _("Add a step for failures"))
        self.options = ModelForm(Rule, only=OPTIONS)
        self.json = QPlainTextEdit()
        self.json.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        when = QGroupBox(_("When"))
        QVBoxLayout(when).addWidget(self.trigger)
        rule_tab = _page(self.general, when)

        only_if = QGroupBox(_("Only if all of these hold"))
        only_if_layout = QVBoxLayout(only_if)
        only_if_layout.addWidget(
            _hint(_("If one is not met at that moment, nothing is done this time."))
        )
        only_if_layout.addWidget(self.conditions)
        wait_while = QGroupBox(_("Wait while any of these holds"))
        wait_layout = QVBoxLayout(wait_while)
        wait_layout.addWidget(
            _hint(_("E.g. a render or a video playing: it waits and checks again."))
        )
        wait_layout.addWidget(self.guards)
        wait_layout.addWidget(self.guard_timing)
        only_if_tab = _page(only_if)
        wait_tab = _page(wait_while)

        steps = QGroupBox(_("Do, in this order"))
        QVBoxLayout(steps).addWidget(self.actions)
        failed = QGroupBox(_("If a step fails"))
        failed_layout = QVBoxLayout(failed)
        failed_layout.addWidget(
            _hint(_("E.g. send the error to your phone: {error} is what went wrong."))
        )
        failed_layout.addWidget(self.on_failure)
        steps_tab = _page(steps, failed)
        options_tab = _page(self.options)

        self.tabs = QTabWidget()
        self.tabs.addTab(rule_tab, _("When"))
        self.tabs.addTab(only_if_tab, _("Only if…"))
        self.tabs.addTab(wait_tab, _("Wait while…"))
        self.tabs.addTab(steps_tab, _("What it does"))
        self.tabs.addTab(options_tab, _("Options"))
        self.tabs.addTab(self.json, "JSON")
        self._tab = 0
        self._all = False  # conditions written as {"all": [...]} even with a single one
        self.tabs.currentChanged.connect(self._switched)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {style.text_color('failed').name()};")
        self.error.hide()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.resize(720, 640)

        self.set_rule(rule or _new_rule())
        if link is not None and not widgets.APP_CATALOG:
            spawn(self._load_apps(), self, on_error=lambda _error: None)

    async def _load_apps(self) -> None:
        """The installed applications, for the "Open an application" steps."""
        widgets.APP_CATALOG[:] = await self._link.api.get("/apps")
        for combo in self.findChildren(AppCombo):
            combo.fill()

    # ── Form ↔ JSON ───────────────────────────────────────────────────────────

    def set_rule(self, data: dict[str, Any]) -> None:
        self.rule_id.setText(data.get("id", ""))
        self.general.set(data)
        self.trigger.set(data.get("trigger"))
        conditions = data.get("conditions")
        self._all = isinstance(conditions, dict) and set(conditions) == {"all"}
        self.conditions.set(_conditions_list(conditions))
        guards = data.get("guards") or {}
        self.guards.set(list(guards.get("any", [])))
        self.guard_timing.set(guards)
        self.actions.set(list(data.get("actions", [])))
        self.on_failure.set(list(data.get("on_failure", [])))
        self.options.set(data)
        self.json.setPlainText(_dump(data))

    def rule_data(self) -> dict[str, Any]:
        """The rule as the form (or the JSON tab, if open) says; ValueError if unreadable."""
        if self.tabs.currentWidget() is self.json:
            return self._json_data()
        data: dict[str, Any] = {}
        if self.rule_id.text().strip():
            data["id"] = self.rule_id.text().strip()
        data.update(self.general.get())
        data["trigger"] = self._keep_armed(self.trigger.get())
        items = self.conditions.get()
        if not items:
            data["conditions"] = None
        elif len(items) == 1 and not self._all:
            data["conditions"] = items[0]
        else:
            data["conditions"] = {"all": items}
        guards = self.guards.get()
        data["guards"] = {"any": guards, **self.guard_timing.get()} if guards else None
        data["actions"] = self.actions.get()
        data["on_failure"] = self.on_failure.get()
        data.update(self.options.get())
        return data

    def validate(self) -> dict[str, Any]:
        """The rule, checked with the same models the daemon uses; ValueError with the
        reasons if it is not valid."""
        data = self.rule_data()
        try:
            Rule.model_validate({"id": PLACEHOLDER_ID, **data})
        except ValidationError as exc:
            errors = json.loads(exc.json(include_url=False))
            raise ValueError(format_detail(errors)) from None
        return data

    def save(self) -> None:
        try:
            data = self.validate()
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._show_error(None)
        self.save_button.setEnabled(False)
        spawn(self._send(data), self, on_error=self._failed)

    async def _send(self, data: dict[str, Any]) -> None:
        if self._original is None:
            await self._link.api.post("/rules", json=data)
        else:
            await self._link.api.put(f"/rules/{self._original['id']}", json=data)
        self._link.refresh()
        self.accept()

    def _failed(self, error: Exception) -> None:
        self.save_button.setEnabled(True)
        self._show_error(str(error))

    def _show_error(self, text: str | None) -> None:
        self.error.setText(text or "")
        self.error.setVisible(bool(text))

    def _switched(self, index: int) -> None:
        leaving_json = self.tabs.widget(self._tab) is self.json
        entering_json = self.tabs.widget(index) is self.json
        try:
            if leaving_json and not entering_json:
                self.set_rule(self._json_data())
            elif entering_json and not leaving_json:
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(self._tab)  # read the form, not the JSON
                data = self.rule_data()
                self.tabs.setCurrentIndex(index)
                self.tabs.blockSignals(False)
                self.json.setPlainText(_dump(data))
        except ValueError as exc:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(self._tab)
            self.tabs.blockSignals(False)
            self._show_error(str(exc))
            return
        self._show_error(None)
        self._tab = index

    def _json_data(self) -> dict[str, Any]:
        try:
            data = json.loads(self.json.toPlainText())
        except json.JSONDecodeError as exc:
            raise ValueError(_("invalid JSON: {error}").format(error=exc)) from None
        if not isinstance(data, dict):
            raise ValueError(_("the JSON must be an object"))
        return data

    def _keep_armed(self, trigger: dict[str, Any]) -> dict[str, Any]:
        """Editing a countdown rule must not restart its countdown."""
        before = (self._original or {}).get("trigger", {})
        if (
            trigger.get("type") == "countdown"
            and before.get("type") == "countdown"
            and before.get("duration") == trigger.get("duration")
            and before.get("armed_at")
        ):
            return {**trigger, "armed_at": before["armed_at"]}
        return trigger


def _new_rule() -> dict[str, Any]:
    return {
        "name": _("New rule"),
        "trigger": {"type": "cron", "expr": "0 3 * * *"},
        "actions": [{"type": "notify", "title": "PowerClock", "body": ""}],
    }


def _conditions_list(conditions: Any) -> list[dict[str, Any]]:
    if not conditions:
        return []
    if isinstance(conditions, dict) and set(conditions) == {"all"}:
        return list(conditions["all"])
    return [conditions]


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    font = QFont(label.font())
    font.setItalic(True)
    label.setFont(font)
    return label


def _page(*widgets: QWidget) -> QScrollArea:
    inner = QWidget()
    layout = QVBoxLayout(inner)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(inner)
    return scroll
