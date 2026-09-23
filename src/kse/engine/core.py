"""Engine: wires the scheduler, the evaluator and the executor around one backend."""

import asyncio
import contextlib
import logging
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from kse.engine.clock import Clock, SystemClock
from kse.engine.evaluator import Evaluator
from kse.engine.executor import Executor, RequestWake
from kse.engine.processes import ProcessManager
from kse.engine.runs import Event, EventSink, Run
from kse.engine.scheduler import Scheduler
from kse.engine.wake import WakePlanner
from kse.models import CountdownTrigger, Rule
from kse.platform.base import NotSupported, PlatformBackend, PowerEvent
from kse.sensors.base import SensorReader, UnknownSensors

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
        sensors: SensorReader | None = None,
        processes: ProcessManager | None = None,
        dry_run: bool = False,
        emit: EventSink | None = None,
        request_wake: RequestWake | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self._backend = backend
        self._tz = tz  # for rules without their own `timezone`
        self._sink = emit
        self.evaluator = Evaluator(sensors or UnknownSensors(), self.clock)
        self.executor = Executor(
            backend,
            self.evaluator,
            self.clock,
            dry_run=dry_run,
            emit=emit,
            processes=processes,
            request_wake=request_wake,
        )
        self.scheduler = Scheduler(self.clock, self._on_due)
        self.wake = WakePlanner(backend, self.clock, self._wake_times, emit=emit)
        self._rules: dict[str, Rule] = {}
        self._loop: asyncio.Task[None] | None = None
        self._wake_loop: asyncio.Task[None] | None = None

    @property
    def rules(self) -> dict[str, Rule]:
        return dict(self._rules)

    async def start(self) -> None:
        try:
            await self._backend.subscribe_power_events(self._on_power_event)
        except NotSupported:
            log.info("no power events on this platform; relying on periodic re-checks")
        self._loop = asyncio.create_task(self.scheduler.run(), name="kse-scheduler")
        self._wake_loop = asyncio.create_task(self.wake.run(), name="kse-wake")
        self.wake.request_sync()

    async def stop(self) -> None:
        for task in (self._loop, self._wake_loop):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._loop = self._wake_loop = None
        await self.executor.shutdown()

    def upsert(self, rule: Rule, since: datetime | None = None) -> Rule:
        """Add or replace a rule; returns the version the engine keeps (maybe armed).

        `since` is when the rule was last checked, so occurrences missed while the daemon
        was not running can be detected (see Scheduler.schedule).
        """
        rule = self._arm(rule, self._rules.get(rule.id))
        self._rules[rule.id] = rule
        self.scheduler.schedule(rule, self._tz_for(rule), since)
        self.wake.request_sync()
        return rule

    def remove(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)
        self.scheduler.unschedule(rule_id)
        self.wake.request_sync()

    def run_now(self, rule_id: str) -> Run:
        rule = self._rules[rule_id]
        return self.executor.start(rule, self._tz_for(rule), cause="manual")

    def pending(self) -> dict[str, datetime]:
        return self.scheduler.pending()

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

    def _on_due(self, rule: Rule, scheduled_for: datetime, missed: bool) -> None:
        tz = self._tz_for(rule)
        if rule.one_shot:  # before running: listeners may remove the rule once the run ends
            finished = rule.model_copy(update={"enabled": False})
            self._rules[rule.id] = finished
            self.scheduler.schedule(finished, tz)
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
            self.executor.start(
                rule, tz, cause="schedule", scheduled_for=scheduled_for, missed=missed
            )

    async def _on_power_event(self, event: PowerEvent) -> None:
        if event is PowerEvent.AFTER_RESUME:
            self.scheduler.poke()
        await self.wake.on_power_event(event)

    def _wake_times(self) -> list[datetime]:
        rules = self._rules
        return [
            due
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
