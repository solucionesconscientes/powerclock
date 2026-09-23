"""OS-neutral entry point for `kse helper`; each OS provides its own implementation."""

from types import ModuleType

from kse.platform import current_os
from kse.platform.base import NotSupported


def helper_module() -> ModuleType:
    if current_os() == "linux":
        from kse.platform.linux import helper

        return helper
    raise NotSupported("helper", f"the wake-up helper is not available on {current_os()} yet")
