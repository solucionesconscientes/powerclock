import json
from importlib.metadata import distribution

from typer.testing import CliRunner

from powerclock import __version__
from powerclock.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"powerclock {__version__}"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_entry_points_resolve() -> None:
    scripts = {
        (ep.group, ep.name): ep
        for ep in distribution("powerclock").entry_points
        if ep.group in ("console_scripts", "gui_scripts")
    }
    assert set(scripts) == {
        ("console_scripts", "powerclock"),
        ("console_scripts", "powerclock-daemon"),
        ("gui_scripts", "powerclock-gui"),  # no console window on Windows
    }
    for entry_point in scripts.values():
        assert callable(entry_point.load())


def test_doctor_table() -> None:
    result = runner.invoke(
        app, ["doctor"]
    )  # POWERCLOCK_BACKEND=fake, POWERCLOCK_DRY_RUN=1 (conftest)
    assert result.exit_code == 0
    assert "fake (dry-run)" in result.output
    assert "power.shutdown" in result.output
    assert "power_source" in result.output


def test_doctor_json() -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert {"id", "supported", "detail", "fix_hint"} <= set(rows[0])
    assert "sensors" in {row["id"] for row in rows}
