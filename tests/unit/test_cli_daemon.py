"""The CLI against a real daemon (fake backend, dry-run) running in TestClient's thread."""

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kse.cli import client as api
from kse.cli.main import app
from kse.config import Paths
from kse.daemon.core import Daemon
from kse.models import RunStep
from kse.platform.fake import FakePlatform
from kse.sensors.fake import FakeReadings
from support import MADRID

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # rich tables: no wrapping in the assertions


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Daemon]:
    backend = FakePlatform(timezone=MADRID)
    daemon = Daemon(
        backend,
        paths=Paths(tmp_path / "c", tmp_path / "d"),
        dry_run=True,
        readings=FakeReadings(),
    )
    headers = {"Authorization": f"Bearer {daemon.token}"}
    with TestClient(daemon.app, headers=headers) as http:
        monkeypatch.setattr(api, "connect", lambda paths=None: api.Client(http))
        yield daemon


def kse(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def kse_fails(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 1, result.output
    return result.output


def test_quick_shutdown_status_cancel_history(daemon: Daemon) -> None:
    """The M4 definition of done, through the CLI."""
    output = kse("shutdown", "--in", "2m")
    assert "Shut down in 2m" in output
    assert "in 1m 5" in output or "in 2m" in output

    status = kse("status")
    assert "Dry run" in status
    assert "Next" in status
    assert "Shut down in 2m" in status

    assert "Cancelled: Shut down in 2m" in kse("cancel")
    assert "Nothing scheduled." in kse("status")

    history = kse("history")
    assert "Shut down in 2m" in history
    assert "cancelled before it fired" in history
    assert "1 of 1 runs" in history


def test_global_dry_run_and_options(daemon: Daemon) -> None:
    kse("--dry-run", "suspend", "--at", "23:30", "--force", "--warning", "2m")
    [rule] = daemon.engine.rules.values()
    assert rule.dry_run
    assert rule.warning.total_seconds() == 120
    assert rule.actions[0].mode == "force"  # type: ignore[union-attr]
    assert rule.name.endswith("23:30")


def test_run_a_program_later(daemon: Daemon) -> None:
    kse("run", "--in", "10m", "--", "backup.sh", "--full")
    [rule] = daemon.engine.rules.values()
    assert isinstance(rule.actions[0], RunStep)
    assert rule.actions[0].cmd == ["backup.sh", "--full"]
    assert rule.name == "Run backup.sh in 10m"


def test_postpone(daemon: Daemon) -> None:
    kse("reboot", "--in", "5m")
    assert "Postponed: Restart in 5m" in kse("postpone", "10m")
    assert "run 'nope' is not counting down" in kse_fails("postpone", "--run", "nope")


def test_errors_are_explained(daemon: Daemon) -> None:
    assert "invalid duration" in kse_fails("shutdown", "--in", "5 minutes")
    assert "nothing to cancel" in kse_fails("cancel")
    assert "no rule 'missing'" in kse_fails("rules", "show", "missing")


def test_rules_commands(daemon: Daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "No rules yet" in kse("rules", "list")
    assert "Added: backup-nocturno" in kse(
        "rules", "add", str(ROOT / "examples" / "backup-nocturno.json")
    )
    listing = kse("rules", "list")
    assert "backup-nocturno" in listing
    assert "cron 0 3 * * *" in listing
    assert json.loads(kse("rules", "show", "backup-nocturno"))["name"] == "Backup nocturno"

    assert "Disabled" in kse("rules", "disable", "backup-nocturno")
    assert not daemon.engine.rules["backup-nocturno"].enabled
    assert "Enabled" in kse("rules", "enable", "backup-nocturno")

    edited = {**json.loads(kse("rules", "show", "backup-nocturno")), "name": "Copia"}
    monkeypatch.setattr("click.edit", lambda text, extension: json.dumps(edited))
    assert "Saved: backup-nocturno — Copia" in kse("rules", "edit", "backup-nocturno")
    monkeypatch.setattr("click.edit", lambda text, extension: None)
    assert "No changes." in kse("rules", "edit", "backup-nocturno")

    export = tmp_path / "export.json"
    assert "Exported 1 rule(s)" in kse("rules", "export", str(export))
    assert json.loads(kse("rules", "export"))["rules"][0]["name"] == "Copia"
    assert "Skipped (already exists): backup-nocturno" in kse("rules", "import", str(export))
    assert "Imported: backup-nocturno" in kse("rules", "import", str(export), "--replace")

    assert "Started: Copia" in kse("rules", "run", "backup-nocturno")
    assert "Deleted: backup-nocturno" in kse("rules", "rm", "backup-nocturno")
    assert daemon.engine.rules == {}


def test_import_every_example(daemon: Daemon) -> None:
    for example in sorted((ROOT / "examples").glob("*.json")):
        kse("rules", "import", str(example))
    assert len(daemon.engine.rules) == 5


def test_daemon_never_ran() -> None:
    output = kse_fails("status")  # KSE_HOME is an empty temporary directory
    assert "no API token yet" in output
    assert "kse service install" in output


def test_daemon_not_running() -> None:
    paths = Paths.default()
    paths.config.mkdir(parents=True)
    paths.token.write_text("secret")
    with socket.socket() as probe:  # a free port where nothing listens
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    paths.settings.write_text(json.dumps({"port": port}))
    output = kse_fails("status")
    assert "the kse daemon is not running" in output


def test_wake_commands(daemon: Daemon) -> None:
    output = kse("wake", "--at", "2026-09-25 07:30")
    assert "Wake up at 2026-09-25 07:30" in output
    assert "wake-up alarm" in output
    assert "wake-up alarm" in kse("status")
    output = kse("suspend", "--at", "23:30", "--wake", "07:30")
    assert "wake-up alarm" in output
    kse("run", "--at", "03:00", "--wake", "--", "backup.sh")
    wake_rules = [rule for rule in daemon.engine.rules.values() if rule.wake]
    assert len(wake_rules) == 3


def test_shutdown_when_a_program_exits(daemon: Daemon) -> None:
    output = kse("shutdown", "--when-exits", "ffmpeg")
    assert "Shut down when ffmpeg exits" in output
    assert "ffmpeg is not running yet: waiting for it to start" in output
    assert "postpone" not in output
    status = kse("status")
    assert "Watching" in status
    assert "Shut down when ffmpeg exits" in status
    assert "Cancelled: Shut down when ffmpeg exits" in kse("cancel")
    assert "Nothing scheduled." in kse("status")


def test_when_options(daemon: Daemon) -> None:
    kse("reboot", "--when-cpu-below", "10", "--for", "2m")
    kse("suspend", "--when-idle", "20m")
    kse("run", "--when-net-below", "50", "--", "notify-send", "done")
    names = sorted(rule.name for rule in daemon.engine.rules.values())
    assert names == [
        "Restart when the CPU is below 10 % for 2m",
        "Run notify-send when the network is below 50 kbit/s for 5m",
        "Suspend when idle for 20m",
    ]
    status = kse("status")
    assert "measuring…" in status
    assert "idle for 0s" in status
    assert "cancel it instead" in kse_fails("postpone")
    kse_fails("shutdown", "--when-idle", "20m", "--in", "5m")
