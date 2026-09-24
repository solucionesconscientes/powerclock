"""OS-neutral entry point for `powerclock helper`; each OS provides its own implementation."""

from types import ModuleType

from powerclock.platform import current_os
from powerclock.platform.base import NotSupported


def helper_module() -> ModuleType:
    if current_os() == "linux":
        from powerclock.platform.linux import helper

        return helper
    raise NotSupported("helper", f"the wake-up helper is not available on {current_os()} yet")
