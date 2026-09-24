import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from powerclock.config import (
    DEFAULT_PORT,
    Paths,
    Settings,
    SettingsError,
    atomic_write,
    ensure_token,
    load_settings,
    read_token,
)
from powerclock.timeparse import resolve_at
from support import MADRID


def test_paths_follow_the_home_variable(tmp_path: Path) -> None:
    paths = Paths.default()  # conftest points POWERCLOCK_HOME to a temporary directory
    assert paths.config == paths.data == tmp_path / "powerclock-home"
    assert paths.rules.name == "rules.json"
    assert paths.history.name == "history.sqlite"


def test_paths_default_to_the_xdg_directories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWERCLOCK_HOME")
    paths = Paths.default()
    assert paths.config.name == paths.data.name == "powerclock"
    assert paths.config != paths.data


def test_settings(tmp_path: Path) -> None:
    paths = Paths(tmp_path, tmp_path)
    assert load_settings(paths) == Settings()
    assert Settings().port == DEFAULT_PORT
    paths.settings.write_text('{"port": 48000, "dry_run": true}')
    assert load_settings(paths) == Settings(port=48000, dry_run=True)
    paths.settings.write_text('{"port": 80}')
    with pytest.raises(SettingsError, match=r"daemon\.json"):
        load_settings(paths)


def test_token_is_private_and_stable(tmp_path: Path) -> None:
    path = tmp_path / "config" / "api.token"
    token = ensure_token(path)
    assert len(token) >= 40
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert ensure_token(path) == token
    assert read_token(path) == token
    path.chmod(0o644)
    ensure_token(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    target = tmp_path / "rules.json"
    atomic_write(target, "uno")
    atomic_write(target, "dos")
    assert target.read_text() == "dos"
    assert [p.name for p in tmp_path.iterdir()] == ["rules.json"]


NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)  # 10:00 in Madrid


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10:30", datetime(2026, 9, 24, 8, 30, tzinfo=UTC)),  # later today
        ("09:15", datetime(2026, 9, 25, 7, 15, tzinfo=UTC)),  # already passed: tomorrow
        ("7:05", datetime(2026, 9, 25, 5, 5, tzinfo=UTC)),
        ("2026-12-24 20:00", datetime(2026, 12, 24, 19, 0, tzinfo=UTC)),  # CET in winter
        ("2026-12-24T20:00:00+00:00", datetime(2026, 12, 24, 20, 0, tzinfo=UTC)),
    ],
)
def test_resolve_at(text: str, expected: datetime) -> None:
    assert resolve_at(text, NOW, MADRID) == expected


@pytest.mark.parametrize("text", ["25:00", "12:61", "tomorrow", "", "10.30"])
def test_resolve_at_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="invalid time"):
        resolve_at(text, NOW, MADRID)
