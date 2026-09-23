"""Sensor reader for tests: answers from a dict keyed by predicate type."""

from kse.sensors.base import SensorPredicate


class FakeSensors:
    def __init__(self, values: dict[str, bool | None] | None = None) -> None:
        self.values = dict(values or {})  # missing keys are unknown (None)
        self.checked: list[SensorPredicate] = []

    async def check(self, predicate: SensorPredicate) -> bool | None:
        self.checked.append(predicate)
        return self.values.get(predicate.type)
