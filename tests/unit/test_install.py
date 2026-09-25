"""Setting PowerClock up and taking it out (install/steps.py), how it was installed and its
updates (install/program.py), and the setup / update / uninstall commands."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from fakeinstall import FakeDesktop, FakeHelper, FakeService
from powerclock.cli import main as cli
from powerclock.config import Paths
from powerclock.install import program
from powerclock.install.steps import Options, Setup


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data")


def make(paths: Paths, **kwargs: Any) -> Setup:
    options: dict[str, Any] = {
        "service": FakeService(),
        "helper": FakeHelper(),
        "desktop": FakeDesktop(),
        "paths": paths,
        "user": "pc",
    }
    options.update(kwargs)
    return Setup(**options)


# ── Steps ─────────────────────────────────────────────────────────────────────


def test_install_everything(paths: Paths) -> None:
    setup = make(paths)
    ran: list[list[list[str]]] = []
    report = setup.install(Options(), lambda commands: ran.append(commands) or True)
    assert report.ok
    assert setup.desktop.menu  # type: ignore[union-attr]
    assert setup.desktop.login  # type: ignore[union-attr]
    assert setup.service.calls == [("install", (False, None))]  # type: ignore[union-attr]
    [commands] = ran  # the password is asked once, for every root command together
    assert len(commands) == 2
    assert report.done == [
        "In the applications menu",
        "Tray icon when the session starts",
        "Running in the background",
        "PowerClock can turn the computer on",
    ]


def test_unattended_and_dry_run(paths: Paths) -> None:
    setup = make(paths)
    setup.install(Options(unattended=True, dry_run=True), lambda commands: True)
    assert setup.service.calls == [("install", (True, "pc"))]  # type: ignore[union-attr]
    [call] = setup.helper.install_calls  # type: ignore[union-attr]
    assert call == {"user": "pc", "rules_file": paths.data / "50-powerclock-unattended.rules"}


def test_cancelled_password_leaves_the_rest_working(paths: Paths) -> None:
    setup = make(paths)
    report = setup.install(Options(), lambda commands: False)
    assert not report.ok
    assert "allow it later from Diagnostics" in report.problems[0]
    assert setup.service.installed  # type: ignore[union-attr]


def test_options_left_out(paths: Paths) -> None:
    setup = make(paths)
    asked: list[Any] = []
    report = setup.install(
        Options(menu=False, login=False, helper=False), lambda commands: asked.append(1) or True
    )
    assert report.ok
    assert asked == []
    assert not setup.desktop.menu  # type: ignore[union-attr]


def test_a_failing_step_is_reported(paths: Paths) -> None:
    class Broken(FakeService):
        def install(self, *, dry_run: bool, linger_user: str | None = None) -> list[str]:
            raise OSError("systemctl --user failed")

    report = make(paths, service=Broken()).install(Options(helper=False), lambda c: True)
    assert report.problems == ["background service: systemctl --user failed"]


def test_uninstall(paths: Paths) -> None:
    setup = make(paths, service=FakeService(installed=True))
    setup.desktop.set_menu(True)  # type: ignore[union-attr]
    paths.config.mkdir(parents=True)
    (paths.config / "rules.json").write_text("{}")
    report = setup.uninstall(lambda commands: True)
    assert report.ok
    assert setup.service.calls == [("uninstall", None)]  # type: ignore[union-attr]
    assert not setup.desktop.menu  # type: ignore[union-attr]
    assert (paths.config / "rules.json").exists()  # kept unless asked
    setup.uninstall(lambda commands: True, remove_data=True)
    assert not paths.config.exists()


# ── Program: how it was installed, updates ───────────────────────────────────


@pytest.mark.parametrize(
    ("prefix", "kind"),
    [
        ("/home/pc/.local/share/uv/tools/powerclock", "installer"),
        ("/home/pc/.local/share/pipx/venvs/powerclock", "pipx"),
        ("/home/pc/src/powerclock/.venv", "other"),
    ],
)
def test_installed_by(prefix: str, kind: str) -> None:
    assert program.installed_by(Path(prefix)) == kind


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("0.1.1", "0.1.0", True),
        ("0.2.0", "0.1.9", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.1.0.dev0", True),  # the release is newer than its development version
        ("0.2.0rc1", "0.2.0", False),
        ("1.0", "0.9.9", True),
    ],
)
def test_newer(latest: str, current: str, newer: bool) -> None:
    assert program.newer(latest, current) is newer


def test_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    uv = program.private_uv()
    uv.parent.mkdir(parents=True)
    uv.write_text("")
    installer = program.commands("installer")
    assert installer.upgrade == [str(uv), "tool", "upgrade", "powerclock"]
    assert installer.uninstall == [str(uv), "tool", "uninstall", "powerclock"]
    assert program.commands("other") == program.Commands(None, None)


async def test_latest_version() -> None:
    def pypi(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == program.PYPI
        return httpx.Response(200, json={"info": {"version": "0.3.1"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(pypi)) as client:
        assert await program.latest_version(client) == "0.3.1"


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_setup_command(monkeypatch: pytest.MonkeyPatch, paths: Paths) -> None:
    setup = make(paths)
    monkeypatch.setattr(cli, "Setup", lambda: setup)
    monkeypatch.setattr(cli, "_as_root", lambda module, commands: True)
    result = CliRunner().invoke(cli.app, ["setup", "--unattended", "--no-menu"])
    assert result.exit_code == 0, result.output
    assert "PowerClock is ready" in result.output
    assert setup.service.calls == [("install", (True, "pc"))]  # dry run: POWERCLOCK_DRY_RUN=1
    assert not setup.desktop.menu  # type: ignore[union-attr]


def test_uninstall_command(monkeypatch: pytest.MonkeyPatch, paths: Paths) -> None:
    setup = make(paths, service=FakeService(installed=True))
    ran: list[list[str]] = []
    monkeypatch.setattr(cli, "Setup", lambda: setup)
    monkeypatch.setattr(cli, "_as_root", lambda module, commands: True)
    monkeypatch.setattr(cli, "program_commands", lambda: program.Commands(None, ["uv", "x"]))
    monkeypatch.setattr(cli.subprocess, "run", lambda command, check: ran.append(command))
    result = CliRunner().invoke(cli.app, ["uninstall", "--yes"])
    assert result.exit_code == 0, result.output
    assert ran == [["uv", "x"]]
    assert "PowerClock uninstalled" in result.output


def test_update_command(monkeypatch: pytest.MonkeyPatch, paths: Paths) -> None:
    setup = make(paths, service=FakeService(installed=True))
    ran: list[list[str]] = []

    async def latest() -> str:
        return "9.0.0"

    class Done:
        returncode = 0

    monkeypatch.setattr(cli, "Setup", lambda: setup)
    monkeypatch.setattr(cli, "latest_version", latest)
    monkeypatch.setattr(cli, "program_commands", lambda: program.Commands(["uv", "up"], None))
    monkeypatch.setattr(cli.subprocess, "run", lambda command, check: ran.append(command) or Done())
    result = CliRunner().invoke(cli.app, ["update"])
    assert result.exit_code == 0, result.output
    assert ran == [["uv", "up"]]
    assert setup.service.calls == [("restart", None)]  # type: ignore[union-attr]
    assert "Updated to 9.0.0" in result.output


def test_update_when_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    async def latest() -> str:
        return "0.0.1"

    monkeypatch.setattr(cli, "latest_version", latest)
    result = CliRunner().invoke(cli.app, ["update"])
    assert result.exit_code == 0
    assert "is the newest version" in result.output
