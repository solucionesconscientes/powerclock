"""Menu entry and login start (.desktop files), one instance per user, and `kse gui`."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from guisupport import pump
from kse.cli import main as cli
from kse.gui.single import SingleInstance
from kse.platform.linux import autostart


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {"XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CONFIG_HOME": str(tmp_path / "config")}


def test_menu_entry(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart, "gui_executable", lambda: Path("/home/pc/.local/bin/kse-gui"))
    assert not autostart.in_menu(env)
    autostart.set_menu(True, env)
    assert autostart.in_menu(env)
    entry = autostart.menu_path(env).read_text()
    assert "Exec=/home/pc/.local/bin/kse-gui\n" in entry
    assert "Icon=kse\n" in entry
    assert "GenericName[es]=Programador de energía y tareas" in entry
    assert autostart.icon_path(env).read_text().startswith("<svg")
    autostart.set_menu(False, env)
    assert not autostart.in_menu(env)
    assert not autostart.icon_path(env).exists()


def test_login_start(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart, "gui_executable", lambda: Path("/opt/my apps/kse-gui"))
    autostart.set_login(True, env)
    entry = autostart.autostart_path(env).read_text()
    assert 'Exec="/opt/my apps/kse-gui" --tray' in entry
    assert "X-GNOME-Autostart-enabled=true" in entry
    assert autostart.at_login(env)
    assert autostart.set_login(False, env) == [f"removed {autostart.autostart_path(env)}"]
    assert autostart.set_login(False, env) == []


async def test_single_instance(qapp: object, tmp_path: Path) -> None:
    name = f"kse-gui-test-{tmp_path.name}"
    first = SingleInstance(name)
    assert not first.forward("show")  # nobody is listening yet
    received: list[str] = []
    first.listen(received.append)
    second = SingleInstance(name)
    assert second.forward("show")
    for _ in range(20):
        await pump(10)
        if received:
            break
    assert received == ["show"]


def test_kse_gui_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "kse-gui"
    executable.write_text("")
    started: list[Any] = []
    monkeypatch.setattr(cli, "gui_executable", lambda: executable)
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: started.append(command))
    result = CliRunner().invoke(cli.app, ["gui", "--tray"])
    assert result.exit_code == 0, result.output
    assert started == [[str(executable), "--tray"]]
    monkeypatch.setattr(cli, "gui_executable", lambda: None)
    result = CliRunner().invoke(cli.app, ["gui"])
    assert result.exit_code == 1
    assert "pipx install --force 'kse[gui]'" in result.output
