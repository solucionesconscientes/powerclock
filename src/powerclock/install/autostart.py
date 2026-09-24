"""OS-neutral entry point for the GUI's menu entry and login start; one module per OS."""

from types import ModuleType

from powerclock.platform import current_os
from powerclock.platform.base import NotSupported


def desktop_module() -> ModuleType:
    if current_os() == "linux":
        from powerclock.platform.linux import autostart

        return autostart
    raise NotSupported(
        "autostart", f"the menu entry and login start are not available on {current_os()} yet"
    )
