import pytest


@pytest.fixture(autouse=True)
def _safe_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: no test can reach a real backend, even if it forgets to ask for the fake one."""
    monkeypatch.setenv("KSE_BACKEND", "fake")
    monkeypatch.setenv("KSE_DRY_RUN", "1")
