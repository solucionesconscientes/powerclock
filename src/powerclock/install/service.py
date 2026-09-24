"""OS-neutral entry point for `powerclock service`; each OS provides its own implementation."""

from types import ModuleType

from powerclock.platform import current_os
from powerclock.platform.base import NotSupported


def service_module() -> ModuleType:
    if current_os() == "linux":
        from powerclock.platform.linux import service

        return service
    raise NotSupported(
        "service", f"installing the daemon as a service is not supported on {current_os()} yet"
    )
