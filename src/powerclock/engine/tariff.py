"""Electricity tariff periods: which one applies at a moment (for the tariff_period
condition). Only when the user chose a tariff: with a flat price all day it does not matter.

Spain 2.0TD (Peninsula, Balearic and Canary Islands, in local time): weekends and national
holidays are valley all day; on weekdays 0-8 h valley, 8-10 flat, 10-14 peak, 14-18 flat,
18-22 peak, 22-24 flat.
"""

from datetime import datetime
from typing import Literal

from powerclock.engine.holidays import is_holiday

Period = Literal["valley", "flat", "peak"]
Tariff = Literal["es-2.0td"]
TARIFFS: tuple[Tariff, ...] = ("es-2.0td",)

_ES_WEEKDAY: tuple[tuple[int, Period], ...] = (  # (from hour, period)
    (0, "valley"),
    (8, "flat"),
    (10, "peak"),
    (14, "flat"),
    (18, "peak"),
    (22, "flat"),
)


def period(tariff: Tariff, local: datetime) -> Period:
    """The period at a local (wall-clock) moment."""
    if local.weekday() >= 5 or is_holiday(local.date(), "ES"):
        return "valley"
    current: Period = "valley"
    for hour, name in _ES_WEEKDAY:
        if local.hour >= hour:
            current = name
    return current
