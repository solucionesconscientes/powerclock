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
