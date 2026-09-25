"""Placing windows on KDE Plasma: a small KWin script, loaded over D-Bus, waits for the new
window of an app and moves it (screen, virtual desktop, full screen…). On Wayland this is
the clean way; tools like xdotool do not work there.

The script only acts on the first matching window that appears, and PowerClock unloads it
once `wait_window` has passed.
"""

import asyncio
import contextlib
import json
import logging
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

from powerclock.platform.base import WindowPlacement
from powerclock.platform.linux.dbus import Bus, DBusError, has_owner

log = logging.getLogger(__name__)

KWIN = "org.kde.KWin"
SCRIPTING_PATH = "/Scripting"
SCRIPTING = "org.kde.kwin.Scripting"


def script(ids: list[str], pid: int | None, window: WindowPlacement) -> str:
    """The KWin (Plasma 6) script: a window matches by its process, its desktop file name
    or its class."""
    actions: list[str] = []
    if window.screen is not None:
        index = window.screen - 1
        actions.append(
            f"if (workspace.screens.length > {index}) "
            f"workspace.sendClientToScreen(w, workspace.screens[{index}]);"
        )
    if window.desktop is not None:
        index = window.desktop - 1
        actions.append(
            f"if (workspace.desktops.length > {index}) w.desktops = [workspace.desktops[{index}]];"
        )
    actions.append(
        {
            "normal": "",
            "maximized": "w.setMaximize(true, true);",
            "fullscreen": "w.fullScreen = true;",
            "minimized": "w.minimized = true;",
        }[window.state]
    )
    if window.above:
        actions.append("w.keepAbove = true;")
    body = "\n        ".join(action for action in actions if action)
    return f"""(function () {{
    var ids = {json.dumps([i.lower() for i in ids])};
    var pid = {int(pid or 0)};
    var done = false;
    function wanted(w) {{
        if (pid > 0 && w.pid === pid) return true;
        var file = String(w.desktopFileName || "").replace(/\\.desktop$/, "").toLowerCase();
        var cls = String(w.resourceClass || "").toLowerCase();
        return ids.indexOf(file) >= 0 || ids.indexOf(cls) >= 0;
    }}
    function place(w) {{
        if (done || !w.normalWindow || !wanted(w)) return;
        done = true;
        {body}
    }}
    workspace.windowAdded.connect(place);
}})();
"""


class WindowPlacer:
    def __init__(self, bus: Bus, runtime_dir: Path) -> None:
        self._bus = bus
        self._folder = runtime_dir / "powerclock"
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loaded: dict[str, Path] = {}  # script name → its file

    async def available(self) -> bool:
        try:
            return await has_owner(self._bus, KWIN)
        except DBusError:
            return False

    async def place(
        self, ids: list[str], pid: int | None, window: WindowPlacement, wait: timedelta
    ) -> None:
        """Load the script now; unload it after `wait`. Raises DBusError if KWin refuses."""
        token = secrets.token_hex(4)
        name = f"powerclock-{token}"
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._folder / f"kwin-{token}.js"
        path.write_text(script(ids, pid, window), encoding="utf-8")
        try:
            await self._bus.call(
                KWIN, SCRIPTING_PATH, SCRIPTING, "loadScript", "ss", [str(path), name]
            )
            await self._bus.call(KWIN, SCRIPTING_PATH, SCRIPTING, "start")
        except DBusError:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        self._loaded[name] = path
        task = asyncio.create_task(self._unload_later(name, wait))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _unload_later(self, name: str, wait: timedelta) -> None:
        await asyncio.sleep(wait.total_seconds())
        await self._unload(name)

    async def _unload(self, name: str) -> None:
        path = self._loaded.pop(name, None)
        if path is None:
            return
        with contextlib.suppress(DBusError, OSError):
            await self._bus.call(KWIN, SCRIPTING_PATH, SCRIPTING, "unloadScript", "s", [name])
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def close(self) -> None:
        """Stop waiting and unload every script still loaded."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for name in list(self._loaded):
            await self._unload(name)
