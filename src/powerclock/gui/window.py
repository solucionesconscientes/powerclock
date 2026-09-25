"""The main window: the «Next» band on top (what PowerClock will do next and when, or that it
isn't running), then the Quick, Rules, History and Diagnostics tabs. It is created when
opened and destroyed when closed (the tray stays)."""

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from powerclock.gui import style
from powerclock.gui.cards import NextBand, scrollable
from powerclock.gui.client import DaemonLink
from powerclock.gui.diagnostics import DiagnosticsTab
from powerclock.gui.history import HistoryTab
from powerclock.gui.icons import app_icon, themed
from powerclock.gui.quick import QuickTab
from powerclock.gui.rules import RulesTab
from powerclock.gui.summary import remaining_text, summarize
from powerclock.gui.tasks import spawn
from powerclock.i18n import _

LIVE_REFRESH = 5000  # ms: what the sensors see (CPU, network…) while the window is open
TABS = ("quick", "rules", "history", "diagnostics")


class MainWindow(QMainWindow):
    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self.setWindowTitle("PowerClock")
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.quick = QuickTab(link)
        self.rules = RulesTab(link)
        self.history = HistoryTab(link)
        self.diagnostics = DiagnosticsTab(link)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.quick, themed("chronometer"), _("Quick"))
        self.tabs.addTab(self.rules, themed("view-list-details"), _("Rules"))
        self.tabs.addTab(self.history, themed("view-history"), _("History"))
        self.tabs.addTab(scrollable(self.diagnostics), themed("help-about"), _("Diagnostics"))
        self.tabs.currentChanged.connect(self._load_tab)

        self.band = NextBand()
        self.band.start.clicked.connect(self._start_service)
        self.band.cancel.clicked.connect(lambda: spawn(link.api.post("/cancel"), self))
        self.band.postpone.clicked.connect(
            lambda: spawn(link.api.post("/postpone", json={"delay": "10m"}), self)
        )

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(style.SPACE[3], style.SPACE[3], style.SPACE[3], style.SPACE[3])
        layout.setSpacing(style.SPACE[3])
        layout.addWidget(self.band)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.resize(*style.WINDOW)

        self._timer = QTimer(self)
        self._timer.setInterval(LIVE_REFRESH)
        self._timer.timeout.connect(link.refresh)
        link.changed.connect(self._update)
        link.event.connect(self._on_event)
        self._update()
        self._load_tab(0)

    def show_tab(self, name: str | None) -> None:
        if name in TABS:
            self.tabs.setCurrentIndex(TABS.index(name))

    def showEvent(self, event: object) -> None:
        self._timer.start()
        self._link.refresh()
        super().showEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        super().closeEvent(event)

    def _update(self) -> None:
        link = self._link
        self.summary = summarize(link.online, link.pending)
        self.band.show_summary(self.summary)
        dry = link.online and bool(link.health and link.health.get("dry_run"))
        self.setWindowTitle("PowerClock" + (" — " + _("test mode") if dry else ""))

    def _on_event(self, event: dict[str, Any]) -> None:
        countdown = self.summary.countdown
        if event.get("type") == "tick" and countdown is not None:
            seconds = event.get("data", {}).get("remaining", 0)
            self.band.show_remaining(remaining_text(seconds))

    def _load_tab(self, index: int) -> None:
        if not self._link.online:
            return
        match TABS[index]:
            case "rules":
                self.rules.reload()
            case "history":
                self.history.reload()
            case "diagnostics":
                self.diagnostics.reload()

    def _start_service(self) -> None:
        self.show_tab("diagnostics")
        self.diagnostics.start_daemon()
