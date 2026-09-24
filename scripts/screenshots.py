"""Screenshots of the GUI for the README, in English and Spanish.

    uv run python scripts/screenshots.py            # both languages → docs/images/{en,es}/

The GUI runs offscreen (nothing appears on the desktop) against a daemon with the fake
backend and fake sensors: no power action, alarm or D-Bus call reaches the system.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
LANGUAGES = {"en": "C.UTF-8", "es": "es_ES.UTF-8"}

RULES: dict[str, list[dict[str, Any]]] = {
    "en": [
        {
            "id": "nightly-backup",
            "name": "Nightly backup, then shut down",
            "trigger": {"type": "cron", "expr": "0 3 * * *"},
            "wake": True,
            "conditions": {"type": "power_source", "is": "ac"},
            "guards": {
                "any": [{"type": "process_running", "name": "ffmpeg"}, {"type": "media_playing"}]
            },
            "actions": [
                {"type": "run", "cmd": ["/home/me/bin/backup.sh"], "timeout": "2h"},
                {"type": "notify", "title": "PowerClock", "body": "Backup done"},
                {"type": "power", "action": "shutdown"},
            ],
        },
        {
            "id": "workday-morning",
            "name": "Turn on on workdays and open the calendar",
            "trigger": {"type": "cron", "expr": "30 7 * * 1-5"},
            "wake": True,
            "actions": [{"type": "open", "target": "https://calendar.example.org"}],
        },
        {
            "id": "idle-suspend",
            "name": "Suspend after 20 idle minutes",
            "trigger": {"type": "idle", "for": "20m"},
            "guards": {"any": [{"type": "media_playing"}, {"type": "ssh_session"}]},
            "actions": [{"type": "power", "action": "suspend"}],
        },
        {
            "id": "download-done",
            "name": "Shut down when the download is over",
            "enabled": False,
            "trigger": {"type": "net_below", "kbps": 50, "for": "5m", "direction": "down"},
            "actions": [{"type": "power", "action": "shutdown"}],
        },
    ],
    "es": [
        {
            "id": "backup-nocturno",
            "name": "Backup nocturno y apagar",
            "trigger": {"type": "cron", "expr": "0 3 * * *"},
            "wake": True,
            "conditions": {"type": "power_source", "is": "ac"},
            "guards": {
                "any": [{"type": "process_running", "name": "ffmpeg"}, {"type": "media_playing"}]
            },
            "actions": [
                {"type": "run", "cmd": ["/home/yo/bin/backup.sh"], "timeout": "2h"},
                {"type": "notify", "title": "PowerClock", "body": "Backup terminado"},
                {"type": "power", "action": "shutdown"},
            ],
        },
        {
            "id": "buenos-dias",
            "name": "Encender los laborables y abrir la agenda",
            "trigger": {"type": "cron", "expr": "30 7 * * 1-5"},
            "wake": True,
            "actions": [{"type": "open", "target": "https://agenda.example.org"}],
        },
        {
            "id": "suspender-inactivo",
            "name": "Suspender tras 20 minutos sin usarlo",
            "trigger": {"type": "idle", "for": "20m"},
            "guards": {"any": [{"type": "media_playing"}, {"type": "ssh_session"}]},
            "actions": [{"type": "power", "action": "suspend"}],
        },
        {
            "id": "descarga-terminada",
            "name": "Apagar al terminar la descarga",
            "enabled": False,
            "trigger": {"type": "net_below", "kbps": 50, "for": "5m", "direction": "down"},
            "actions": [{"type": "power", "action": "shutdown"}],
        },
    ],
}


def capabilities() -> list[Any]:
    """What `powerclock doctor` reports on a KDE laptop (the fake backend only says "simulated")."""
    from powerclock.platform.base import Capability

    rows = [
        ("session", True, "KDE · wayland", None),
        ("power.shutdown", True, "CanPowerOff: available", None),
        ("power.suspend", True, "CanSuspend: available", None),
        (
            "power.hibernate",
            False,
            "CanHibernate: not available · swap 0.5 GiB, RAM 16 GiB",
            "needs swap at least as large as RAM and the resume= kernel parameter",
        ),
        ("power.graceful", True, "KDE (org.kde.Shutdown): applications can ask to save", None),
        ("idle", True, "Wayland ext-idle-notify-v1 · keyboard and mouse only", None),
        ("notify", True, "Plasma 6 (KDE) · with buttons", None),
        ("wake.rtc", True, "rtc_cmos 00:00 · clock in UTC", None),
        ("wake.helper", True, "installed and up to date", None),
        ("wake.authorized", True, "this process may program the alarm without a password", None),
        (
            "hardware",
            True,
            "Dell Inc. Latitude 5480",
            "Power on from off: BIOS → Power Management → Auto On Time (usually needs AC)",
        ),
        ("power_source", True, "on AC · battery 100 %", None),
    ]
    return [Capability(id=i, supported=s, detail=d, fix_hint=f) for i, s, d, f in rows]


async def pump(app: Any, seconds: float = 0.5) -> None:
    for _ in range(int(seconds / 0.02)):
        app.processEvents()
        await asyncio.sleep(0.02)


async def shoot(language: str) -> None:
    import httpx
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from PySide6.QtWidgets import QApplication

    from powerclock.config import Paths
    from powerclock.connection import Endpoint
    from powerclock.daemon.core import Daemon, QuickRequest
    from powerclock.gui.client import HttpApi
    from powerclock.gui.controller import Controller
    from powerclock.platform.fake import FakePlatform
    from powerclock.sensors.base import PowerState
    from powerclock.sensors.fake import FakeReadings

    out = OUT / language
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(["powerclock-gui"])
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale.system(), "qtbase", "_", folder):
        app.installTranslator(translator)

    class Laptop(FakePlatform):
        name = "linux"

        async def capabilities(self) -> list[Any]:
            return capabilities()

    readings = FakeReadings()
    readings.idle_seconds = 312
    readings.power_state = PowerState(percent=80.0, on_ac=False)  # the backup is skipped
    home = Path(tempfile.mkdtemp())
    daemon = Daemon(
        Laptop(timezone=ZoneInfo("Europe/Madrid")),
        paths=Paths(home / "config", home / "data"),
        dry_run=True,
        readings=readings,
    )
    await daemon.start()
    for rule in RULES[language]:
        daemon.create_rule(rule)
    # A history with every ending: skipped, done, failed and cancelled.
    daemon.run_rule(RULES[language][0]["id"])
    daemon.run_rule(RULES[language][1]["id"])
    daemon.quick(QuickRequest.model_validate({"command": ["/home/me/bin/sync-photos.sh"]}))
    daemon.quick(QuickRequest.model_validate({"action": "reboot"}))
    await asyncio.sleep(0.3)
    daemon.cancel_current()
    await asyncio.sleep(0.3)
    readings.power_state = PowerState(percent=100.0, on_ac=True)
    readings.start("ffmpeg", pid=4242)
    daemon.quick(
        QuickRequest.model_validate({"action": "shutdown", "at": "23:30", "wake_at": "07:30"})
    )
    daemon.quick(QuickRequest.model_validate({"action": "suspend", "when_idle": "30m"}))
    daemon.quick(QuickRequest.model_validate({"action": "shutdown", "when_exits": "ffmpeg"}))

    api = HttpApi(
        locate=lambda: Endpoint("http://powerclock", daemon.token),
        transport=httpx.ASGITransport(app=daemon.app),
    )

    async def stream() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "connected"}
        with daemon.hub.subscribe() as queue:
            while True:
                yield (await queue.get()).model_dump(mode="json")

    controller = Controller(app, api=api, stream=stream, tray=True)
    controller.start(show_window=True)
    await pump(app, 1.5)
    window = controller.window
    assert window is not None
    window.resize(860, 620)
    for name in ("quick", "rules", "history", "diagnostics"):
        window.show_tab(name)
        await pump(app, 0.8)
        if name == "history":
            window.history.table.selectRow(0)
            await pump(app, 0.2)
        window.grab().save(str(out / f"{name}.png"))

    window.show_tab("rules")
    await pump(app, 0.3)
    rules = window.rules
    rules.table.selectRow(
        next(i for i, r in enumerate(rules.rules) if r["id"] == RULES[language][0]["id"])
    )
    rules.edit()
    await pump(app, 0.5)
    editor = rules.editor
    assert editor is not None
    editor.resize(720, 640)
    for index, name in ((1, "editor-conditions"), (2, "editor-steps"), (4, "editor-json")):
        editor.tabs.setCurrentIndex(index)
        await pump(app, 0.3)
        editor.grab().save(str(out / f"{name}.png"))
    editor.reject()

    assert controller.tray is not None
    controller.tray.menu.adjustSize()
    controller.tray.menu.grab().save(str(out / "tray-menu.png"))
    daemon.quick(QuickRequest.model_validate({"action": "reboot", "warning": "60s"}))
    await pump(app, 1.2)
    for dialog in controller.countdowns.dialogs.values():
        dialog.grab().save(str(out / "countdown.png"))
    await controller.stop()
    await daemon.stop()
    print(f"docs/images/{language}: {len(list(out.glob('*.png')))} images")


def main() -> None:
    if len(sys.argv) > 1:  # one language, in a process whose locale is already set
        asyncio.run(shoot(sys.argv[1]))
        return
    for language, locale in LANGUAGES.items():
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "POWERCLOCK_BACKEND": "fake",
            "LC_ALL": locale,
            "LANGUAGE": language if language != "en" else "",
        }
        subprocess.run([sys.executable, __file__, language], env=env, check=True)


if __name__ == "__main__":
    main()
