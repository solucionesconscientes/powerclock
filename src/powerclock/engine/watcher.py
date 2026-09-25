"""State triggers (idle, cpu_below, net_below, battery, power_source, desktop_session,
process_exit) and the loop that samples the sensors active rules use.

A watched rule fires when its trigger's state becomes true (sustained for its `for`), and
only once: it is armed again when the state is false. A rule added while the state
already holds fires (e.g. the battery is already below 15 %), but staying idle does not
fire the idle rule again and again. `process_exit` fires when a process it has seen
running is gone: one that is not running yet is waited for, never taken as finished.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from powerclock.engine.clock import Clock
from powerclock.models import (
    Active,
    AllOf,
    AnyOf,
    BatteryLevel,
    CpuBelow,
    DesktopSession,
    Device,
    FileExists,
    Idle,
    NetBelow,
    NotOf,
    PowerSource,
    Predicate,
    ProcessExitTrigger,
    Rule,
    Temperature,
    UsedToday,
    WaitUntilStep,
    WifiSsid,
)
from powerclock.sensors.base import ProcessInfo, SensorPredicate
from powerclock.sensors.registry import SensorHub, Watched

log = logging.getLogger(__name__)

SENSOR_TRIGGERS = (
    Idle,
    CpuBelow,
    NetBelow,
    BatteryLevel,
    PowerSource,
    DesktopSession,
    WifiSsid,
    Active,
    UsedToday,
    FileExists,
    Device,
    Temperature,
)
STATE_TRIGGERS = (*SENSOR_TRIGGERS, ProcessExitTrigger)

OnFire = Callable[[Rule], None]
Demand = Callable[[], Iterable[Watched]]


def sensor_predicates(rule: Rule) -> Iterator[SensorPredicate]:
    """The sensor predicates in a rule's conditions, guards and wait_until steps."""
    roots: list[Predicate] = []
    if rule.conditions is not None:
        roots.append(rule.conditions)
    if rule.guards is not None:
        roots.extend(rule.guards.any)
    roots.extend(step.condition for step in rule.actions if isinstance(step, WaitUntilStep))
    for root in roots:
        yield from _leaves(root)


def _leaves(predicate: Predicate) -> Iterator[SensorPredicate]:
    match predicate:
        case AllOf(all=items) | AnyOf(any=items):
            for item in items:
                yield from _leaves(item)
        case NotOf(not_=inner):
            yield from _leaves(inner)
        case _ if isinstance(predicate, SensorPredicate):
            yield predicate


def is_state_rule(rule: Rule) -> bool:
    return isinstance(rule.trigger, STATE_TRIGGERS)


class WatchStatus(BaseModel):
    """What a watched rule is waiting for, as `/pending` shows it."""

    rule_id: str
    name: str
    trigger: dict[str, Any]
    state: bool | None  # whether the trigger's state holds now (None: unknown)
    armed: bool  # False: it fired and waits for the state to be false again
    value: float | str | None = None  # what the sensor reads (see SensorHub.measure)
    measured: float | None = None  # seconds of history so far, for averages
    checked_at: datetime | None = None  # None: not checked yet


@dataclass
class _Watch:
    rule: Rule
    armed: bool = True
    state: bool | None = None
    checked_at: datetime | None = None
    seen: set[tuple[int, float]] = field(default_factory=set)  # process_exit: (pid, started)


class Watcher:
    def __init__(self, hub: SensorHub, clock: Clock, on_fire: OnFire, demand: Demand) -> None:
        self._hub = hub
        self._clock = clock
        self._on_fire = on_fire
        self._demand = demand  # every item that needs polling, from the engine
        self._watches: dict[str, _Watch] = {}
        self._wakeup = asyncio.Event()

    def watch(self, rule: Rule) -> None:
        """Start, update or stop watching a rule: enabled rules with a state trigger are
        watched. A new version with the same trigger keeps what was observed."""
        if not (rule.enabled and is_state_rule(rule)):
            self.unwatch(rule.id)
            return
        current = self._watches.get(rule.id)
        if current is not None and current.rule.trigger == rule.trigger:
            current.rule = rule
        else:
            self._watches[rule.id] = _Watch(rule)
        self.poke()

    def unwatch(self, rule_id: str) -> None:
        self._watches.pop(rule_id, None)
        self.poke()  # rules changed: what must be sampled may have changed too

    def poke(self) -> None:
        """Check again now: rules changed or the machine resumed."""
        self._wakeup.set()

    def status(self) -> list[WatchStatus]:
        return [self._status(watch) for watch in self._watches.values()]

    async def run(self) -> None:
        while True:
            self._wakeup.clear()
            try:
                self._hub.demand(self._demand())
                await self._hub.sample()
                await self._check()
            except Exception:
                log.exception("checking the state triggers failed")
            await self._sleep(self._hub.next_due())  # None: nothing to sample, wait for a poke

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _check(self) -> None:
        for watch in list(self._watches.values()):
            state = await self._state(watch)
            if self._watches.get(watch.rule.id) is not watch:  # changed meanwhile
                continue
            watch.state, watch.checked_at = state, self._clock.now()
            if state is True and watch.armed:
                watch.armed = False
                watch.seen.clear()  # process_exit: wait for the next one to start
                try:
                    self._on_fire(watch.rule)
                except Exception:
                    log.exception("firing rule %s failed", watch.rule.id)
            elif state is False:
                watch.armed = True

    async def _state(self, watch: _Watch) -> bool | None:
        trigger = watch.rule.trigger
        if isinstance(trigger, ProcessExitTrigger):
            table = await self._hub.processes()
            return None if table is None else _exited(trigger, watch, table)
        assert isinstance(trigger, SENSOR_TRIGGERS)
        return await self._hub.check(trigger)

    def _status(self, watch: _Watch) -> WatchStatus:
        trigger = watch.rule.trigger
        value: float | str | None = None
        measured = None
        if isinstance(trigger, ProcessExitTrigger):
            value = "running" if watch.seen else "not_seen"
        elif isinstance(trigger, SENSOR_TRIGGERS):
            value, window = self._hub.measure(trigger)
            measured = None if window is None else window.total_seconds()
        return WatchStatus(
            rule_id=watch.rule.id,
            name=watch.rule.name,
            trigger=trigger.model_dump(mode="json"),
            state=watch.state,
            armed=watch.armed,
            value=value,
            measured=measured,
            checked_at=watch.checked_at,
        )

    async def _sleep(self, seconds: float | None) -> None:
        if self._wakeup.is_set():
            return
        waker = asyncio.ensure_future(self._wakeup.wait())
        waiting = {waker}
        if seconds is not None:
            waiting.add(asyncio.ensure_future(self._clock.sleep(seconds)))
        try:
            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in waiting:
                task.cancel()


def _exited(trigger: ProcessExitTrigger, watch: _Watch, table: list[ProcessInfo]) -> bool:
    """Whether the process(es) the rule has seen running are gone."""
    if trigger.pid is not None:
        running = {(p.pid, p.started) for p in table if p.pid == trigger.pid}
        if not watch.seen:
            watch.seen = running
            return False
        return not (watch.seen & running)  # same PID, other start time: it was reused
    running = {(p.pid, p.started) for p in table if p.name == trigger.name}
    if running:
        watch.seen |= running
        return False
    return bool(watch.seen)
