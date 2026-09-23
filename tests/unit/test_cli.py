import json
from importlib.metadata import distribution

from typer.testing import CliRunner

from kse import __version__
from kse.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"kse {__version__}"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_entry_points_resolve() -> None:
    scripts = {
        ep.name: ep for ep in distribution("kse").entry_points if ep.group == "console_scripts"
    }
    assert set(scripts) == {"kse", "kse-daemon", "kse-gui"}
    for entry_point in scripts.values():
        assert callable(entry_point.load())


def test_doctor_table() -> None:
    result = runner.invoke(app, ["doctor"])  # KSE_BACKEND=fake, KSE_DRY_RUN=1 (conftest)
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
