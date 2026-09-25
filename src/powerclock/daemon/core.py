"""The daemon: rules on disk, the engine, the run history and the event stream.

The API (api.py) is a thin layer over these methods.
"""

import asyncio
import contextlib
import dataclasses
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from powerclock import __version__, recipes
from powerclock.config import (
    USER_SETTINGS,
    Paths,
    Settings,
    atomic_write,
    ensure_token,
    read_secrets,
)
from powerclock.daemon.events import EventHub
from powerclock.daemon.store import History, RulesFileError, RuleStore
from powerclock.engine import Engine, savings
from powerclock.engine.clock import Clock
from powerclock.engine.runs import Event, Run
from powerclock.i18n import _, power_action_label
from powerclock.models import (
    AtTrigger,
    CountdownTrigger,
    CpuBelow,
    Duration,
    Idle,
    LaunchStep,
    ManualTrigger,
    NetBelow,
    NotifyStep,
    PositiveDuration,
    PowerStep,
    ProcessExitTrigger,
    Rule,
    RunStep,
    Trigger,
    format_duration,
)
from powerclock.platform import dry_run_requested
from powerclock.platform.base import (
    LogInMode,
    NotSupported,
    PlatformBackend,
    PowerAction,
    PowerMode,
)
from powerclock.sensors.base import Readings
from powerclock.sensors.system import SystemReadings
from powerclock.timeparse import resolve_at

log = logging.getLogger(__name__)

QUICK_PREFIX = "quick-"  # one-shot rules created by quick actions; removed once they end
HEARTBEAT = 60.0  # seconds between "still alive" marks, used to detect missed fires
AWAKE_GAP = timedelta(seconds=HEARTBEAT * 3)  # a longer silence: the computer was off or asleep
# Power actions that stop the computer: the period awake ends there (see engine/savings.py).
STOPPING = frozenset({"shutdown", "reboot", "suspend", "hibernate", "hybrid_sleep"})
RELOAD_POLL = 2.0  # seconds between checks of rules.json for hand edits
AUTOLOGIN_WATCH = 600.0  # seconds after starting to look for this boot's automatic log-in
AUTOLOGIN_POLL = 2.0
POSTPONE = timedelta(minutes=10)
SUSTAIN = timedelta(minutes=5)  # default `for` of --when-cpu-below / --when-net-below


class DaemonError(Exception):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


