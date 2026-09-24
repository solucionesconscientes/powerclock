"""The History tab: every run, why it ended as it did, and its steps."""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from powerclock.cli.format import local
from powerclock.gui.client import DaemonLink
from powerclock.gui.icons import themed
from powerclock.gui.summary import when_text
from powerclock.gui.tasks import spawn
from powerclock.i18n import _
from powerclock.labels import cause_label, detail_label, kind_label, reason_label, state_label

LIMIT = 200
STATE_COLORS = {
    "done": "#27ae60",
    "failed": "#da4453",
    "cancelled": "#f67400",
    "skipped": "#7f8c8d",
}


class HistoryTab(QWidget):
    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self.runs: list[dict[str, Any]] = []

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [_("Finished"), _("Rule"), _("Result"), _("Why it ran"), _("Reason")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        for column in (0, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_steps)

        self.steps = QPlainTextEdit()
        self.steps.setReadOnly(True)
        self.steps.setPlaceholderText(_("Pick a run to see its steps."))
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.steps)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        refresh = QPushButton(themed("view-refresh"), _("Refresh"))
        refresh.clicked.connect(self.reload)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(refresh)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        link.event.connect(self._on_event)

    def reload(self) -> None:
        spawn(self._load(), self)

    async def _load(self) -> None:
        data = await self._link.api.get("/history", params={"limit": LIMIT})
        self.show_runs(data["runs"])

    def show_runs(self, runs: list[dict[str, Any]]) -> None:
        self.runs = runs
        self.table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            state = QTableWidgetItem(state_label(run["state"]))
            if run["state"] in STATE_COLORS:
                state.setForeground(QBrush(QColor(STATE_COLORS[run["state"]])))
            cause = cause_label(run["cause"]) + (" · " + _("late") if run.get("missed") else "")
            cells = [
                QTableWidgetItem(when_text(run.get("finished_at"))),
                QTableWidgetItem(run["rule_name"]),
                state,
                QTableWidgetItem(cause),
                QTableWidgetItem(reason_label(run.get("reason"))),
            ]
            for column, cell in enumerate(cells):
                cell.setToolTip(cell.text())
                self.table.setItem(row, column, cell)
        self.steps.clear()

    def _show_steps(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        run = self.runs[rows[0].row()]
        lines = [
            f"{run['rule_name']} ({run['rule_id']}) · {state_label(run['state'])}",
            _("started {start} · finished {end}").format(
                start=local(run.get("started_at")), end=local(run.get("finished_at"))
            ),
        ]
        if run.get("dry_run"):
            lines.append(_("dry run: power actions were only logged"))
        for step in run.get("steps", []):
            line = f"{step['index'] + 1}. {kind_label(step['type'])}: {state_label(step['status'])}"
            if step.get("detail"):
                line += f" — {detail_label(step['detail'])}"
            lines.append(line)
        if not run.get("steps"):
            lines.append(_("No step ran."))
        self.steps.setPlainText("\n".join(lines))

    def _on_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "run_finished" and self.isVisible():
            self.reload()
