"""Sunrise and sunset, computed here (NOAA's formulas; about a minute of accuracy), with no
internet. Without coordinates, the time zone's own city gives them: the tz database lists
one for each zone (Europe/Madrid: 40.4 N, 3.7 W)."""

import math
import zoneinfo
from datetime import UTC, date, datetime, timedelta, tzinfo
from functools import cache
from pathlib import Path
from typing import Literal

SunEvent = Literal["sunrise", "sunset"]
ZENITH = 90.833  # the sun's upper edge on the horizon, with refraction


def sun_time(day: date, latitude: float, longitude: float, event: SunEvent) -> datetime | None:
    """When the sun rises or sets on `day` (UTC), or None (polar day or night)."""
    n = day.timetuple().tm_yday
    hour = 6 if event == "sunrise" else 18
    gamma = 2 * math.pi / 365 * (n - 1 + (hour - 12) / 24)
    equation = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    phi = math.radians(latitude)
    cos_angle = math.cos(math.radians(ZENITH)) / (math.cos(phi) * math.cos(declination)) - (
        math.tan(phi) * math.tan(declination)
    )
    if not -1 <= cos_angle <= 1:
        return None
    angle = math.degrees(math.acos(cos_angle))
    if event == "sunrise":
        angle = -angle
    minutes = 720 - 4 * (longitude - angle) - equation
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(minutes=minutes)


def next_sun(
    after: datetime,
    event: SunEvent,
    offset: timedelta,
    tz: tzinfo,
    latitude: float | None = None,
    longitude: float | None = None,
) -> datetime | None:
    """The first sunrise/sunset (plus `offset`) after `after`, None if there is no place."""
    if latitude is None or longitude is None:
        place = zone_location(getattr(tz, "key", None))
        if place is None:
            return None
        latitude, longitude = place
    first = after.astimezone(tz).date() - timedelta(days=1)
    for days in range(370):
        moment = sun_time(first + timedelta(days=days), latitude, longitude, event)
        if moment is None:
            continue
        due = (moment + offset).replace(microsecond=0)  # rounded before comparing: once
        if due > after:
            return due
    return None


@cache
def zone_location(zone: str | None) -> tuple[float, float] | None:
    """The coordinates the tz database gives a zone ("Europe/Madrid"), if any."""
    if not zone:
        return None
    for folder in zoneinfo.TZPATH:
        for name in ("zone1970.tab", "zone.tab"):
            try:
                lines = (Path(folder) / name).read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                fields = line.split("\t")
                if len(fields) >= 3 and fields[2] == zone and not line.startswith("#"):
                    return _coordinates(fields[1])
    return None


def _coordinates(text: str) -> tuple[float, float]:
    """ISO 6709 as the tz database writes it: +DDMM-DDDMM or +DDMMSS-DDDMMSS."""
    split = max(text.rfind("+"), text.rfind("-"))
    return _degrees(text[:split]), _degrees(text[split:])


def _degrees(part: str) -> float:
    sign = -1 if part[0] == "-" else 1
    digits = part[1:]
    head = 2 if len(digits) in (4, 6) else 3
    whole = int(digits[:head])
    minutes = int(digits[head : head + 2])
    seconds = int(digits[head + 2 : head + 4] or 0)
    return sign * (whole + minutes / 60 + seconds / 3600)
