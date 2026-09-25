"""Engine: wires the scheduler, the watcher, the evaluator and the executor around one
backend."""

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from powerclock.engine.clock import Clock, SystemClock
from powerclock.engine.evaluator import Evaluator
from powerclock.engine.executor import Executor, RequestWake
from powerclock.engine.processes import ProcessManager
from powerclock.engine.runs import Event, EventSink, Run, RunCause
from powerclock.engine.scheduler import Scheduler
from powerclock.engine.wake import WakeNeed, WakePlanner
from powerclock.engine.watcher import STATE_TRIGGERS, Watcher, WatchStatus, sensor_predicates
from powerclock.models import CountdownTrigger, Rule, StartupTrigger
from powerclock.platform.base import NotSupported, PlatformBackend, PowerEvent
from powerclock.sensors.base import NoReadings, Readings
from powerclock.sensors.registry import SensorHub, Watched, needs_polling

log = logging.getLogger(__name__)

MISSED_REASON = "missed: the machine was off or asleep, or the daemon was not running"


class Engine:
    """Holds the active rules and fires them.

    When the engine changes a rule itself (arming a countdown, disabling a one-shot rule)
    it emits `rule_changed`, so the daemon can persist the new version.
    """

    def __init__(
        self,
        backend: PlatformBackend,
        *,
        tz: tzinfo,
        clock: Clock | None = None,
        readings: Readings | None = None,
        processes: ProcessManager | None = None,
        dry_run: bool = False,
        emit: EventSink | None = None,
        request_wake: RequestWake | None = None,
        variables: Mapping[str, str] | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self._backend = backend
        self._tz = tz  # for rules without their own `timezone`
        self._sink = emit
        self.sensors = SensorHub(readings or NoReadings(), self.clock)
        self.evaluator = Evaluator(self.sensors, self.clock)
        self.executor = Executor(
            backend,
            self.evaluator,
            self.clock,
            dry_run=dry_run,
            emit=emit,
            processes=processes,
            request_wake=request_wake,
            variables=variables,
        )
        self.scheduler = Scheduler(self.clock, self._on_due)
        self.watcher = Watcher(self.sensors, self.clock, self._on_state, self._demand)
        self.wake = WakePlanner(backend, self.clock, self._wake_times, emit=emit)
        self._rules: dict[str, Rule] = {}
        self._loops: list[asyncio.Task[None]] = []
        self._delayed: set[asyncio.Task[None]] = set()  # startup rules waiting for their delay

    @property
    def rules(self) -> dict[str, Rule]:
        return dict(self._rules)

    async def start(self) -> None:
        try:
            await self._backend.subscribe_power_events(self._on_power_event)
        except NotSupported:
            log.info("no power events on this platform; relying on periodic re-checks")
        self._loops = [
            asyncio.create_task(self.scheduler.run(), name="powerclock-scheduler"),
            asyncio.create_task(self.watcher.run(), name="powerclock-watcher"),
            asyncio.create_task(self.wake.run(), name="powerclock-wake"),
        ]
        self.wake.request_sync()
        self._startup("daemon_start")

    @property
    def running(self) -> bool:
        return bool(self._loops)

    async def stop(self) -> None:
        for task in [*self._loops, *self._delayed]:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._loops = []
        await self.executor.shutdown()

    def upsert(self, rule: Rule, since: datetime | None = None) -> Rule:
        """Add or replace a rule; returns the version the engine keeps (maybe armed).

        `since` is when the rule was last checked, so occurrences missed while the daemon
        was not running can be detected (see Scheduler.schedule).
        """
        rule = self._arm(rule, self._rules.get(rule.id))
        self._rules[rule.id] = rule
        self._install(rule, since)
        self.wake.request_sync()
        return rule

    def remove(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)
        self.scheduler.unschedule(rule_id)
        self.watcher.unwatch(rule_id)
        self.wake.request_sync()

    def run_now(self, rule_id: str) -> Run:
        rule = self._rules[rule_id]
        return self.executor.start(rule, self._tz_for(rule), cause="manual")

    def pending(self) -> dict[str, datetime]:
        return self.scheduler.pending()

    def watching(self) -> list[WatchStatus]:
        """Enabled rules with a state trigger and what they are waiting for."""
        return self.watcher.status()

    def _arm(self, rule: Rule, previous: Rule | None) -> Rule:
        """A countdown starts counting when its rule is enabled."""
        trigger = rule.trigger
        if not isinstance(trigger, CountdownTrigger) or not rule.enabled:
            return rule
        re_enabled = previous is not None and not previous.enabled
        if trigger.armed_at is not None and not re_enabled:
            return rule
        armed_trigger = trigger.model_copy(update={"armed_at": self.clock.now()})
        armed = rule.model_copy(update={"trigger": armed_trigger})
        self._rule_changed(armed)
        return armed

    def _install(self, rule: Rule, since: datetime | None = None) -> None:
        self.scheduler.schedule(rule, self._tz_for(rule), since)
        self.watcher.watch(rule)

    def _on_due(self, rule: Rule, scheduled_for: datetime, missed: bool) -> None:
        self._fire(rule, "schedule", scheduled_for=scheduled_for, missed=missed)

    def _on_state(self, rule: Rule) -> None:
        self._fire(rule, "trigger")

    def _fire(
        self,
        rule: Rule,
        cause: RunCause,
        *,
        scheduled_for: datetime | None = None,
        missed: bool = False,
    ) -> None:
        tz = self._tz_for(rule)
        if rule.one_shot:  # before running: listeners may remove the rule once the run ends
            finished = rule.model_copy(update={"enabled": False})
            self._rules[rule.id] = finished
            self._install(finished)
            self._rule_changed(finished)
        self.wake.request_sync()  # the next occurrence may need another wake-up
        if missed and rule.on_missed == "skip":
            self.executor.record(
                rule,
                "skipped",
                MISSED_REASON,
                cause="schedule",
                scheduled_for=scheduled_for,
                missed=True,
            )
        else:
            self.executor.start(rule, tz, cause=cause, scheduled_for=scheduled_for, missed=missed)

    def _startup(self, event: Literal["daemon_start", "resume"]) -> None:
        for rule in self._rules.values():
            trigger = rule.trigger
            if rule.enabled and isinstance(trigger, StartupTrigger) and event in trigger.on:
                task = asyncio.create_task(self._fire_after(rule, trigger.delay))
                self._delayed.add(task)
                task.add_done_callback(self._delayed.discard)

    async def _fire_after(self, rule: Rule, delay: timedelta) -> None:
        await self.clock.sleep(delay.total_seconds())
        current = self._rules.get(rule.id)
        if current is not None and current.enabled and current.trigger == rule.trigger:
            self._fire(current, "trigger")

    def _demand(self) -> list[Watched]:
        """What the sensors must sample all along: the triggers of watched rules and the
        predicates with a `for` of enabled rules and of rules with a run in progress."""
        active = {run.rule_id for run in self.executor.active}
        items: list[Watched] = []
        for rule in self._rules.values():
            if rule.enabled and isinstance(rule.trigger, STATE_TRIGGERS):
                items.append(rule.trigger)
            if rule.enabled or rule.id in active:
                items.extend(p for p in sensor_predicates(rule) if needs_polling(p))
        return items

    async def _on_power_event(self, event: PowerEvent) -> None:
        if event is PowerEvent.AFTER_RESUME:
            self.scheduler.poke()
            self.watcher.poke()
            self._startup("resume")
        await self.wake.on_power_event(event)

    def _wake_times(self) -> list[WakeNeed]:
        rules = self._rules
        return [
            (due, rules[rule_id].log_in)
            for rule_id, due in self.scheduler.pending().items()
            if rule_id in rules and rules[rule_id].wake
        ]

    def _rule_changed(self, rule: Rule) -> None:
        if self._sink is None:
            return
        try:
            self._sink(Event(type="rule_changed", at=self.clock.now(), rule_id=rule.id))
        except Exception:
            log.exception("event listener failed")

    def _tz_for(self, rule: Rule) -> tzinfo:
        return ZoneInfo(rule.timezone) if rule.timezone else self._tz
