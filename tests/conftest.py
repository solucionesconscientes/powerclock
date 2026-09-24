import os
from pathlib import Path

import pytest

# Tests read English messages: ours (gettext) and the system's (strerror). Set before any
# kse module is imported, and before Qt applies the desktop's language to the process.
os.environ.pop("LANGUAGE", None)
os.environ["LC_ALL"] = "C.UTF-8"


@pytest.fixture(autouse=True)
def _safe_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Safety net: no test can reach a real backend, even if it forgets to ask for the fake
    one, nor touch the real ~/.config/kse or ~/.config/systemd."""
    monkeypatch.setenv("KSE_BACKEND", "fake")
    monkeypatch.setenv("KSE_DRY_RUN", "1")
    monkeypatch.setenv("KSE_HOME", str(tmp_path / "kse-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
