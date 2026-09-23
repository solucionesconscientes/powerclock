"""Backend selection. Backends are imported lazily so that one OS never loads another's code."""

import os
import sys
from collections.abc import Callable

from kse.platform.base import NotSupported, PlatformBackend

BACKEND_ENV = "KSE_BACKEND"
DRY_RUN_ENV = "KSE_DRY_RUN"


def _fake() -> PlatformBackend:
    from kse.platform.fake import FakePlatform

    return FakePlatform()


def _linux() -> PlatformBackend:
    from kse.platform.linux import LinuxPlatform

    return LinuxPlatform()


# Windows arrives in phase 3, macOS in phase 4.
_FACTORIES: dict[str, Callable[[], PlatformBackend]] = {"fake": _fake, "linux": _linux}


def current_os() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def dry_run_requested() -> bool:
    """True when $KSE_DRY_RUN is set to 1, true, yes or on."""
    return os.environ.get(DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def get_backend(name: str | None = None, *, dry_run: bool | None = None) -> PlatformBackend:
    """Return the backend `name`, else the one in $KSE_BACKEND, else the current OS's.

    In dry-run (by default, when $KSE_DRY_RUN asks for it) the backend is wrapped so that
    power actions and wake-alarm writes are only logged.
    """
    selected = (name or os.environ.get(BACKEND_ENV) or current_os()).strip().lower()
    factory = _FACTORIES.get(selected)
    if factory is None:
        available = ", ".join(sorted(_FACTORIES))
        raise NotSupported(
            "backend",
            f"no backend named {selected!r} (available: {available})",
            fix_hint=f"Set {BACKEND_ENV}=fake to use the simulated backend.",
        )
    backend = factory()
    if dry_run_requested() if dry_run is None else dry_run:
        from kse.platform.dryrun import DryRunPlatform

        return DryRunPlatform(backend)
    return backend
