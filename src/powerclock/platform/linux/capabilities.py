"""The Linux part of `powerclock doctor`: what works on this machine and how to fix what does
not."""

import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from powerclock.i18n import _
from powerclock.platform.base import Capability, NotSupported, PowerAction
from powerclock.platform.linux.dbus import DBusError
from powerclock.platform.linux.helper import ACTION, packaged
from powerclock.platform.linux.idle import LOGIND, WAYLAND
from powerclock.platform.linux.logind import ALLOWED, METHODS
from powerclock.platform.linux.network import wifi_ssid

if TYPE_CHECKING:
    from powerclock.platform.linux.backend import LinuxPlatform

log = logging.getLogger(__name__)

Check = Callable[["LinuxPlatform"], Awaitable[list[Capability]]]


def row(id_: str, supported: bool, detail: str, fix_hint: str | None = None) -> Capability:
    return Capability(id=id_, supported=supported, detail=detail, fix_hint=fix_hint)


async def collect(platform: "LinuxPlatform") -> list[Capability]:
    rows: list[Capability] = []
    for check in CHECKS:
        try:
            rows += await check(platform)
        except Exception as exc:  # a broken check must never break the whole report
            log.exception("doctor check %s failed", check.__name__)
            rows.append(
                row(check.__name__.removeprefix("_"), False, f"{type(exc).__name__}: {exc}")
            )
    return rows


async def _session(p: "LinuxPlatform") -> list[Capability]:
    try:
        kind = await p.logind.session_property("Type")
        desktop = await p.logind.session_property("Desktop")
    except (DBusError, NotSupported):
        return [row("session", False, _("no graphical session: desktop features are unavailable"))]
    desktop = desktop or p.env.get("XDG_CURRENT_DESKTOP") or "?"
    return [row("session", True, f"{desktop} · {kind}")]


async def _power(p: "LinuxPlatform") -> list[Capability]:
    answers = {
        "yes": _("available"),
        "challenge": _("available after authenticating (polkit)"),
        "no": _("not allowed for this user"),
        "na": _("not available on this system"),
    }
    rows = []
    for action, (query, _method) in METHODS.items():
        try:
            answer = await p.logind.can(action)
        except DBusError as exc:
            rows.append(
                row(f"power.{action}", False, _("logind not reachable: {error}").format(error=exc))
            )
            continue
        detail = answers.get(answer, answer)
        fix = None
        if action in (PowerAction.HIBERNATE, PowerAction.HYBRID_SLEEP):
            memory, swap = p.host.memory_kib() or 0, p.host.swap_kib()
            detail += " · " + _("swap {swap:.1f} GiB, RAM {ram:.1f} GiB, resume= {resume}").format(
                swap=swap / 1024**2,
                ram=memory / 1024**2,
                resume=_("set") if p.host.resume_configured() else _("not set"),
            )
            if answer not in ALLOWED:
                fix = _("needs swap at least as large as RAM and the resume= kernel parameter")
        rows.append(row(f"power.{action}", answer in ALLOWED, f"{query}: {detail}", fix))
    return rows


async def _graceful(p: "LinuxPlatform") -> list[Capability]:
    method = await p.desktop.graceful_method()
    if method is None:
        detail = _("no session manager: shutdown and reboot go straight to logind")
        return [row("power.graceful", False, detail)]
    return [
        row(
            "power.graceful",
            True,
            _("{method}: applications can ask to save").format(method=method),
        )
    ]


async def _session_actions(p: "LinuxPlatform") -> list[Capability]:
    try:
        session_id, _path = await p.logind.display()
    except (DBusError, NotSupported):
        detail = _("no graphical session")
        return [row("power.lock", False, detail), row("power.logout", False, detail)]
    detail = _("logind session {id}").format(id=session_id)
    return [row("power.lock", True, detail), row("power.logout", True, detail)]


async def _screen_off(p: "LinuxPlatform") -> list[Capability]:
    method = await p.desktop.screen_off_method()
    if method is None:
        return [row("power.screen_off", False, _("no method found"), _("KDE: install kscreen"))]
    return [row("power.screen_off", True, method)]


async def _idle(p: "LinuxPlatform") -> list[Capability]:
    seconds = await p.idle.idle_seconds()
    strategy = p.idle.strategy
    if strategy is None or seconds is None:
        return [row("idle", False, _("no way to measure inactivity"), _("X11: install xprintidle"))]
    if strategy == WAYLAND:  # the first reading is always 0: it measures from now on
        scope = _("keyboard and mouse only") if p.idle.input_only else _("respects inhibitors")
        return [row("idle", True, f"{strategy} · {scope}")]
    detail = _("{strategy} · idle for {seconds} s").format(
        strategy=strategy, seconds=round(seconds)
    )
    if strategy == LOGIND:
        detail += " · " + _("only as reliable as the desktop that sets it")
    return [row("idle", True, detail)]


async def _media(p: "LinuxPlatform") -> list[Capability]:
    try:
        players = await p.desktop.players()
    except DBusError:
        return [row("media", False, _("no session bus"))]
    playing = sum(status == "Playing" for status in players.values())
    detail = _("MPRIS: {count} player(s), {playing} playing").format(
        count=len(players), playing=playing
    )
    return [row("media", True, detail)]


async def _notify(p: "LinuxPlatform") -> list[Capability]:
    try:
        server, capabilities = await p.notifier.server()
    except DBusError:
        return [row("notify", False, _("no notification server"))]
    if "actions" in capabilities:
        return [row("notify", True, _("{server} · with buttons").format(server=server))]
    detail = _("{server} · no buttons: cancel the countdown from the CLI or the GUI")
    return [row("notify", True, detail.format(server=server))]


