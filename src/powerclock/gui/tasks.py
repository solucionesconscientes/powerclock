"""Coroutines started from Qt handlers: they run on the asyncio loop (qasync in the app) and
their errors are shown to the user instead of being lost."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from powerclock.connection import ApiError, DaemonUnavailable

log = logging.getLogger(__name__)

ErrorSink = Callable[[Exception, QWidget | None], None]

_running: set[asyncio.Task[Any]] = set()


def message(error: Exception) -> str:
    if isinstance(error, ApiError | DaemonUnavailable):
        return str(error)
    return f"{type(error).__name__}: {error}"


def show_error(error: Exception, parent: QWidget | None = None) -> None:
    """A non-modal message box: it never blocks the event loop."""
    box = QMessageBox(QMessageBox.Icon.Warning, "PowerClock", message(error), parent=parent)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    box.open()


_sink: ErrorSink = show_error


def set_error_sink(sink: ErrorSink) -> ErrorSink:
    """Replace where errors go (tests collect them); returns the previous sink."""
    global _sink
    previous, _sink = _sink, sink
    return previous


def spawn(
    coroutine: Coroutine[Any, Any, Any],
    parent: QWidget | None = None,
    *,
    on_error: Callable[[Exception], None] | None = None,
) -> asyncio.Task[Any]:
    """Run a coroutine in the background; if it fails, `on_error` or a message box says why."""
    task = asyncio.ensure_future(coroutine)
    _running.add(task)

    def done(finished: asyncio.Task[Any]) -> None:
        _running.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if not isinstance(error, Exception):
            return
        if not isinstance(error, ApiError | DaemonUnavailable):
            log.error("background task failed", exc_info=error)
        if on_error is not None:
            on_error(error)
        else:
            _sink(error, parent)

    task.add_done_callback(done)
    return task


def ask(
    parent: QWidget | None, text: str, on_yes: Callable[[], None], *, title: str = "PowerClock"
) -> QMessageBox:
    """A Yes/No question that does not block the event loop; `on_yes` runs on Yes."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def answered(result: int) -> None:
        if result == QMessageBox.StandardButton.Yes:
            on_yes()

    box.finished.connect(answered)
    box.open()
    return box


def inform(parent: QWidget | None, text: str, *, warning: bool = False) -> QMessageBox:
    """A message that does not block the event loop."""
    icon = QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information
    box = QMessageBox(icon, "PowerClock", text, parent=parent)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    box.open()
    return box
