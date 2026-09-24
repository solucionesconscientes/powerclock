"""The Rules tab: every rule with its trigger and what comes next; create, edit, enable,
run, delete, import and export."""

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from powerclock.cli.format import relative, watch_detail
from powerclock.gui.client import DaemonLink
from powerclock.gui.editor import RuleEditor
from powerclock.gui.icons import themed
from powerclock.gui.summary import when_text
from powerclock.gui.tasks import ask, show_error, spawn
from powerclock.i18n import _
from powerclock.labels import describe_trigger

COLUMNS = ("on", "name", "trigger", "next", "id")


class RulesTab(QWidget):
    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self.rules: list[dict[str, Any]] = []
        self.editor: RuleEditor | None = None

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(["", _("Name"), _("When"), _("Next"), _("Id")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._toggled)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.new_button = _button("list-add", _("New…"), self.new)
        self.edit_button = _button("document-edit", _("Edit…"), self.edit)
        self.run_button = _button("media-playback-start", _("Run now"), self.run)
        self.delete_button = _button("edit-delete", _("Delete"), self.delete)
        import_button = _button("document-import", _("Import…"), self.import_file)
        export_button = _button("document-export", _("Export…"), self.export_file)
        buttons = QHBoxLayout()
        for button in (self.new_button, self.edit_button, self.run_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(import_button)
        buttons.addWidget(export_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

        link.event.connect(self._on_event)
        link.changed.connect(self._fill_next)
        self._update_buttons()

    # ── Data ──────────────────────────────────────────────────────────────────

    def reload(self) -> None:
        spawn(self._load(), self)

    async def _load(self) -> None:
        self.show_rules(await self._link.api.get("/rules"))

    def show_rules(self, rules: list[dict[str, Any]]) -> None:
        selected = self.selected()
        self.rules = rules
        self.table.blockSignals(True)
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            enabled.setCheckState(
                Qt.CheckState.Checked if rule["enabled"] else Qt.CheckState.Unchecked
            )
            enabled.setToolTip(_("Enabled"))
            self.table.setItem(row, 0, enabled)
            self.table.setItem(row, 1, _cell(rule["name"]))
            self.table.setItem(row, 2, _cell(describe_trigger(rule["trigger"])))
            self.table.setItem(row, 3, QTableWidgetItem(""))
            self.table.setItem(row, 4, QTableWidgetItem(rule["id"]))
            if selected is not None and rule["id"] == selected["id"]:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self._fill_next()
        self._update_buttons()

    def _fill_next(self) -> None:
        pending = self._link.pending
        upcoming = {item["rule_id"]: item["at"] for item in pending.get("next", [])}
        watched = {item["rule_id"]: item for item in pending.get("watching", [])}
        running = {run["rule_id"] for run in pending.get("active", [])}
        for row, rule in enumerate(self.rules):
            rule_id = rule["id"]
            if rule_id in running:
                text = _("running")
            elif rule_id in upcoming:
                text = f"{when_text(upcoming[rule_id])} ({relative(upcoming[rule_id])})"
            elif rule_id in watched:
                text = f"👁 {watch_detail(watched[rule_id])}"
            else:
                text = ""
            item = self.table.item(row, 3)
            if item is not None:
                item.setText(text)
                item.setToolTip(text)

    def selected(self) -> dict[str, Any] | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.rules[rows[0].row()] if rows and rows[0].row() < len(self.rules) else None

    # ── Actions ───────────────────────────────────────────────────────────────

    def new(self) -> None:
        self._open_editor(None)

    def edit(self) -> None:
        rule = self.selected()
        if rule is not None:
            self._open_editor(rule)

    def run(self) -> None:
        rule = self.selected()
        if rule is not None:
            spawn(self._link.api.post(f"/rules/{rule['id']}/run"), self)

    def delete(self) -> None:
        rule = self.selected()
        if rule is None:
            return
        question = _("Delete the rule {name!r}?").format(name=rule["name"])
        ask(self, question, lambda: spawn(self._delete(rule["id"]), self))

    async def _delete(self, rule_id: str) -> None:
        await self._link.api.delete(f"/rules/{rule_id}")
        self.reload()

    def import_file(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Import rules"), str(Path.home()), _("Rules (*.json)")
        )
        if not name:
            return
        try:
            data = json.loads(Path(name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            show_error(exc, self)
            return
        spawn(self._import(data), self)

    async def _import(self, data: Any) -> None:
        if isinstance(data, dict) and isinstance(data.get("rules"), list):
            data = data["rules"]
        existing = {rule["id"] for rule in self.rules}
        for rule in data if isinstance(data, list) else [data]:
            if rule.get("id") in existing:
                await self._link.api.put(f"/rules/{rule['id']}", json=rule)
            else:
                await self._link.api.post("/rules", json=rule)
        self.reload()

    def export_file(self) -> None:
        name, _filter = QFileDialog.getSaveFileName(
            self, _("Export rules"), str(Path.home() / "powerclock-rules.json"), _("Rules (*.json)")
        )
        if name:
            text = json.dumps({"version": 1, "rules": self.rules}, indent=2, ensure_ascii=False)
            Path(name).write_text(text + "\n", encoding="utf-8")

    def _open_editor(self, rule: dict[str, Any] | None) -> None:
        self.editor = RuleEditor(self._link, rule, self)
        self.editor.accepted.connect(self.reload)
        self.editor.open()

    def _toggled(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.row() >= len(self.rules):
            return
        rule = self.rules[item.row()]
        on = item.checkState() == Qt.CheckState.Checked
        spawn(self._link.api.post(f"/rules/{rule['id']}/{'enable' if on else 'disable'}"), self)

    def _on_event(self, event: dict[str, Any]) -> None:
        if event.get("type") in ("rule_changed", "connected"):
            self.reload()

    def _update_buttons(self) -> None:
        chosen = self.selected() is not None
        for button in (self.edit_button, self.run_button, self.delete_button):
            button.setEnabled(chosen)


def _cell(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(text)
    return item


def _button(icon: str, text: str, slot: Any) -> QPushButton:
    button = QPushButton(themed(icon), text)
    button.clicked.connect(slot)
    return button
