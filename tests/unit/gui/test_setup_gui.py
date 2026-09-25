"""The installation window, the one-time welcome, and updating / uninstalling from the
Diagnostics tab. The steps run against fake modules: nothing is installed."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from fakeinstall import FakeDesktop, FakeHelper, FakeService
from guisupport import pump
from powerclock.config import Paths
from powerclock.gui.client import DaemonLink
from powerclock.gui.controller import Controller
from powerclock.gui.maintenance import MaintenanceBox
from powerclock.gui.setup import SetupWindow
from powerclock.gui.welcome import WelcomeDialog, remember_welcomed, welcomed
from powerclock.install import program
from powerclock.install.steps import Setup


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(
        service=FakeService(),
        helper=FakeHelper(),
        desktop=FakeDesktop(),
        paths=Paths(tmp_path / "config", tmp_path / "data"),
        user="pc",
    )


async def settle_thread(check: Any, seconds: float = 3.0) -> None:
    """Wait for work done in a worker thread (asyncio.to_thread)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not check() and loop.time() < deadline:
        await pump(10)
        await asyncio.sleep(0.01)


def boxes() -> list[QMessageBox]:
    widgets = QApplication.topLevelWidgets()
    return [w for w in widgets if isinstance(w, QMessageBox) and w.isVisible()]


# ── Installation window ───────────────────────────────────────────────────────


async def test_install_from_the_window(qapp: object, setup: Setup) -> None:
    passwords: list[list[list[str]]] = []
    launched: list[bool] = []
    window = SetupWindow(
        setup,
        run_root=lambda commands: passwords.append(commands) or True,
        launch=lambda: launched.append(True),
    )
    assert window.options().menu
    assert window.options().login
    assert window.options().helper
    assert not window.unattended.isChecked()
    window.unattended.setChecked(True)
    window.install()
    await settle_thread(lambda: window.report is not None)
    assert window.report is not None
    assert window.report.ok
    assert window.status.text() == "✔ PowerClock is ready."
    assert len(passwords) == 1  # one password for the helper and its unattended rule
    assert setup.service.calls == [("install", (True, "pc"))]  # type: ignore[union-attr]
    assert not window.open_button.isHidden()
    window.open_button.click()
    assert launched == [True]


async def test_without_the_helper_no_password_is_asked(qapp: object, setup: Setup) -> None:
    asked: list[Any] = []
    window = SetupWindow(
        setup, run_root=lambda commands: asked.append(1) or True, launch=lambda: None
    )
    window.helper.setChecked(False)
    assert not window.unattended.isEnabled()
    window.install()
    await settle_thread(lambda: window.report is not None)
    assert asked == []


async def test_a_cancelled_password_is_explained(qapp: object, setup: Setup) -> None:
    window = SetupWindow(setup, run_root=lambda commands: False, launch=lambda: None)
    window.install()
    await settle_thread(lambda: window.report is not None)
    assert "allow it later from Diagnostics" in window.log.toPlainText()
    assert window.status.text() == "PowerClock is installed, with the notes above."


async def test_no_helper_on_this_system(qapp: object, tmp_path: Path) -> None:
    bare = Setup(service=FakeService(), desktop=FakeDesktop(), paths=Paths(tmp_path, tmp_path))
    bare.helper = None
    window = SetupWindow(bare, run_root=lambda commands: True, launch=lambda: None)
    assert not window.helper.isEnabled()
    assert not window.options().helper


# ── Welcome ───────────────────────────────────────────────────────────────────


def test_welcome_is_remembered(qapp: object, tmp_path: Path) -> None:
    paths = Paths(tmp_path, tmp_path)
    assert not welcomed(paths)
    dialog = WelcomeDialog(paths)
    dialog.accept()
    assert welcomed(paths)
    remember_welcomed(paths)
    assert welcomed(paths)


async def test_welcome_shows_once_with_the_window(link: DaemonLink) -> None:
    app = SimpleNamespace(quit=lambda: None)
    controller = Controller(app, api=link.api, stream=None, tray=True, welcome=True)  # type: ignore[arg-type]
    controller.start(show_window=True)
    assert controller.welcome is not None
    first = controller.welcome
    controller.window.close()  # type: ignore[union-attr]
    await pump()
    controller.show_window()
    assert controller.welcome is first  # not again
    await controller.stop()


# ── Updates and uninstall ────────────────────────────────────────────────────


def box_for(setup: Setup, **kwargs: Any) -> MaintenanceBox:
    options: dict[str, Any] = {
        "commands": lambda: program.Commands(["uv", "upgrade"], ["uv", "uninstall"]),
        "run": lambda command: 0,
        "run_root": lambda commands: True,
        "restart": lambda: None,
        "quit_app": lambda: None,
    }
    options.update(kwargs)
    return MaintenanceBox(setup, **options)


async def test_check_and_update(qapp: object, setup: Setup) -> None:
    ran: list[list[str]] = []
    restarted: list[bool] = []

    async def latest() -> str:
        return "9.9.9"

    setup.service.installed = True  # type: ignore[union-attr]
    box = box_for(
        setup,
        latest=latest,
        run=lambda c: ran.append(c) or 0,
        restart=lambda: restarted.append(True),
    )
    box.check()
    await pump()
    assert box.status.text() == "PowerClock 9.9.9 is out."
    assert box.update_button.text() == "Update to 9.9.9"
    box.update_now()
    await settle_thread(lambda: restarted)
    assert ran == [["uv", "upgrade"]]
    assert setup.service.calls == [("restart", None)]  # type: ignore[union-attr]
    assert restarted == [True]


async def test_up_to_date_or_unreachable(qapp: object, setup: Setup) -> None:
    async def old() -> str:
        return "0.0.1"

    async def offline() -> str:
        raise OSError("no network")

    box = box_for(setup, latest=old)
    box.check()
    await pump()
    assert box.status.text() == "You have the newest version."
    assert box.update_button.isHidden()
    box = box_for(setup, latest=offline)
    box.check()
    await pump()
    assert box.status.text() == "Could not check for updates: no network"
    assert box.check_button.isEnabled()


async def test_uninstall(qapp: object, setup: Setup) -> None:
    ran: list[list[str]] = []
    quits: list[bool] = []
    setup.service.installed = True  # type: ignore[union-attr]
    box = box_for(setup, run=lambda c: ran.append(c) or 0, quit_app=lambda: quits.append(True))
    question = box.confirm_uninstall()
    question.checkBox().setChecked(True)  # also delete rules and history
    question.done(QMessageBox.StandardButton.Yes)
    await settle_thread(lambda: ran)
    await settle_thread(lambda: boxes())
    assert setup.service.calls == [("uninstall", None)]  # type: ignore[union-attr]
    assert ran == [["uv", "uninstall"]]
    [done] = boxes()
    assert done.text() == "PowerClock was uninstalled."
    done.close()
    await pump()
    assert quits == [True]
