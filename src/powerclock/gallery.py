"""Ready-made rules by use case (the gallery): pick one, adjust it in the editor, save.

Words in angle brackets (<url>, <file>) are for the user to replace; the editor shows the
recipe's hint for each. Every template is a valid rule (a test checks them all).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from powerclock.i18n import _

Rule = dict[str, Any]


@dataclass(frozen=True)
class Template:
    id: str
    group: str
    title: str
    description: str
    rule: Rule
    needs: str | None = None  # a setting it only makes sense with ("tariff")


def groups() -> list[tuple[str, str]]:
    return [
        ("energy", _("Save energy")),
        ("mornings", _("Mornings")),
        ("screens", _("Kiosks and presentations")),
        ("health", _("Breaks and focus")),
        ("calendar", _("Meetings and the day's light")),
        ("home", _("Backups and other computers")),
    ]


def templates(now: Callable[[], datetime] = datetime.now) -> list[Template]:
    tomorrow_nine = (now().astimezone() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    shutdown = {"type": "power", "action": "shutdown"}
    return [
        # ── Save energy ──
        Template(
            "download-done",
            "energy",
            _("Shut down when the download finishes"),
            _("When the network stays quiet for 5 minutes, with 2 minutes to cancel."),
            {
                "name": _("Shut down when the download finishes"),
                "trigger": {"type": "net_below", "kbps": 50, "for": "5m", "direction": "down"},
                "guards": {"any": [{"type": "ssh_session"}]},
                "actions": [shutdown],
                "warning": "2m",
                "one_shot": True,
            },
        ),
        Template(
            "program-ends",
            "energy",
            _("Shut down when a program ends"),
            _("A render, a copy or a long export: when it ends, the computer turns off."),
            {
                "name": _("Shut down when ffmpeg ends"),
                "trigger": {"type": "process_exit", "name": "ffmpeg"},
                "actions": [shutdown],
                "warning": "2m",
                "one_shot": True,
            },
        ),
        Template(
            "idle-suspend",
            "energy",
            _("Suspend after 20 minutes without use"),
            _("Not while something plays, someone is connected by SSH or the CPU is busy."),
            {
                "name": _("Suspend after 20 minutes without use"),
                "trigger": {"type": "idle", "for": "20m"},
                "guards": {
                    "any": [
                        {"type": "media_playing"},
                        {"type": "ssh_session"},
                        {"not": {"type": "cpu_below", "percent": 20, "for": "2m"}},
                    ]
                },
                "actions": [{"type": "power", "action": "suspend"}],
                "warning": "60s",
            },
        ),
        Template(
            "night-shutdown",
            "energy",
            _("Shut down every night"),
            _("At 23:30, with 5 minutes to cancel or postpone."),
            {
                "name": _("Shut down every night"),
                "trigger": {"type": "cron", "expr": "30 23 * * *"},
                "actions": [shutdown],
                "warning": "5m",
            },
        ),
        Template(
            "cheap-hours",
            "energy",
            _("Heavy tasks in the cheap hours"),
            _("Only with a time-of-use tariff: runs your task when electricity is cheapest."),
            {
                "name": _("Heavy tasks in the cheap hours"),
                "trigger": {"type": "cron", "expr": "0 1 * * *"},
                "conditions": {"type": "tariff_period", "period": "valley"},
                "actions": [{"type": "run", "cmd": ["~/bin/task.sh"], "timeout": "3h"}],
            },
            needs="tariff",
        ),
        # ── Mornings ──
        Template(
            "good-morning",
            "mornings",
            _("Turn on on workdays and open the calendar"),
            _("The computer turns itself on at 07:30 and opens your calendar."),
            {
                "name": _("Turn on on workdays and open the calendar"),
                "trigger": {"type": "cron", "expr": "30 7 * * 1-5"},
                "wake": True,
                "actions": [{"type": "open", "target": "https://calendar.google.com"}],
            },
        ),
        Template(
            "radio-alarm",
            "mornings",
            _("Radio alarm"),
            _("Turns on, logs in with the screen locked and plays a radio, getting louder."),
            {
                "name": _("Radio alarm"),
                "trigger": {"type": "cron", "expr": "0 7 * * 1-5"},
                "wake": True,
                "log_in": "locked",
                "actions": [
                    {"type": "volume", "level": 10},
                    {"type": "launch", "app": "vlc", "recipe": "vlc.stream", "args": ["<url>"]},
                    {"type": "volume", "level": 60, "fade": "5m"},
                ],
            },
        ),
        # ── Kiosks and presentations ──
        Template(
            "kiosk",
            "screens",
            _("Kiosk: a web page full screen"),
            _("When the session starts, a web page full screen, opened again if it closes."),
            {
                "name": _("Kiosk: a web page full screen"),
                "trigger": {"type": "desktop_session"},
                "actions": [
                    {
                        "type": "launch",
                        "app": "google-chrome",
                        "recipe": "chromium.kiosk",
                        "args": [
                            "--kiosk",
                            "--noerrdialogs",
                            "--hide-crash-restore-bubble",
                            "--autoplay-policy=no-user-gesture-required",
                            "--password-store=basic",
                            "--user-data-dir={data}/profiles/kiosk",
                            "<url>",
                        ],
                        "keep_open": True,
                    },
                    {"type": "inhibit", "screen_on": True, "duration": "12h"},
                ],
            },
        ),
        Template(
            "photo-frame",
            "screens",
            _("Photo frame"),
            _("When the session starts, a slideshow of a folder, full screen."),
            {
                "name": _("Photo frame"),
                "trigger": {"type": "desktop_session"},
                "actions": [
                    {
                        "type": "launch",
                        "app": "org.kde.gwenview",
                        "recipe": "gwenview.slideshow",
                        "args": ["--fullscreen", "--slideshow", "<folder>"],
                    }
                ],
            },
        ),
        Template(
            "presentation",
            "screens",
            _("Presentation at a time"),
            _("Opens a PDF as a presentation and silences notifications for an hour."),
            {
                "name": _("Presentation at a time"),
                "trigger": {"type": "at", "when": tomorrow_nine.isoformat()},
                "wake": True,
                "actions": [
                    {"type": "inhibit", "do_not_disturb": True, "duration": "1h"},
                    {
                        "type": "launch",
                        "app": "org.kde.okular",
                        "recipe": "okular.presentation",
                        "args": ["--presentation", "<file>"],
                    },
                ],
                "one_shot": True,
            },
        ),
        # ── Breaks and focus ──
        Template(
            "break",
            "health",
            _("Take a break every 50 minutes"),
            _("After 50 minutes in use without a 5-minute pause, a reminder."),
            {
                "name": _("Take a break"),
                "trigger": {"type": "active", "for": "50m", "pause": "5m"},
                "actions": [
                    {
                        "type": "notify",
                        "title": _("Time for a break"),
                        "body": _("Stand up, look far away, drink some water."),
                    }
                ],
            },
        ),
        Template(
            "enough",
            "health",
            _("Enough for today"),
            _("After 8 hours of use today, it asks whether to shut down."),
            {
                "name": _("Enough for today"),
                "trigger": {"type": "used_today", "for": "8h"},
                "actions": [
                    {
                        "type": "ask",
                        "title": _("8 hours today. Shut down the computer?"),
                        "buttons": [_("Shut down"), _("Not yet")],
                        "go_on": _("Shut down"),
                    },
                    shutdown,
                ],
            },
        ),
        # ── Meetings and the day's light ──
        Template(
            "meeting",
            "calendar",
            _("Before each meeting"),
            _("5 minutes before each event of your calendar (.ics address), a reminder."),
            {
                "name": _("Before each meeting"),
                "trigger": {"type": "calendar", "source": "<.ics>", "before": "5m"},
                "actions": [
                    {"type": "notify", "title": _("Meeting in 5 minutes"), "body": "{rule}"},
                ],
            },
        ),
        Template(
            "sunset",
            "calendar",
            _("Dark theme at sunset"),
            _("At sunset the desktop turns dark (at sunrise, add the opposite rule)."),
            {
                "name": _("Dark theme at sunset"),
                "trigger": {"type": "sun", "event": "sunset"},
                "actions": [{"type": "desktop", "theme": "dark"}],
            },
        ),
        # ── Backups and other computers ──
        Template(
            "backup",
            "home",
            _("Nightly backup, then shut down"),
            _("Turns on at 03:00, only on AC power; waits while something plays."),
            {
                "name": _("Nightly backup, then shut down"),
                "trigger": {"type": "cron", "expr": "0 3 * * *"},
                "wake": True,
                "conditions": {"type": "power_source", "is": "ac"},
                "guards": {"any": [{"type": "media_playing"}, {"type": "ssh_session"}]},
                "actions": [
                    {"type": "run", "cmd": ["~/bin/backup.sh"], "timeout": "2h"},
                    shutdown,
                ],
                "on_failure": [
                    {"type": "notify", "title": _("The backup failed"), "body": "{error}"}
                ],
            },
        ),
        Template(
            "wake-nas",
            "home",
            _("Turn on the NAS before the backup"),
            _("Wake-on-LAN at 02:55: write its MAC address."),
            {
                "name": _("Turn on the NAS before the backup"),
                "trigger": {"type": "cron", "expr": "55 2 * * *"},
                "actions": [{"type": "wake_lan", "mac": "00:00:00:00:00:00"}],
            },
        ),
        Template(
            "phone-on",
            "home",
            _("Tell my phone when the computer turns on"),
            _("A message with ntfy (free, no account): write your topic."),
            {
                "name": _("Tell my phone when the computer turns on"),
                "trigger": {"type": "startup", "on": ["daemon_start"], "delay": "1m"},
                "actions": [
                    {
                        "type": "push",
                        "service": "ntfy",
                        "url": "https://ntfy.sh/<topic>",
                        "message": _("The computer is on"),
                    }
                ],
            },
        ),
    ]
