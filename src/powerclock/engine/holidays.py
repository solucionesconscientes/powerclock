"""Public holidays, computed here: Spain's national ones (the same everywhere in Spain)
plus any the user adds. Regional and local holidays change every year: add them as dates."""

from datetime import date, timedelta
from functools import cache


def easter(year: int) -> date:
    """Easter Sunday (the Western church's computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lr = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lr) // 451
    month = (h + lr - 7 * m + 114) // 31
    day = (h + lr - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@cache
def spain(year: int) -> frozenset[date]:
    fixed = [(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)]
    days = {date(year, month, day) for month, day in fixed}
    days.add(easter(year) - timedelta(days=2))  # Good Friday
    return frozenset(days)


COUNTRIES = {"ES": spain}


def is_holiday(day: date, country: str = "ES", extra: tuple[date, ...] = ()) -> bool:
    return day in extra or day in COUNTRIES[country](day.year)
