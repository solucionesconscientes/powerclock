"""OS-neutral entry point for `kse service`; each OS provides its own implementation."""

from types import ModuleType

from kse.platform import current_os
from kse.platform.base import NotSupported


def service_module() -> ModuleType:
    if current_os() == "linux":
        from kse.platform.linux import service

        return service
    raise NotSupported(
        "service", f"installing the daemon as a service is not supported on {current_os()} yet"
    )
