"""`powerclock-gui`: the tray icon and, on demand, the window. One instance per user: starting
it again brings up the window of the one already running. `--setup` opens the installation
window instead (the installer does)."""

import argparse
import asyncio
import contextlib
import getpass
import logging
import sys
from typing import TYPE_CHECKING

from powerclock.i18n import _

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="powerclock-gui", description="PowerClock")
    parser.add_argument("--tray", action="store_true", help="start in the tray, without the window")
    parser.add_argument("--setup", action="store_true", help="open the installation window")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        import qasync  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except ImportError:
        sys.exit(_("The GUI is not installed: pipx install --force 'powerclock[gui]'"))
    sys.exit(run_setup() if args.setup else run(tray_only=args.tray))


def application() -> "QApplication":
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("powerclock")
    app.setApplicationDisplayName("PowerClock")
    app.setDesktopFileName("powerclock")  # Wayland: matches powerclock.desktop and its icon
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale.system(), "qtbase", "_", folder):
        app.installTranslator(translator)
    return app


def run(*, tray_only: bool) -> int:
    import qasync

    app = application()
    app.setQuitOnLastWindowClosed(False)

    from powerclock.gui.single import SingleInstance

    single = SingleInstance(f"powerclock-gui-{getpass.getuser()}")
    if single.forward("tray" if tray_only else "show"):
        return 0  # the running instance shows its window

    from powerclock.gui.controller import Controller

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    closed = asyncio.Event()
    app.aboutToQuit.connect(closed.set)
    with loop:
        controller = Controller(app)
        single.listen(controller.on_request)
        controller.start(show_window=not tray_only)
        loop.run_until_complete(closed.wait())
        with contextlib.suppress(Exception):
            loop.run_until_complete(controller.stop())
    return 0


def run_setup() -> int:
    import qasync

    app = application()

    from powerclock.gui.setup import SetupWindow

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    closed = asyncio.Event()
    app.aboutToQuit.connect(closed.set)
    with loop:
        window = SetupWindow()
        window.finished.connect(lambda _result: app.quit())
        window.show()
        loop.run_until_complete(closed.wait())
    return 0
