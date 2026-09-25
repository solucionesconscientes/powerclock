#!/usr/bin/python3
"""powerclock-helper: the only part of powerclock that runs as root.

It programs, clears or reads the RTC wake-up alarm, and handles the one-time automatic
log-in after a scheduled power-on; nothing else. It is installed as
/usr/local/libexec/powerclock-helper and called through pkexec (polkit action
org.powerclock.helper.wake):

    powerclock-helper wake-set <epoch>   alarm at a UTC Unix time (future, at most a year ahead)
    powerclock-helper wake-clear         remove the alarm
    powerclock-helper wake-get           print the alarm as a UTC Unix time, or "none"
    powerclock-helper autologin-arm <epoch> <session|-> <locked|unlocked>
                                         log the CALLER in once if that alarm powers the
                                         computer on (a ticket in /var/lib/powerclock)
    powerclock-helper autologin-disarm   forget the ticket
    powerclock-helper autologin-done     remove this boot's log-in settings (from /run)
    powerclock-helper boot               run by powerclock-boot.service before the display
                                         manager: use the ticket if this boot is the
                                         scheduled power-on

The log-in is always for the user who called pkexec (PKEXEC_UID), never for a name given
as an argument, and never for root or system accounts. The display manager's setting is
written to /run (memory): a power cut or any later boot finds nothing there.

Standard library only; arguments are validated strictly and nothing from the caller is
ever executed or used as a path.
"""

import contextlib
import json
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

WAKEALARM = Path("/sys/class/rtc/rtc0/wakealarm")
ADJTIME = Path("/etc/adjtime")
RTCWAKE_CANDIDATES = (Path("/usr/sbin/rtcwake"), Path("/sbin/rtcwake"), Path("/usr/bin/rtcwake"))
MAX_AHEAD = 366 * 24 * 3600
MIN_AHEAD = 5
EPOCH = re.compile(r"[0-9]{1,12}")
CLEAN_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

# One-time automatic log-in (docs/ARCHITECTURE.md §6, "Entrar al encender").
EARLY = 60  # seconds before the alarm a boot still counts as the scheduled one (clock skew)
WINDOW = 600  # seconds after the alarm
MIN_UID = 1000  # regular users only
SESSION = re.compile(r"[A-Za-z0-9._-]{1,64}")
MODES = ("locked", "unlocked")
POWER_SWITCH = 0x06  # SMBIOS "Wake-up Type": the power button


class Places:
    """Where the log-in pieces live (tests point them elsewhere)."""

    def __init__(self, root=Path("/")):
        self.state = root / "var/lib/powerclock"
        self.runtime = root / "run/powerclock"
        self.dmi = root / "sys/firmware/dmi/tables/DMI"
        self.display_manager = root / "etc/systemd/system/display-manager.service"
        self.session_dirs = (root / "usr/share/wayland-sessions", root / "usr/share/xsessions")
        self.sddm_configs = (root / "usr/lib/sddm/sddm.conf.d", root / "etc/sddm.conf.d")
        self.sddm_main = root / "etc/sddm.conf"

    @property
    def ticket(self):
        return self.state / "autologin.json"

    @property
    def used(self):
        return self.runtime / "used"


class HelperError(Exception):
    def __init__(self, message, code=EXIT_FAILED):
        super().__init__(message)
        self.code = code


def parse_epoch(text, now):
    if not EPOCH.fullmatch(text):
        raise HelperError(f"not a Unix time: {text!r}", EXIT_USAGE)
    epoch = int(text)
    if epoch < now + MIN_AHEAD:
        raise HelperError("the wake-up time must be in the future", EXIT_USAGE)
    if epoch > now + MAX_AHEAD:
        raise HelperError("the wake-up time is more than a year ahead", EXIT_USAGE)
    return epoch


