"""Backend selection. Backends are imported lazily so that one OS never loads another's code."""

import os
import sys
from collections.abc import Callable

from kse.platform.base import NotSupported, PlatformBackend

BACKEND_ENV = "KSE_BACKEND"


def _fake() -> PlatformBackend:
    from kse.platform.fake import FakePlatform

    return FakePlatform()


# The Linux backend is registered here in M3, Windows in phase 3, macOS in phase 4.
_FACTORIES: dict[str, Callable[[], PlatformBackend]] = {"fake": _fake}


def current_os() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def get_backend(name: str | None = None) -> PlatformBackend:
    """Return the backend `name`, else the one in $KSE_BACKEND, else the current OS's."""
    selected = (name or os.environ.get(BACKEND_ENV) or current_os()).strip().lower()
    factory = _FACTORIES.get(selected)
    if factory is None:
        available = ", ".join(sorted(_FACTORIES))
        raise NotSupported(
            "backend",
            f"no backend named {selected!r} (available: {available})",
            fix_hint=f"Set {BACKEND_ENV}=fake to use the simulated backend.",
        )
    return factory()
