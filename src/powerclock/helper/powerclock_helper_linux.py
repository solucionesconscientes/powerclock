#!/usr/bin/python3
"""powerclock-helper: the only part of powerclock that runs as root.

It programs, clears or reads the RTC wake-up alarm and does nothing else. It is installed
as /usr/local/libexec/powerclock-helper and called through pkexec (polkit action
org.powerclock.helper.wake):

    powerclock-helper wake-set <epoch>   alarm at a UTC Unix time (future, at most a year ahead)
    powerclock-helper wake-clear         remove the alarm
    powerclock-helper wake-get           print the alarm as a UTC Unix time, or "none"

Standard library only; arguments are validated strictly and nothing from the caller is
ever executed or used as a path.
"""

import os
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


def main(argv=None, *, now=None, rtcwake=None, wakealarm=WAKEALARM, adjtime=ADJTIME):
    argv = sys.argv[1:] if argv is None else argv
    now = int(time.time()) if now is None else now
    if rtcwake is None:
        rtcwake = find_rtcwake()
    try:
        if len(argv) == 2 and argv[0] == "wake-set":
            wake_set(parse_epoch(argv[1], now), now, rtcwake, wakealarm)
        elif argv == ["wake-clear"]:
            wake_clear(rtcwake, wakealarm)
        elif argv == ["wake-get"]:
            value = wake_get(wakealarm, adjtime)
            print("none" if value is None else value)
        else:
            raise HelperError(
                "usage: powerclock-helper wake-set <epoch> | wake-clear | wake-get", EXIT_USAGE
            )
    except HelperError as exc:
        print(f"powerclock-helper: {exc}", file=sys.stderr)
        return exc.code
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
