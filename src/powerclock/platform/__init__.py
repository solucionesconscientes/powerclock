"""Backend selection. Backends are imported lazily so that one OS never loads another's code."""

import os
import sys
from collections.abc import Callable

from powerclock.config import LEGACY_PREFIX, setting
from powerclock.platform.base import NotSupported, PlatformBackend

BACKEND_ENV = "POWERCLOCK_BACKEND"
DRY_RUN_ENV = "POWERCLOCK_DRY_RUN"


def _fake() -> PlatformBackend:
    from powerclock.platform.fake import FakePlatform

    return FakePlatform()


def _linux() -> PlatformBackend:
    from powerclock.platform.linux import LinuxPlatform

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
    """True when $POWERCLOCK_DRY_RUN (or the old $KSE_DRY_RUN) is 1, true, yes or on: if
    either asks for a dry run, it is one."""
    names = (DRY_RUN_ENV, LEGACY_PREFIX + "DRY_RUN")
    return any(os.environ.get(n, "").strip().lower() in {"1", "true", "yes", "on"} for n in names)


def get_backend(name: str | None = None, *, dry_run: bool | None = None) -> PlatformBackend:
    """Return the backend `name`, else the one in $POWERCLOCK_BACKEND, else the current OS's.

    In dry-run (by default, when $POWERCLOCK_DRY_RUN asks for it) the backend is wrapped so that
    power actions and wake-alarm writes are only logged.
    """
    selected = (name or setting(BACKEND_ENV) or current_os()).strip().lower()
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
        from powerclock.platform.dryrun import DryRunPlatform

        return DryRunPlatform(backend)
    return backend
