"""Holds the GUI together: the link with the daemon, the tray, the countdown dialogs and the
window, which exists only while it is open."""

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from kse.gui.client import Api, DaemonLink, EventStream, HttpApi, event_stream
from kse.gui.countdown import Countdowns
from kse.gui.tray import Tray
from kse.gui.window import MainWindow


class Controller(QObject):
    def __init__(
        self,
        app: QApplication,
        *,
        api: Api | None = None,
        stream: EventStream | None = None,
        tray: bool | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self.api = api or HttpApi()
        self.link = DaemonLink(self.api, stream or event_stream())
        self.countdowns = Countdowns(self.link)
        with_tray = QSystemTrayIcon.isSystemTrayAvailable() if tray is None else tray
        self.tray = (
            Tray(self.link, show_window=self.show_window, quit_app=self.quit) if with_tray else None
        )
        self.window: MainWindow | None = None

    def start(self, *, show_window: bool) -> None:
        self.link.start()
        if self.tray is not None:
            self.tray.show()
        if show_window or self.tray is None:  # without a tray, the window is the app
            self.show_window(None)

    def show_window(self, tab: str | None = None) -> None:
        if self.window is None:
            self.window = MainWindow(self.link)
            self.window.destroyed.connect(self._window_closed)
        self.window.show_tab(tab)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def on_request(self, request: str) -> None:
        """From another `kse-gui` started meanwhile."""
        if request == "show":
            self.show_window(None)

    def quit(self) -> None:
        if self.tray is not None:
            self.tray.hide()
        self._app.quit()

    async def stop(self) -> None:
        await self.link.stop()
        close = getattr(self.api, "close", None)
        if close is not None:
            await close()

    def _window_closed(self) -> None:
        self.window = None
        if self.tray is None:
            self.quit()
