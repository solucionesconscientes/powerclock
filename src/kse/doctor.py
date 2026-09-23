"""`kse doctor`: the backend's report plus the checks that do not depend on the OS."""

import psutil

from kse.i18n import _
from kse.platform.base import Capability, PlatformBackend
from kse.sensors import system


async def capabilities(backend: PlatformBackend) -> list[Capability]:
    """The full report; the backend stays open (the daemon keeps using it)."""
    return [*await backend.capabilities(), *generic()]


async def collect(backend: PlatformBackend) -> list[Capability]:
    """The full report for a one-off command: closes the backend afterwards."""
    try:
        return await capabilities(backend)
    finally:
        await backend.close()


def generic() -> list[Capability]:
    state = system.battery()
    if state is None:
        power = _("no battery: always on AC")
    else:
        source = _("on AC") if state.plugged else _("on battery")
        power = _("{source} · battery {percent} %").format(
            source=source, percent=round(state.percent)
        )
    sensors = _("psutil {version}: CPU, network, processes, SSH sessions").format(
        version=psutil.__version__
    )
    return [
        Capability(id="power_source", supported=True, detail=power),
        Capability(id="sensors", supported=True, detail=sensors),
    ]
