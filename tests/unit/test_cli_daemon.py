"""The CLI against a real daemon (fake backend, dry-run) running in TestClient's thread."""

import json
import socket
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from powerclock.cli import client as api
from powerclock.cli.main import app
from powerclock.config import Paths
from powerclock.daemon.core import Daemon
from powerclock.models import RunStep
from powerclock.platform.fake import FakePlatform
from powerclock.sensors.fake import FakeReadings
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


def powerclock(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def powerclock_fails(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 1, result.output
    return result.output


def test_quick_shutdown_status_cancel_history(daemon: Daemon) -> None:
    """The M4 definition of done, through the CLI."""
    output = powerclock("shutdown", "--in", "2m")
    assert "Shut down in 2m" in output
    assert "in 1m 5" in output or "in 2m" in output

    status = powerclock("status")
    assert "Test mode" in status
    assert "Next" in status
    assert "Shut down in 2m" in status

    assert "Cancelled: Shut down in 2m" in powerclock("cancel")
    assert "Nothing scheduled." in powerclock("status")

    history = powerclock("history")
    assert "Shut down in 2m" in history
    assert "cancelled before it fired" in history
    assert "1 of 1 runs" in history


def test_global_dry_run_and_options(daemon: Daemon) -> None:
    powerclock("--dry-run", "suspend", "--at", "23:30", "--force", "--warning", "2m")
    [rule] = daemon.engine.rules.values()
    assert rule.dry_run
    assert rule.warning.total_seconds() == 120
    assert rule.actions[0].mode == "force"  # type: ignore[union-attr]
    assert rule.name.endswith("23:30")


def test_run_a_program_later(daemon: Daemon) -> None:
    powerclock("run", "--in", "10m", "--", "backup.sh", "--full")
    [rule] = daemon.engine.rules.values()
    assert isinstance(rule.actions[0], RunStep)
    assert rule.actions[0].cmd == ["backup.sh", "--full"]
    assert rule.name == "Run backup.sh in 10m"


def test_postpone(daemon: Daemon) -> None:
    powerclock("reboot", "--in", "5m")
    assert "Postponed: Restart in 5m" in powerclock("postpone", "10m")
    assert "run 'nope' is not counting down" in powerclock_fails("postpone", "--run", "nope")


def test_errors_are_explained(daemon: Daemon) -> None:
    assert "invalid duration" in powerclock_fails("shutdown", "--in", "5 minutes")
    assert "nothing to cancel" in powerclock_fails("cancel")
    assert "no rule 'missing'" in powerclock_fails("rules", "show", "missing")


def test_rules_commands(daemon: Daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "No rules yet" in powerclock("rules", "list")
    assert "Added: backup-nocturno" in powerclock(
        "rules", "add", str(ROOT / "examples" / "backup-nocturno.json")
    )
    listing = powerclock("rules", "list")
    assert "backup-nocturno" in listing
    assert "cron 0 3 * * *" in listing
    assert json.loads(powerclock("rules", "show", "backup-nocturno"))["name"] == "Backup nocturno"

    assert "Disabled" in powerclock("rules", "disable", "backup-nocturno")
    assert not daemon.engine.rules["backup-nocturno"].enabled
    assert "Enabled" in powerclock("rules", "enable", "backup-nocturno")

    edited = {**json.loads(powerclock("rules", "show", "backup-nocturno")), "name": "Copia"}
    monkeypatch.setattr("click.edit", lambda text, extension: json.dumps(edited))
    assert "Saved: backup-nocturno — Copia" in powerclock("rules", "edit", "backup-nocturno")
    monkeypatch.setattr("click.edit", lambda text, extension: None)
    assert "No changes." in powerclock("rules", "edit", "backup-nocturno")

    export = tmp_path / "export.json"
    assert "Exported 1 rule(s)" in powerclock("rules", "export", str(export))
    assert json.loads(powerclock("rules", "export"))["rules"][0]["name"] == "Copia"
    assert "Skipped (already exists): backup-nocturno" in powerclock("rules", "import", str(export))
    assert "Imported: backup-nocturno" in powerclock("rules", "import", str(export), "--replace")

    assert "Started: Copia" in powerclock("rules", "run", "backup-nocturno")
    assert "Deleted: backup-nocturno" in powerclock("rules", "rm", "backup-nocturno")
    assert daemon.engine.rules == {}


def test_import_every_example(daemon: Daemon) -> None:
    for example in sorted((ROOT / "examples").glob("*.json")):
        powerclock("rules", "import", str(example))
    assert len(daemon.engine.rules) == 5


def test_daemon_never_ran() -> None:
    output = powerclock_fails("status")  # POWERCLOCK_HOME is an empty temporary directory
    assert "no API token" in output
    assert "powerclock service install" in output


def test_daemon_not_running() -> None:
    paths = Paths.default()
    paths.config.mkdir(parents=True)
    paths.token.write_text("secret")
    with socket.socket() as probe:  # a free port where nothing listens
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    paths.settings.write_text(json.dumps({"port": port}))
    output = powerclock_fails("status")
    assert "PowerClock is not running in the background" in output


def test_wake_commands(daemon: Daemon) -> None:
    tomorrow = f"{date.today() + timedelta(days=1)} 07:30"  # always in the future
    output = powerclock("wake", "--at", tomorrow)
    assert f"Turn on at {tomorrow}" in output
    assert "wake-up alarm" in output
    assert "wake-up alarm" in powerclock("status")
    output = powerclock("suspend", "--at", "23:30", "--wake", "07:30")
    assert "wake-up alarm" in output
    powerclock("run", "--at", "03:00", "--wake", "--", "backup.sh")
    wake_rules = [rule for rule in daemon.engine.rules.values() if rule.wake]
    assert len(wake_rules) == 3


def test_shutdown_when_a_program_exits(daemon: Daemon) -> None:
    output = powerclock("shutdown", "--when-exits", "ffmpeg")
    assert "Shut down when ffmpeg ends" in output
    assert "ffmpeg is not running yet: waiting for it to start" in output
    assert "postpone" not in output
    status = powerclock("status")
    assert "Watching" in status
    assert "Shut down when ffmpeg ends" in status
    assert "Cancelled: Shut down when ffmpeg ends" in powerclock("cancel")
    assert "Nothing scheduled." in powerclock("status")


def test_when_options(daemon: Daemon) -> None:
    powerclock("reboot", "--when-cpu-below", "10", "--for", "2m")
    powerclock("suspend", "--when-idle", "20m")
    powerclock("run", "--when-net-below", "50", "--", "notify-send", "done")
    names = sorted(rule.name for rule in daemon.engine.rules.values())
    assert names == [
        "Restart when the computer goes quiet (CPU below 10 % for 2m)",
        "Run notify-send when the download finishes (network below 50 kbit/s for 5m)",
        "Suspend after 20m without use",
    ]
    status = powerclock("status")
    assert "measuring…" in status
    assert "idle for 0s" in status
    assert "cancel it instead" in powerclock_fails("postpone")
    powerclock_fails("shutdown", "--when-idle", "20m", "--in", "5m")


def test_reasons_are_readable_and_keep_brackets(daemon: Daemon) -> None:
    powerclock("run", "--", "/nonexistent/powerclock-program")
    for _ in range(200):  # a real (missing) program: wait for its run in real time
        if daemon.history.list(limit=1):
            break
        time.sleep(0.01)
    history = powerclock("history")
    assert "step 1 (Run a program) failed: [Errno 2]" in history


def test_apps_recipes_and_launch(daemon: Daemon) -> None:
    listed = powerclock("apps")
    assert "Okular" in listed
    assert "org.kde.okular" in listed
    assert "(Flatpak)" in listed
    assert "vlc.loop" in powerclock("apps", "vlc")
    assert "Okular" not in powerclock("apps", "vlc")
    assert "--presentation" in powerclock("recipes", "org.kde.okular")
    output = powerclock("launch", "org.kde.okular", "--in", "10m", "--", "--page=3", "a.pdf")
    assert "Open Okular in 10m" in output
    powerclock("launch", "vlc", "--recipe", "vlc.loop", "--at", "23:00", "--", "~/Música")
    launches = [
        step
        for rule in daemon.engine.rules.values()
        for step in rule.actions
        if step.type == "launch"
    ]
    assert [step.args for step in launches] == [
        ["--page=3", "a.pdf"],
        ["--fullscreen", "--loop", "--random", "~/Música"],
    ]
    assert "needs: <file>" in powerclock_fails("launch", "vlc", "--recipe", "vlc.loop")
    assert "no recipe 'nope'" in powerclock_fails("launch", "vlc", "--recipe", "nope")
