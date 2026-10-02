"""Knowing that a new version is out: what is remembered between runs, and when to ask."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from powerclock import __version__
from powerclock.config import Paths
from powerclock.install import updates

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "config", tmp_path / "data")


def test_nothing_remembered_yet_means_ask(tmp_path: Path) -> None:
    state = updates.read(paths(tmp_path))
    assert state.enabled
    assert state.available is None
    assert state.due(NOW)


def test_what_pypi_said_survives_a_restart(tmp_path: Path) -> None:
    where = paths(tmp_path)
    updates.remember("9.9.9", now=NOW, paths=where)
    state = updates.read(where)
    assert state.seen == "9.9.9"
    assert state.available == "9.9.9"
    assert not state.due(NOW + timedelta(hours=23))
    assert state.due(NOW + timedelta(days=1))


def test_the_version_running_is_not_news(tmp_path: Path) -> None:
    where = paths(tmp_path)
    updates.remember(__version__, now=NOW, paths=where)
    assert updates.read(where).available is None


def test_turning_it_off_stops_the_asking_and_is_remembered(tmp_path: Path) -> None:
    where = paths(tmp_path)
    updates.remember("9.9.9", now=NOW, paths=where)
    assert not updates.set_enabled(False, where).due(NOW + timedelta(days=30))
    assert not updates.read(where).enabled
    assert updates.read(where).seen == "9.9.9"  # forgetting the answer is not the point
    assert updates.set_enabled(True, where).due(NOW + timedelta(days=30))


def test_a_broken_file_is_not_a_crash(tmp_path: Path) -> None:
    where = paths(tmp_path)
    updates.remember("9.9.9", now=NOW, paths=where)
    (where.data / "updates.json").write_text("{ this is not json")
    assert updates.read(where) == updates.State()
