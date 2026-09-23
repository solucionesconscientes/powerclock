from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _safe_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Safety net: no test can reach a real backend, even if it forgets to ask for the fake
    one, nor touch the real ~/.config/kse or ~/.config/systemd."""
    monkeypatch.setenv("KSE_BACKEND", "fake")
    monkeypatch.setenv("KSE_DRY_RUN", "1")
    monkeypatch.setenv("KSE_HOME", str(tmp_path / "kse-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
