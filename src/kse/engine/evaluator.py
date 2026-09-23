"""Evaluates predicate trees with three-valued logic: True, False or None (unknown).

A sensor that cannot be read answers None instead of guessing; all/any/not follow Kleene
logic. Each caller decides what unknown means: conditions do not run, guards do not
block, wait_until keeps waiting.
"""

from collections.abc import Sequence
from datetime import tzinfo

from kse.engine.clock import Clock
from kse.models import AllOf, AnyOf, NotOf, Predicate, TimeWindow, Weekday
from kse.sensors.base import SensorReader

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Evaluator:
    def __init__(self, sensors: SensorReader, clock: Clock) -> None:
        self._sensors = sensors
        self._clock = clock

    async def evaluate(self, predicate: Predicate, tz: tzinfo) -> bool | None:
        match predicate:
            case AllOf(all=items):
                result: bool | None = True
                for item in items:
                    value = await self.evaluate(item, tz)
                    if value is False:
                        return False
                    if value is None:
                        result = None
                return result
            case AnyOf(any=items):
                result = False
                for item in items:
                    value = await self.evaluate(item, tz)
                    if value is True:
                        return True
                    if value is None:
                        result = None
                return result
            case NotOf(not_=inner):
                value = await self.evaluate(inner, tz)
                return None if value is None else not value
            case TimeWindow(start=start, end=end):
                now = self._clock.now().astimezone(tz).time()
                return start <= now < end if start < end else (now >= start or now < end)
            case Weekday(days=days):
                return DAY_NAMES[self._clock.now().astimezone(tz).weekday()] in days
            case _:
                return await self._sensors.check(predicate)

    async def first_true(self, predicates: Sequence[Predicate], tz: tzinfo) -> Predicate | None:
        """The first predicate that is definitely true (used for guards)."""
        for predicate in predicates:
            if await self.evaluate(predicate, tz) is True:
                return predicate
        return None


def describe(predicate: Predicate) -> str:
    """Short text for run records and logs."""
    return predicate.model_dump_json()
