import os
from pathlib import Path

import pytest

# Tests read English messages: ours (gettext) and the system's (strerror). Set before any
# powerclock module is imported, and before Qt applies the desktop's language to the process.
os.environ.pop("LANGUAGE", None)
os.environ["LC_ALL"] = "C.UTF-8"


@pytest.fixture(autouse=True)
def _safe_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Safety net: no test can reach a real backend, even if it forgets to ask for the fake
    one, nor touch the real ~/.config/powerclock or ~/.config/systemd."""
    monkeypatch.setenv("POWERCLOCK_BACKEND", "fake")
    monkeypatch.setenv("POWERCLOCK_DRY_RUN", "1")
    monkeypatch.setenv("POWERCLOCK_HOME", str(tmp_path / "powerclock-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
