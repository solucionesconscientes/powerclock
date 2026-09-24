"""Linux backend (logind, D-Bus, Wayland). Only imported on Linux, by get_backend()."""

from powerclock.platform.linux.backend import LinuxPlatform

__all__ = ["LinuxPlatform"]
