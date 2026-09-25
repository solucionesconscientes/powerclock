"""The main window: Quick, Rules, History and Diagnostics tabs, and a banner when PowerClock
is not running in the background. It is created when opened and destroyed when closed (the
tray stays)."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from powerclock.gui.client import DaemonLink
from powerclock.gui.diagnostics import DiagnosticsTab
from powerclock.gui.history import HistoryTab
from powerclock.gui.icons import app_icon, themed
from powerclock.gui.quick import QuickTab
from powerclock.gui.rules import RulesTab
from powerclock.gui.summary import not_running_text, summarize
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
        self.tabs.addTab(self.diagnostics, themed("help-about"), _("Diagnostics"))
        self.tabs.currentChanged.connect(self._load_tab)

        self.banner = QFrame()
        self.banner.setStyleSheet(
            "QFrame { background: #fdecea; border: 1px solid #da4453; border-radius: 4px; }"
            "QLabel { border: none; color: #232629; }"
        )
        banner_layout = QHBoxLayout(self.banner)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        start = QPushButton(themed("media-playback-start"), _("Start PowerClock"))
        start.clicked.connect(self._start_service)
        banner_layout.addWidget(self.banner_text, 1)
        banner_layout.addWidget(start)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.resize(760, 620)

        self._timer = QTimer(self)
        self._timer.setInterval(LIVE_REFRESH)
        self._timer.timeout.connect(link.refresh)
        link.changed.connect(self._update)
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
        self.banner.setVisible(not link.online)
        self.banner_text.setText(not_running_text())
        summary = summarize(link.online, link.pending)
        self.statusBar().showMessage(summary.headline)
        dry = link.online and bool(link.health and link.health.get("dry_run"))
        self.setWindowTitle("PowerClock" + (" — " + _("test mode") if dry else ""))

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
