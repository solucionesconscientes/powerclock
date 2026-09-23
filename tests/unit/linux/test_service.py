from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kse.cli.main import app
from kse.platform.linux import service


class FakeSystemctl:
    def __init__(self, failing: str | None = None) -> None:
        self.ran: list[list[str]] = []
        self.failing = failing

    def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        self.ran.append(list(argv))
        if self.failing and self.failing in argv:
            return 1, "Failed to connect to bus"
        if "is-active" in argv:
            return 3, "inactive"
        if "is-enabled" in argv:
            return 0, "enabled"
        return 0, ""


def test_unit_file() -> None:
    unit = service.render_unit(Path("/venv/bin/kse-daemon"), dry_run=False)
    assert "ExecStart=/venv/bin/kse-daemon --foreground\n" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert "KSE_DRY_RUN" not in unit
    dry = service.render_unit(Path("/venv/bin/kse-daemon"), dry_run=True)
    assert "Environment=KSE_DRY_RUN=1\n" in dry


def test_unit_path_follows_xdg(tmp_path: Path) -> None:
    assert service.unit_path({"XDG_CONFIG_HOME": str(tmp_path)}) == (
        tmp_path / "systemd" / "user" / "kse.service"
    )


def test_install_uninstall_and_status(tmp_path: Path) -> None:
    unit = tmp_path / "kse.service"
    systemctl = FakeSystemctl()
    done = service.install(
        dry_run=True,
        linger_user="pc",
        runner=systemctl,
        path=unit,
        executable=Path("/venv/bin/kse-daemon"),
    )
    assert "KSE_DRY_RUN=1" in unit.read_text()
    assert systemctl.ran == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "kse.service"],
        ["systemctl", "--user", "restart", "kse.service"],
        ["loginctl", "enable-linger", "pc"],
    ]
    assert done[-1] == "linger enabled for pc"

    state = service.status(runner=systemctl, path=unit)
    assert (state.installed, state.active, state.enabled) == (True, "inactive", "enabled")

    systemctl.ran.clear()
    service.uninstall(runner=systemctl, path=unit)
    assert not unit.exists()
    assert systemctl.ran == [
        ["systemctl", "--user", "disable", "--now", "kse.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_install_failure_is_reported(tmp_path: Path) -> None:
    with pytest.raises(service.ServiceError, match="Failed to connect to bus"):
        service.install(
            dry_run=False,
            runner=FakeSystemctl(failing="enable"),
            path=tmp_path / "kse.service",
            executable=Path("/venv/bin/kse-daemon"),
        )


def test_daemon_executable_is_next_to_the_interpreter() -> None:
    assert service.daemon_executable().name == "kse-daemon"


def test_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("COLUMNS", "300")  # the unit path must not wrap
    systemctl = FakeSystemctl()
    monkeypatch.setattr(service, "run", systemctl)
    runner = CliRunner()
    result = runner.invoke(app, ["service", "install", "--dry-run"])
    assert result.exit_code == 0, result.output
    unit = tmp_path / "xdg-config" / "systemd" / "user" / "kse.service"  # conftest's XDG home
    assert f"wrote {unit}" in result.output
    assert "KSE_DRY_RUN=1" in unit.read_text()
    status = runner.invoke(app, ["service", "status"])
    assert "active: inactive · enabled: enabled" in status.output
    assert runner.invoke(app, ["service", "uninstall"]).exit_code == 0
    assert not unit.exists()


def test_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "run", FakeSystemctl(failing="daemon-reload"))
    result = CliRunner().invoke(app, ["service", "install"])
    assert result.exit_code == 1
    assert "daemon-reload failed" in result.output