class QuickRequest(BaseModel):
    """A KShutdown-style action: now, in a while (`in`), at a time (`at`) or when a
    condition is met (`when_*`)."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True, serialize_by_alias=True)

    action: PowerAction | None = None
    command: list[str] | None = Field(default=None, min_length=1)
    app: str | None = Field(default=None, min_length=1)  # open this application…
    args: list[str] = Field(default_factory=list)  # …with these arguments
    recipe: str | None = None  # …and the window placement of this recipe (recipes.json)
    in_: PositiveDuration | None = Field(default=None, alias="in")
    at: str | None = None  # "23:30", "2026-09-24 07:30" or ISO with offset
    mode: PowerMode = PowerMode.GRACEFUL
    warning: Duration = timedelta(seconds=60)
    dry_run: bool = False
    wake: bool = False  # wake the machine up for this action (needs `in` or `at`)
    wake_at: str | None = None  # and/or wake it up at another time (suspend --wake 07:30)
    log_in: LogInMode | None = None  # log in once when that wake-up powers it on
    when_idle: PositiveDuration | None = None
    when_exits: str | None = Field(default=None, min_length=1)  # a process name or a PID
    when_cpu_below: float | None = Field(default=None, gt=0, le=100)  # percent
    when_net_below: float | None = Field(default=None, gt=0)  # kbit/s
    for_: PositiveDuration | None = Field(default=None, alias="for")  # with cpu/net: 5m

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if sum(item is not None for item in (self.action, self.command, self.app)) != 1:
            raise ValueError("set exactly one of: action, command, app")
        if (self.args or self.recipe) and self.app is None:
            raise ValueError("args and recipe only apply to app")
        if self.log_in is not None and not (self.wake or self.wake_at):
            raise ValueError("log_in needs wake or wake_at")
        when = ("in_", "at", "when_idle", "when_exits", "when_cpu_below", "when_net_below")
        if sum(getattr(self, name) is not None for name in when) > 1:
            raise ValueError(
                "set at most one of: in, at, when_idle, when_exits, when_cpu_below, when_net_below"
            )
        if self.for_ is not None and self.when_cpu_below is None and self.when_net_below is None:
            raise ValueError("for only applies to when_cpu_below and when_net_below")
        return self


class WakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str
    log_in: LogInMode | None = None


class PostponeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delay: PositiveDuration = POSTPONE


class Daemon:
    def __init__(
        self,
        backend: PlatformBackend,
        *,
        paths: Paths,
        settings: Settings | None = None,
        clock: Clock | None = None,
        dry_run: bool | None = None,
        readings: Readings | None = None,
    ) -> None:
        self.paths = paths
        self.settings = settings or Settings()
        self.backend = backend
        self._readings = readings or SystemReadings(backend)
        self.dry_run = (
            (self.settings.dry_run or dry_run_requested()) if dry_run is None else dry_run
        )
        self.token = ensure_token(paths.token)
        self.hub = EventHub()
        self.store = RuleStore(paths.rules)
        self.history = History(paths.history)
        self.tz = _timezone(backend)
        self.engine = Engine(
            backend,
            tz=self.tz,
            clock=clock,
            readings=self._readings,
            dry_run=self.dry_run,
            emit=self._on_event,
            request_wake=self._request_wake,  # the set_wake action
            variables={"home": str(Path.home()), "data": str(paths.data)},
            secrets=lambda: read_secrets(paths),
            tariff=lambda: self.settings.tariff,
        )
        self.started_at = self.engine.clock.now()
        self._tasks: list[asyncio.Task[None]] = []
        self._app_names: dict[str, str] = {}  # id → name, for the names of quick actions

        from powerclock.daemon.api import create_app

        self.app = create_app(self)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.dry_run:
            log.warning("dry run: power actions and wake alarms are only logged")
        self.store.load()
        since = self.history.last_alive()  # occurrences after this were missed
        for rule in list(self.store.rules.values()):
            self.engine.upsert(rule, since)
        await self.engine.start()
        self._heartbeat()
        self._tasks = [
            asyncio.create_task(_every(RELOAD_POLL, self.reload_rules), name="powerclock-reload"),
            asyncio.create_task(_every(HEARTBEAT, self._heartbeat), name="powerclock-heartbeat"),
            asyncio.create_task(self._learn_app_names(), name="powerclock-apps"),
            asyncio.create_task(self._after_autologin(), name="powerclock-autologin"),
        ]
        log.info("powerclock %s started: %d rule(s)", __version__, len(self.engine.rules))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.engine.stop()
        self._heartbeat()
        self.history.close()
        await self.backend.close()
        log.info("powerclock stopped")

    def reload_rules(self) -> None:
        """Apply hand edits of rules.json to the running engine."""
        result = self.store.reload_if_changed()
        if result is None:
            return
        changed, removed = result
        for rule in changed:
            self.engine.upsert(rule)
            self._publish_rule(rule.id, "reloaded")
        for rule_id in removed:
            self.engine.remove(rule_id)
            self._publish_rule(rule_id, "deleted")
        log.info("rules.json reloaded: %d changed, %d removed", len(changed), len(removed))

    # ── Applications ──────────────────────────────────────────────────────────

    async def apps(self) -> list[dict[str, Any]]:
        """The installed applications, each with the ids of the recipes made for it."""
        try:
            found = await self.backend.apps()
        except NotSupported as exc:
            raise DaemonError(501, str(exc)) from None
        self._app_names = {app.id: app.name for app in found}
        return [
            {
                **dataclasses.asdict(app),
                "categories": list(app.categories),
                "recipes": [recipe.id for recipe in recipes.for_app(app.id, app.flatpak)],
            }
            for app in found
        ]

    def list_recipes(self) -> list[dict[str, Any]]:
        return [recipe.as_json() for recipe in recipes.recipes()]

    async def _after_autologin(self) -> None:
        """If this boot logged the user in by itself (a scheduled power-on with log_in), lock
        the screen as soon as the desktop is up (unless the rule asked for it visible) and
        remove the log-in setting, so nothing is left for another boot or display manager
        restart. Looked for during the first minutes after starting."""
        clock = self.engine.clock
        try:
            for _ in range(round(AUTOLOGIN_WATCH / AUTOLOGIN_POLL)):
                mode = await self.backend.autologin_used()
                if mode is not None and await self.backend.desktop_session():
                    if mode == "locked":
                        await self.backend.power(PowerAction.LOCK, PowerMode.GRACEFUL)
                    await self.backend.autologin_done()
                    log.info("logged in by itself after a scheduled power-on (%s)", mode)
                    return
                await clock.sleep(AUTOLOGIN_POLL)
        except NotSupported:
            return
        except Exception:
            log.exception("could not finish the automatic log-in")

    async def _learn_app_names(self) -> None:
        with contextlib.suppress(Exception):
            self._app_names = {app.id: app.name for app in await self.backend.apps()}

    # ── Rules ─────────────────────────────────────────────────────────────────

    def list_rules(self) -> list[Rule]:
        return list(self.engine.rules.values())

    def get_rule(self, rule_id: str) -> Rule:
        rule = self.engine.rules.get(rule_id)
        if rule is None:
            raise DaemonError(404, f"no rule {rule_id!r}")
        return rule

    def create_rule(self, data: dict[str, Any]) -> Rule:
        data = {"id": f"rule-{uuid.uuid4().hex[:8]}", **data}
        rule = _validate(data)
        if rule.id in self.engine.rules:
            raise DaemonError(409, f"a rule with id {rule.id!r} already exists")
        return self._save(rule, "created")

    def replace_rule(self, rule_id: str, data: dict[str, Any]) -> Rule:
        self.get_rule(rule_id)
        data = {"id": rule_id, **data}
        if data["id"] != rule_id:
            raise DaemonError(422, "the id in the body does not match the one in the URL")
        return self._save(_validate(data), "updated")

    def delete_rule(self, rule_id: str) -> None:
        self.get_rule(rule_id)
        self._check_writable()
        self.engine.remove(rule_id)
        self.store.delete(rule_id)
        self._publish_rule(rule_id, "deleted")

    def set_enabled(self, rule_id: str, enabled: bool) -> Rule:
        rule = self.get_rule(rule_id)
        return self._save(rule.model_copy(update={"enabled": enabled}), "updated")

    def run_rule(self, rule_id: str) -> Run:
        self.get_rule(rule_id)
        return self.engine.run_now(rule_id)

    # ── Quick actions ─────────────────────────────────────────────────────────

    def quick(self, request: QuickRequest) -> Rule:
        now = self.engine.clock.now()
        step: PowerStep | RunStep | LaunchStep
        if request.action is not None:
            step = PowerStep(action=request.action, mode=request.mode)
            label = power_action_label(request.action)
        elif request.app is not None:
            recipe = recipes.get(request.recipe) if request.recipe else None
            if request.recipe and recipe is None:
                raise DaemonError(422, f"no recipe {request.recipe!r}")
            step = LaunchStep(
                app=request.app,
                args=request.args,
                recipe=request.recipe,
                window=recipe.window if recipe else None,
                keep_open=recipe.keep_open if recipe else False,
            )
            label = _("Open {app}").format(app=self._app_names.get(request.app, request.app))
        else:
            assert request.command is not None
            step = RunStep(cmd=request.command)
            label = _("Run {program}").format(program=request.command[0].rsplit("/", 1)[-1])
        try:
            trigger, name = self._quick_trigger(request, label, now)
            rule = Rule(
                id=f"{QUICK_PREFIX}{uuid.uuid4().hex[:6]}",
                name=name,
                trigger=trigger,
                actions=[step],
                warning=request.warning,
                one_shot=True,
                dry_run=request.dry_run,
                wake=request.wake,
                log_in=request.log_in if request.wake else None,
            )
        except ValidationError as exc:
            raise DaemonError(422, json.loads(exc.json(include_url=False))) from None
        wake_at = self._resolve(request.wake_at, now) if request.wake_at else None
        stored = self._save(rule, "created")
        if wake_at is not None:
            self.create_wake(wake_at, log_in=request.log_in)
        if isinstance(trigger, ManualTrigger):
            self.engine.run_now(rule.id)
        return stored

    def _quick_trigger(
        self, request: QuickRequest, label: str, now: datetime
    ) -> tuple[Trigger, str]:
        """The trigger of a quick action and the rule name that describes it."""
        sustain = request.for_ or SUSTAIN
        if request.in_ is not None:
            delay = format_duration(request.in_)
            return CountdownTrigger(duration=request.in_), _("{action} in {delay}").format(
                action=label, delay=delay
            )
        if request.at is not None:
            when = self._resolve(request.at, now)
            local = when.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
            return AtTrigger(when=when), _("{action} at {time}").format(action=label, time=local)
        if request.when_idle is not None:
            delay = format_duration(request.when_idle)
            return Idle(for_=request.when_idle), _("{action} after {delay} without use").format(
                action=label, delay=delay
            )
        if request.when_exits is not None:
            target = request.when_exits
            if target.isdigit():
                trigger = ProcessExitTrigger(pid=int(target))
                target = f"PID {target}"
            else:
                trigger = ProcessExitTrigger(name=target)
            return trigger, _("{action} when {process} ends").format(action=label, process=target)
        if request.when_cpu_below is not None:
            name = _(
                "{action} when the computer goes quiet (CPU below {percent} % for {delay})"
            ).format(
                action=label, percent=f"{request.when_cpu_below:g}", delay=format_duration(sustain)
            )
            return CpuBelow(percent=request.when_cpu_below, for_=sustain), name
        if request.when_net_below is not None:
            name = _(
                "{action} when the download finishes (network below {kbps} kbit/s for {delay})"
            ).format(
                action=label, kbps=f"{request.when_net_below:g}", delay=format_duration(sustain)
            )
            return NetBelow(kbps=request.when_net_below, for_=sustain), name
        return ManualTrigger(), label

    def wake(self, request: WakeRequest) -> Rule:
        when = self._resolve(request.at, self.engine.clock.now())
        return self.create_wake(when, log_in=request.log_in)

    def create_wake(self, when: datetime, *, log_in: LogInMode | None = None) -> Rule:
        """A one-shot rule whose only job is to wake the machine up at `when`."""
        local = when.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        rule = Rule(
            id=f"{QUICK_PREFIX}{uuid.uuid4().hex[:6]}",
            name=_("Turn on at {time}").format(time=local),
            trigger=AtTrigger(when=when),
            wake=True,
            log_in=log_in,
            one_shot=True,
            warning=timedelta(0),
            actions=[NotifyStep(title="PowerClock", body=_("Turned on as scheduled"))],
        )
        return self._save(rule, "created")

    async def _request_wake(self, when: datetime) -> None:
        self.create_wake(when)

    def _resolve(self, text: str, now: datetime) -> datetime:
        try:
            when = resolve_at(text, now, self.tz)
        except ValueError as exc:
            raise DaemonError(422, str(exc)) from None
        if when <= now:
            raise DaemonError(422, f"{text!r} is already in the past")
        return when

    # ── Runs ──────────────────────────────────────────────────────────────────

    def pending(self) -> dict[str, Any]:
        rules = self.engine.rules
        upcoming = sorted(self.engine.pending().items(), key=lambda item: item[1])
        return {
            "next": [
                {"rule_id": rule_id, "name": rules[rule_id].name, "at": at}
                for rule_id, at in upcoming
            ],
            "active": self.engine.executor.active,
            "watching": self.engine.watching(),
            "wake": {"at": self.engine.wake.target, "error": self.engine.wake.error},
        }

    def get_run(self, run_id: str) -> Run:
        run = self.engine.executor.get(run_id) or self.history.get(run_id)
        if run is None:
            raise DaemonError(404, f"no run {run_id!r}")
        return run

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.engine.executor.get(run_id)
        if run is None or not self.engine.executor.cancel(run_id):
            raise DaemonError(404, f"no active run {run_id!r}")
        return {"cancelled": "run", "run_id": run.id, "rule_id": run.rule_id, "name": run.rule_name}

    def cancel_rule(self, rule_id: str) -> dict[str, Any]:
        """One rule: its run in progress; else, for a quick action, the action itself before
        it fires (other rules are disabled instead)."""
        rule = self.get_rule(rule_id)
        executor = self.engine.executor
        run = next((r for r in executor.active if r.rule_id == rule_id), None)
        if run is not None:
            executor.cancel(run.id)
            return {"cancelled": "run", "run_id": run.id, "rule_id": rule_id, "name": rule.name}
        if not rule_id.startswith(QUICK_PREFIX):
            raise DaemonError(409, f"{rule.name!r} is not running: disable the rule instead")
        executor.record(
            rule,
            "cancelled",
            "cancelled before it fired",
            cause="manual",
            scheduled_for=self.engine.pending().get(rule_id),
        )  # its run_finished removes the quick rule and writes the history
        return {"cancelled": "rule", "rule_id": rule_id, "name": rule.name}

    def cancel_current(self) -> dict[str, Any]:
        """The countdown in progress; else a quick action running or waiting to fire."""
        executor = self.engine.executor
        run = executor.cancel_countdown()
        if run is None:
            run = next((r for r in executor.active if r.rule_id.startswith(QUICK_PREFIX)), None)
            if run is not None:
                executor.cancel(run.id)
        if run is not None:
            return {
                "cancelled": "run",
                "run_id": run.id,
                "rule_id": run.rule_id,
                "name": run.rule_name,
            }
        rule, when = self._next_quick()
        if rule is None:
            raise DaemonError(404, "nothing to cancel")
        executor.record(
            rule,
            "cancelled",
            "cancelled before it fired",
            cause="manual",
            scheduled_for=when,
        )  # its run_finished removes the quick rule and writes the history
        return {"cancelled": "rule", "rule_id": rule.id, "name": rule.name}

    def postpone_run(self, run_id: str, delay: timedelta) -> dict[str, Any]:
        if not self.engine.executor.postpone(run_id, delay):
            raise DaemonError(409, f"run {run_id!r} is not counting down")
        run = self.get_run(run_id)
        return {
            "postponed": "run",
            "run_id": run_id,
            "name": run.rule_name,
            "at": run.deadline,
        }

    def postpone_current(self, delay: timedelta) -> dict[str, Any]:
        """Push back the countdown in progress; else the next quick action."""
        for run in self.engine.executor.active:
            if run.state == "warning":
                return self.postpone_run(run.id, delay)
        rule, _when = self._next_quick()
        if rule is None:
            raise DaemonError(404, "nothing to postpone")
        return self._delay(rule, delay)

    def postpone_rule(self, rule_id: str, delay: timedelta) -> dict[str, Any]:
        """One rule: its countdown in progress; else, for a quick action, its moment."""
        rule = self.get_rule(rule_id)
        for run in self.engine.executor.active:
            if run.rule_id == rule_id and run.state == "warning":
                return self.postpone_run(run.id, delay)
        if not rule_id.startswith(QUICK_PREFIX):
            raise DaemonError(409, f"{rule.name!r} is not counting down: edit the rule instead")
        return self._delay(rule, delay)

    def _delay(self, rule: Rule, delay: timedelta) -> dict[str, Any]:
        """Move a quick action's moment `delay` later."""
        trigger = rule.trigger
        if isinstance(trigger, CountdownTrigger):
            trigger = trigger.model_copy(update={"duration": trigger.duration + delay})
        elif isinstance(trigger, AtTrigger):
            trigger = trigger.model_copy(update={"when": trigger.when + delay})
        else:
            raise DaemonError(
                409, f"{rule.name!r} waits for a condition, not a time: cancel it instead"
            )
        self._save(rule.model_copy(update={"trigger": trigger}), "updated")
        return {
            "postponed": "rule",
            "rule_id": rule.id,
            "name": rule.name,
            "at": self.engine.pending().get(rule.id),
        }

    # ── Information ───────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        now = self.engine.clock.now()
        return {
            "version": __version__,
            "backend": self.backend.name,
            "dry_run": self.dry_run,
            "timezone": str(self.tz),
            "started_at": self.started_at,
            "uptime": round((now - self.started_at).total_seconds()),
            "rules": len(self.engine.rules),
            "rules_errors": self.store.errors,
            "clients": self.hub.subscribers,
            "tariff": self.settings.tariff,
        }

    def set_tariff(self, tariff: str | None) -> dict[str, Any]:
        """Choose the electricity tariff (None: none)."""
        return {"tariff": self.update_settings({"tariff": tariff})["tariff"]}

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Change the settings clients may change (USER_SETTINGS); saved in daemon.json."""
        unknown = set(changes) - USER_SETTINGS
        if unknown:
            raise DaemonError(422, f"these settings cannot be changed here: {sorted(unknown)}")
        try:
            updated = Settings.model_validate({**self.settings.model_dump(), **changes})
        except ValidationError as exc:
            raise DaemonError(422, json.loads(exc.json(include_url=False))) from None
        atomic_write(self.paths.settings, updated.model_dump_json(indent=2) + "\n")
        self.settings = updated
        return {name: getattr(updated, name) for name in sorted(USER_SETTINGS)}

    # ── Use and savings ───────────────────────────────────────────────────────

    async def stats(self, days: int = 30) -> dict[str, Any]:
        """Time on and off over the last `days`, and what PowerClock saved (estimated)."""
        now = self.engine.clock.now()
        found = savings.stats(
            self.history.awake(now - timedelta(days=days)), now - timedelta(days=days), now
        )
        watts = self.settings.watts
        if watts is None:
            try:
                state = await self._readings.power()
            except Exception:
                state = None
            watts = savings.default_watts(None if state is None else state.percent is not None)
        price = (
            self.settings.price_kwh if self.settings.price_kwh is not None else savings.PRICE_KWH
        )
        kwh = found.saved_kwh(watts)
        return {
            "days": days,
            "since": found.since,
            "until": found.until,
            "on_hours": round(found.on.total_seconds() / 3600, 1),
            "off_hours": round(found.off.total_seconds() / 3600, 1),
            "saved_hours": round(found.off_by_powerclock.total_seconds() / 3600, 1),
            "actions": found.actions,
            "watts": watts,
            "watts_estimated": self.settings.watts is None,
            "price_kwh": price,
            "price_estimated": self.settings.price_kwh is None,
            "currency": self.settings.currency,
            "kwh": round(kwh, 2),
            "money": round(kwh * price, 2),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _save(self, rule: Rule, change: str) -> Rule:
        self._check_writable()
        stored = self.engine.upsert(rule)  # may arm a countdown
        self.store.put(stored)
        self._publish_rule(rule.id, change)
        return stored

    def _check_writable(self) -> None:
        if self.store.errors:
            raise DaemonError(
                409,
                f"{self.paths.rules} has errors, fix them first: " + "; ".join(self.store.errors),
            )

    def _next_quick(self) -> tuple[Rule | None, datetime | None]:
        """The next timed quick action; else the latest one waiting for a condition."""
        upcoming = [
            (at, rule_id)
            for rule_id, at in self.engine.pending().items()
            if rule_id.startswith(QUICK_PREFIX)
        ]
        if upcoming:
            when, rule_id = min(upcoming)
            return self.engine.rules[rule_id], when
        watched = [w.rule_id for w in self.engine.watching() if w.rule_id.startswith(QUICK_PREFIX)]
        if watched:
            return self.engine.rules[watched[-1]], None
        return None, None

    def _on_event(self, event: Event) -> None:
        if event.type == "power_action" and event.data.get("action") in STOPPING:
            self.history.mark_ended(event.at, str(event.data["action"]))
        if event.type == "run_finished" and event.run_id is not None:
            run = self.engine.executor.get(event.run_id)
            if run is not None:
                self.history.add(run)
                if run.rule_id.startswith(QUICK_PREFIX):
                    self._forget(run.rule_id)
        elif event.type == "rule_changed" and event.rule_id in self.engine.rules:
            try:  # armed countdown, one-shot rule done…
                self.store.put(self.engine.rules[event.rule_id])
            except RulesFileError as exc:
                log.warning("cannot save rule %s: %s", event.rule_id, exc)
        self.hub.publish(event)

    def _forget(self, rule_id: str) -> None:
        if rule_id not in self.engine.rules:
            return
        self.engine.remove(rule_id)
        with contextlib.suppress(RulesFileError):
            self.store.delete(rule_id)
        self._publish_rule(rule_id, "deleted")

    def _publish_rule(self, rule_id: str, change: str) -> None:
        self.hub.publish(
            Event(
                type="rule_changed",
                at=self.engine.clock.now(),
                rule_id=rule_id,
                data={"change": change},
            )
        )

    def _heartbeat(self) -> None:
        now = self.engine.clock.now()
        self.history.set_last_alive(now)
        self.history.mark_awake(now, AWAKE_GAP)


def _validate(data: dict[str, Any]) -> Rule:
    try:
        return Rule.model_validate(data)
    except ValidationError as exc:
        raise DaemonError(422, json.loads(exc.json(include_url=False))) from None


def _timezone(backend: PlatformBackend) -> tzinfo:
    try:
        return backend.timezone()
    except NotSupported:
        return UTC


async def _every(seconds: float, action: Callable[[], None]) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            action()
        except Exception:
            log.exception("periodic task failed")