def find_rtcwake(candidates=RTCWAKE_CANDIDATES):
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def run_rtcwake(rtcwake, arguments):
    """rtcwake knows whether the RTC keeps UTC or local time (/etc/adjtime)."""
    if rtcwake is None:
        return False
    try:
        result = subprocess.run(
            [str(rtcwake), *arguments],
            env=CLEAN_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def wake_set(epoch, now, rtcwake, wakealarm):
    if run_rtcwake(rtcwake, ["-m", "no", "-t", str(epoch)]):
        return
    # Fallback: sysfs. Relative "+seconds" does not depend on the RTC keeping UTC or
    # local time, unlike an absolute value.
    try:
        wakealarm.write_text("0")
        wakealarm.write_text(f"+{epoch - now}")
    except OSError as exc:
        raise HelperError(f"cannot program the RTC alarm: {exc}") from None


def wake_clear(rtcwake, wakealarm):
    if run_rtcwake(rtcwake, ["-m", "disable"]):
        return
    try:
        wakealarm.write_text("0")
    except OSError as exc:
        raise HelperError(f"cannot clear the RTC alarm: {exc}") from None


def rtc_keeps_local_time(adjtime):
    try:
        lines = adjtime.read_text().splitlines()
    except OSError:
        return False
    return len(lines) >= 3 and lines[2].strip() == "LOCAL"


def wake_get(wakealarm, adjtime):
    """The alarm as a UTC Unix time, or None."""
    try:
        raw = wakealarm.read_text().strip()
    except OSError as exc:
        raise HelperError(f"cannot read the RTC alarm: {exc}") from None
    if not raw:
        return None
    value = int(raw)
    if rtc_keeps_local_time(adjtime):  # the value is local wall-clock time counted as UTC
        wall = time.gmtime(value)
        value = int(time.mktime((*wall[:8], -1)))
    return value


# ── One-time automatic log-in ────────────────────────────────────────────────


def caller(env, user_name=None):
    """The regular user who called pkexec (or sudo): (uid, name)."""
    raw = env.get("PKEXEC_UID") or env.get("SUDO_UID") or ""
    if not raw.isdigit() or int(raw) < MIN_UID:
        raise HelperError("only a regular user can ask to be logged in", EXIT_USAGE)
    uid = int(raw)
    try:
        name = user_name(uid) if user_name else pwd.getpwuid(uid).pw_name
    except KeyError:
        raise HelperError(f"no user with uid {uid}", EXIT_USAGE) from None
    return uid, name


def check_session(session, places):
    if session == "-":
        return session
    if not SESSION.fullmatch(session):
        raise HelperError(f"not a session name: {session!r}", EXIT_USAGE)
    if not any((folder / f"{session}.desktop").is_file() for folder in places.session_dirs):
        raise HelperError(f"no desktop session called {session!r}", EXIT_USAGE)
    return session


def arm(epoch, session, mode, uid, name, places):
    if mode not in MODES:
        raise HelperError(f"the screen must be {' or '.join(MODES)}, not {mode!r}", EXIT_USAGE)
    ticket = {"alarm": epoch, "uid": uid, "user": name, "session": session, "mode": mode}
    places.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = places.ticket.with_suffix(".tmp")
    temporary.write_text(json.dumps(ticket) + "\n")
    temporary.chmod(0o600)
    temporary.replace(places.ticket)


def disarm(places):
    with contextlib.suppress(FileNotFoundError):
        places.ticket.unlink()


def clear_runtime(places):
    for name in ("sddm.conf", "lightdm.conf", "used"):
        with contextlib.suppress(FileNotFoundError):
            (places.runtime / name).unlink()


def read_ticket(places):
    try:
        ticket = json.loads(places.ticket.read_text())
    except (OSError, ValueError):
        return None
    ok = (
        isinstance(ticket, dict)
        and isinstance(ticket.get("alarm"), int)
        and isinstance(ticket.get("uid"), int)
        and ticket["uid"] >= MIN_UID
        and isinstance(ticket.get("user"), str)
        and re.fullmatch(r"[a-z_][a-z0-9_.-]*", ticket["user"])
        and ticket.get("mode") in MODES
        and isinstance(ticket.get("session"), str)
        and (ticket["session"] == "-" or SESSION.fullmatch(ticket["session"]))
    )
    return ticket if ok else None


def wake_type(dmi):
    """The SMBIOS System Information "Wake-up Type" byte, or None if unknown."""
    try:
        table = dmi.read_bytes()
    except OSError:
        return None
    index = 0
    while index + 4 <= len(table):
        kind, length = table[index], table[index + 1]
        if length < 4 or kind == 127:
            return None
        if kind == 1:
            return table[index + 0x18] if length > 0x18 else None
        end = index + length
        while end + 1 < len(table) and (table[end] or table[end + 1]):
            end += 1
        index = end + 2
    return None


def display_manager(places):
    try:
        target = places.display_manager.readlink()
    except OSError:
        return None
    name = target.name.removesuffix(".service")
    return "gdm" if name == "gdm3" else name


def sddm_session(places):
    """The session SDDM logs into automatically (its [Autologin] Session), if set."""
    files = []
    for folder in places.sddm_configs:
        if folder.is_dir():
            files += sorted(p for p in folder.glob("*.conf") if p.name != "zz-powerclock.conf")
    files.append(places.sddm_main)
    session, group = None, None
    for path in files:
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line.startswith("["):
                group = line.strip("[]")
            elif group == "Autologin" and line.startswith("Session="):
                session = line.partition("=")[2].strip() or session
    return session


def boot(now, places):
    """At boot, before the display manager: log the ticket's user in if this is the
    scheduled power-on. Returns what happened (for the journal)."""
    clear_runtime(places)
    ticket = read_ticket(places)
    if not places.ticket.exists():
        return "no log-in requested"
    disarm(places)  # one use only, whatever happens next
    if ticket is None:
        return "the log-in ticket was not valid: ignored"
    alarm = ticket["alarm"]
    if not alarm - EARLY <= now <= alarm + WINDOW:
        return f"not the scheduled power-on (alarm {alarm}, now {now}): no automatic log-in"
    if wake_type(places.dmi) == POWER_SWITCH:
        return "switched on with the power button: no automatic log-in"
    manager = display_manager(places)
    session = None if ticket["session"] == "-" else ticket["session"]
    user = ticket["user"]
    places.runtime.mkdir(mode=0o755, parents=True, exist_ok=True)
    if manager == "sddm":
        session = session or sddm_session(places)
        text = f"[Autologin]\nUser={user}\nRelogin=false\n"
        if session:
            text += f"Session={session}\n"
        name = "sddm.conf"
    elif manager == "lightdm":
        text = f"[Seat:*]\nautologin-user={user}\nautologin-user-timeout=0\n"
        if session:
            text += f"autologin-session={session}\n"
        name = "lightdm.conf"
    else:
        return f"display manager {manager or 'unknown'} is not supported: no automatic log-in"
    header = "# Written by powerclock-helper for this boot only (a scheduled power-on).\n"
    config = places.runtime / name
    config.write_text(header + text)
    config.chmod(0o644)
    places.used.write_text(json.dumps({"uid": ticket["uid"], "mode": ticket["mode"]}) + "\n")
    places.used.chmod(0o644)
    return f"automatic log-in for {user} through {manager}"


def main(
    argv=None,
    *,
    now=None,
    rtcwake=None,
    wakealarm=WAKEALARM,
    adjtime=ADJTIME,
    places=None,
    env=None,
    user_name=None,
):
    argv = sys.argv[1:] if argv is None else argv
    now = int(time.time()) if now is None else now
    places = places or Places()
    env = os.environ if env is None else env
    if rtcwake is None and argv[:1] in (["wake-set"], ["wake-clear"]):
        rtcwake = find_rtcwake()
    try:
        if len(argv) == 2 and argv[0] == "wake-set":
            wake_set(parse_epoch(argv[1], now), now, rtcwake, wakealarm)
        elif argv == ["wake-clear"]:
            wake_clear(rtcwake, wakealarm)
        elif argv == ["wake-get"]:
            value = wake_get(wakealarm, adjtime)
            print("none" if value is None else value)
        elif len(argv) == 4 and argv[0] == "autologin-arm":
            epoch = parse_epoch(argv[1], now)
            session = check_session(argv[2], places)
            uid, name = caller(env, user_name)
            arm(epoch, session, argv[3], uid, name, places)
        elif argv == ["autologin-disarm"]:
            disarm(places)
        elif argv == ["autologin-done"]:
            clear_runtime(places)
        elif argv == ["boot"]:
            print(f"powerclock-helper: {boot(now, places)}")
        else:
            raise HelperError(
                "usage: powerclock-helper wake-set <epoch> | wake-clear | wake-get | "
                "autologin-arm <epoch> <session|-> <locked|unlocked> | autologin-disarm | "
                "autologin-done | boot",
                EXIT_USAGE,
            )
    except HelperError as exc:
        print(f"powerclock-helper: {exc}", file=sys.stderr)
        return exc.code
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
