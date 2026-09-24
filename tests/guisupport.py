"""Helpers for the GUI tests (importable thanks to `pythonpath = ["tests"]`)."""

import asyncio


async def pump(rounds: int = 150) -> None:
    """Let requests, events and Qt signals run until things settle."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    for _ in range(rounds):
        if app is not None:
            app.processEvents()
        await asyncio.sleep(0)