async def _wifi(p: "LinuxPlatform") -> list[Capability]:
    try:
        ssid = await wifi_ssid(p.system_bus)
    except (NotSupported, DBusError) as exc:
        return [row("wifi", False, str(exc))]
    if ssid is None:
        return [row("wifi", True, _("NetworkManager · not on Wi-Fi"))]
    return [row("wifi", True, _("NetworkManager · Wi-Fi {ssid}").format(ssid=ssid))]


async def _applications(p: "LinuxPlatform") -> list[Capability]:
    found = await p.apps()
    flatpak = sum(app.flatpak is not None for app in found)
    rows = [
        row(
            "apps",
            bool(found),
            _("{count} applications ({flatpak} Flatpak)").format(count=len(found), flatpak=flatpak),
        )
    ]
    try:
        graphical = await p.session.graphical()
    except DBusError:
        rows.append(
            row(
                "launch",
                True,
                _("without systemd's user manager: apps start directly and cannot be kept open"),
            )
        )
    else:
        state = _("desktop session up") if graphical else _("no desktop session now")
        rows.append(row("launch", True, _("systemd user manager · {state}").format(state=state)))
    if await p.windows.available():
        rows.append(row("windows", True, "KWin"))
    else:
        rows.append(row("windows", False, _("only on KDE Plasma (KWin)")))
    return rows


async def _power_events(p: "LinuxPlatform") -> list[Capability]:
    try:
        delay = await p.logind.inhibit_delay_max()
    except DBusError as exc:
        detail = _("logind not reachable: {error}").format(error=exc)
        return [row("power_events", False, detail), row("inhibit", False, detail)]
    return [
        row("power_events", True, "logind PrepareForSleep / PrepareForShutdown"),
        row("inhibit", True, _("delay inhibitors up to {seconds} s").format(seconds=round(delay))),
    ]


async def _wake(p: "LinuxPlatform") -> list[Capability]:
    rtc = p.host.rtc()
    if not (rtc.present and rtc.wakealarm):
        rtc_row = row("wake.rtc", False, _("no RTC with a wake alarm"))
    else:
        clock = _("local time") if rtc.local_time else "UTC"
        rtc_row = row(
            "wake.rtc", True, _("{name} · clock in {clock}").format(name=rtc.name, clock=clock)
        )
    rows = [rtc_row, *await _helper_rows(p)]
    alarm = await p.wake_get()
    detail = _("programmed for {time}").format(time=_local(alarm)) if alarm else _("none")
    rows.append(row("wake.alarm", True, detail))
    return rows


async def _helper_rows(p: "LinuxPlatform") -> list[Capability]:
    if not p.host.helper_installed():
        return [row("wake.helper", False, _("not installed"), _("powerclock helper install"))]
    if not p.host.helper_matches(packaged("powerclock_helper_linux.py")):
        return [
            row(
                "wake.helper",
                False,
                _("installed, but from another version of powerclock"),
                _("powerclock helper install"),
            )
        ]
    rows = [row("wake.helper", True, _("installed and up to date"))]
    code, _output = await p.commands.run(
        ["pkcheck", "--action-id", ACTION, "--process", str(os.getpid())]
    )
    answers = {
        0: (True, _("this process may program the alarm without a password")),
        1: (False, _("this process is not allowed to program the alarm")),
        2: (False, _("a password would be needed (no active session?)")),
    }
    supported, detail = answers.get(code, (False, _("pkcheck failed ({code})").format(code=code)))
    fix = (
        None
        if supported
        else _("without a graphical session: powerclock helper install --unattended")
    )
    rows.append(row("wake.authorized", supported, detail, fix))
    unattended = p.host.unattended_installed()
    if unattended is None:
        rows.append(row("wake.unattended", True, _("cannot be checked by a normal user")))
    elif unattended:
        rows.append(
            row("wake.unattended", True, _("rule installed: works with the session closed"))
        )
    else:
        rows.append(
            row(
                "wake.unattended",
                False,
                _("only while you are logged in"),
                _(
                    "powerclock helper install --unattended "
                    "(and powerclock service install --linger)"
                ),
            )
        )
    return rows


def _local(moment: datetime) -> str:
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


async def _hardware(p: "LinuxPlatform") -> list[Capability]:
    vendor, product = p.host.hardware()
    detail = " ".join(part for part in (vendor, product) if part) or _("unknown")
    if vendor and vendor.lower().startswith("dell"):
        hint = _("Power on from off: BIOS → Power Management → Auto On Time (usually needs AC)")
    else:
        hint = _("Waking from off (S5) depends on the BIOS/UEFI; from suspend it usually works")
    return [row("hardware", True, detail, hint)]


async def _linger(p: "LinuxPlatform") -> list[Capability]:
    if p.host.linger(p.user):
        return [row("linger", True, _("enabled: PowerClock works with the session closed"))]
    return [row("linger", False, _("disabled"), _("powerclock service install --linger"))]


async def _timezone(p: "LinuxPlatform") -> list[Capability]:
    return [row("timezone", True, str(p.timezone()))]


CHECKS: list[Check] = [
    _session,
    _power,
    _graceful,
    _session_actions,
    _screen_off,
    _idle,
    _media,
    _notify,
    _wifi,
    _applications,
    _power_events,
    _wake,
    _hardware,
    _linger,
    _timezone,
]
