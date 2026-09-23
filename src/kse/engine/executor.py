"""Runs rules: conditions → guards → actions, keeping a Run record of every firing."""

import asyncio
import contextlib
import logging
import os
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from kse.engine.clock import Clock
from kse.engine.evaluator import Evaluator, describe
from kse.engine.processes import ProcessManager, PsutilProcesses
from kse.engine.runs import (
    Event,
    EventSink,
    EventType,
    Run,
    RunCause,
    RunState,
    StepResult,
    StepStatus,
)
from kse.i18n import _, power_action_label
from kse.models import (
    Action,
    CloseAppStep,
    NotifyStep,
    OpenStep,
    PowerStep,
    Rule,
    RunStep,
    SetWakeStep,
    WaitStep,
    WaitUntilStep,
    format_duration,
)
from kse.platform.base import NotSupported, PlatformBackend

log = logging.getLogger(__name__)

TICK = 1.0  # seconds between countdown ticks
POLL = 5.0  # seconds between wait_until checks
POSTPONE = timedelta(minutes=10)  # the countdown notification's "postpone" button
OUTPUT_TAIL = 4000  # characters of command output kept in the run record
TERMINATE_GRACE = 5.0  # seconds between asking a command to stop and killing it

RequestWake = Callable[[datetime], Awaitable[None]]
Outcome = tuple[StepStatus, str | None]


class StepFailed(Exception):
    """A step could not do its job; the message goes to the run record."""


class _Skip(Exception):
    """The run ends without running its actions."""


@dataclass
class _Active:
    run: Run
    task: asyncio.Task[None]


class Executor:
    def __init__(
        self,
        backend: PlatformBackend,
        evaluator: Evaluator,
        clock: Clock,
        *,
        dry_run: bool = False,
        emit: EventSink | None = None,
        processes: ProcessManager | None = None,
        request_wake: RequestWake | None = None,
        keep: int = 100,
    ) -> None:
        self._backend = backend
        self._evaluator = evaluator
        self._clock = clock
        self._dry_run = dry_run
        self._sink = emit
        self._processes = processes or PsutilProcesses()
        self._request_wake = request_wake  # provided by the WakePlanner (M5)
        self._power_lock = asyncio.Lock()  # one power action (and countdown) at a time
        self._active: dict[str, _Active] = {}
        self._background: set[asyncio.Task[Any]] = set()
        self.recent: deque[Run] = deque(maxlen=keep)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def active(self) -> list[Run]:
        return [active.run for active in self._active.values()]

    @property
    def background(self) -> int:
        """Commands started with `wait: false` that are still running."""
        return len(self._background)

    def get(self, run_id: str) -> Run | None:
        if run_id in self._active:
            return self._active[run_id].run
        return next((run for run in self.recent if run.id == run_id), None)

    def start(
        self,
        rule: Rule,
        tz: tzinfo,
        *,
        cause: RunCause,
        scheduled_for: datetime | None = None,
        missed: bool = False,
    ) -> Run:
        run = self._new_run(rule, cause, scheduled_for, missed)
        if any(active.run.rule_id == rule.id for active in self._active.values()):
            self._finish(run, "skipped", "the previous run of this rule is still active")
            return run
        task = asyncio.create_task(self._execute(rule, tz, run), name=f"kse-run-{run.id}")
        self._active[run.id] = _Active(run, task)
        return run

    def skip(
        self,
        rule: Rule,
        reason: str,
        *,
        cause: RunCause,
        scheduled_for: datetime | None = None,
        missed: bool = False,
    ) -> Run:
        """Record a firing that does not run (e.g. missed with on_missed: skip)."""
        run = self._new_run(rule, cause, scheduled_for, missed)
        self._finish(run, "skipped", reason)
        return run

    async def wait(self, run_id: str) -> Run:
        """Wait until a run ends (without cancelling it if the caller is cancelled)."""
        active = self._active.get(run_id)
        if active is not None:
            await asyncio.shield(active.task)
        run = self.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def cancel(self, run_id: str) -> bool:
        active = self._active.get(run_id)
        if active is None:
            return False
        active.task.cancel()
        return True

    def cancel_countdown(self) -> Run | None:
        """Cancel the run whose power countdown is in progress, if any."""
        for active in self._active.values():
            if active.run.state == "warning":
                active.task.cancel()
                return active.run
        return None

    def postpone(self, run_id: str, delay: timedelta = POSTPONE) -> bool:
        """Push back the power countdown of a run; False if it is not counting down."""
        active = self._active.get(run_id)
        if active is None or active.run.state != "warning" or active.run.deadline is None:
            return False
        active.run.deadline += delay
        self._emit("postponed", active.run, deadline=active.run.deadline.isoformat())
        return True

    async def shutdown(self) -> None:
        """Cancel every active run and wait for them to finish."""
        tasks = [active.task for active in self._active.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    async def _execute(self, rule: Rule, tz: tzinfo, run: Run) -> None:
        self._emit("run_started", run)
        state: RunState = "done"
        reason: str | None = None
        try:
            await self._check_conditions(rule, tz)
            await self._wait_for_guards(rule, tz, run)
            reason = await self._run_actions(rule, tz, run)
            state = "failed" if reason else "done"
        except _Skip as skip:
            state, reason = "skipped", str(skip)
        except asyncio.CancelledError:
            state, reason = "cancelled", "cancelled"
            self._emit("cancelled", run)
        except Exception as exc:
            log.exception("run %s of rule %s crashed", run.id, rule.id)
            state, reason = "failed", f"internal error: {exc}"
        finally:
            self._active.pop(run.id, None)
            self._finish(run, state, reason)

    async def _check_conditions(self, rule: Rule, tz: tzinfo) -> None:
        if rule.conditions is None:
            return
        result = await self._evaluator.evaluate(rule.conditions, tz)
        if result is False:
            raise _Skip("conditions not met")
        if result is None:
            raise _Skip("conditions unknown: a sensor could not be read")

    async def _wait_for_guards(self, rule: Rule, tz: tzinfo, run: Run) -> None:
        guards = rule.guards
        if guards is None:
            return
        started = self._clock.now()
        while (blocking := await self._evaluator.first_true(guards.any, tz)) is not None:
            waited = self._clock.now() - started
            if waited >= guards.max_wait:
                raise _Skip(
                    f"guard still active after {format_duration(guards.max_wait)}: "
                    f"{describe(blocking)}"
                )
            self._set_state(run, "postponed", f"guard active: {describe(blocking)}")
            self._emit("postponed", run, guard=describe(blocking))
            await self._clock.sleep(min(guards.retry, guards.max_wait - waited).total_seconds())
        self._set_state(run, "running", None)

    async def _run_actions(self, rule: Rule, tz: tzinfo, run: Run) -> str | None:
        """Run the steps in order; return the first failure (None if all went well)."""
        failure: str | None = None
        for index, step in enumerate(rule.actions):
            result = StepResult(index=index, type=step.type, started_at=self._clock.now())
            run.steps.append(result)
            try:
                result.status, result.detail = await self._do(step, rule, tz, run)
            except asyncio.CancelledError:
                result.status = "cancelled"
                raise
            except Exception as exc:
                if not isinstance(exc, StepFailed | NotSupported | OSError):
                    log.exception("step %d of rule %s crashed", index + 1, rule.id)
                result.status, result.detail = "failed", str(exc) or type(exc).__name__
                failure = failure or f"step {index + 1} ({step.type}) failed: {result.detail}"
                if rule.on_error == "stop":
                    break
            finally:
                result.finished_at = self._clock.now()
                self._set_state(run, "running", None)
        return failure

    async def _do(self, step: Action, rule: Rule, tz: tzinfo, run: Run) -> Outcome:
        match step:
            case PowerStep():
                return await self._power(step, rule, run)
            case RunStep():
                return await self._command(step)
            case OpenStep():
                await self._backend.open(step.target)
                return "ok", None
            case CloseAppStep():
                count = await self._processes.close(step.name, step.timeout)
                return "ok", f"closed {count} process(es)" if count else "not running"
            case NotifyStep():
                return await self._notify(step)
            case WaitStep():
                self._set_state(run, "waiting", None)
                await self._clock.sleep(step.duration.total_seconds())
                return "ok", None
            case WaitUntilStep():
                return await self._wait_until(step, tz, run)
            case SetWakeStep():
                return await self._set_wake(step)
        raise StepFailed(f"unknown action {step.type!r}")

    # ── Power and countdown ───────────────────────────────────────────────────

    async def _power(self, step: PowerStep, rule: Rule, run: Run) -> Outcome:
        if self._power_lock.locked():
            self._set_state(run, "waiting", "another power action is in progress")
        async with self._power_lock:
            await self._countdown(step, rule, run)
            if self._dry_run or rule.dry_run:
                log.warning("dry run: %s (%s) not executed", step.action, step.mode)
                return "dry_run", f"dry run: {step.action} ({step.mode}) not executed"
            await self._backend.power(step.action, step.mode)
            return "ok", None

    async def _countdown(self, step: PowerStep, rule: Rule, run: Run) -> None:
        if rule.warning <= timedelta(0):
            return
        run.deadline = self._clock.now() + rule.warning
        self._set_state(run, "warning", None)
        self._emit(
            "warning_started", run, action=step.action.value, deadline=run.deadline.isoformat()
        )
        prompt = asyncio.create_task(self._countdown_prompt(step, rule, run))
        try:
            while (remaining := (run.deadline - self._clock.now()).total_seconds()) > 0:
                self._emit("tick", run, remaining=round(remaining))
                await self._clock.sleep(min(TICK, remaining))
        finally:
            prompt.cancel()
            run.deadline = None
        self._set_state(run, "running", None)

    async def _countdown_prompt(self, step: PowerStep, rule: Rule, run: Run) -> None:
        """Desktop notification with Cancel / Postpone buttons during the countdown."""
        body = _("{rule}: {action} in {seconds} s").format(
            rule=rule.name,
            action=power_action_label(step.action),
            seconds=round(rule.warning.total_seconds()),
        )
        buttons = {"cancel": _("Cancel"), "postpone": _("Postpone 10 min")}
        try:
            choice = await self._backend.notify("KSE", body, buttons)
        except NotSupported:
            return
        except Exception:
            log.exception("countdown notification failed")
            return
        if choice == "cancel":
            self.cancel(run.id)
        elif choice == "postpone":
            self.postpone(run.id)

    # ── Other actions ─────────────────────────────────────────────────────────

    async def _notify(self, step: NotifyStep) -> Outcome:
        try:
            await self._backend.notify(step.title, step.body)
        except NotSupported as exc:  # best effort: a server may have no desktop
            return "skipped", str(exc)
        return "ok", None

    async def _wait_until(self, step: WaitUntilStep, tz: tzinfo, run: Run) -> Outcome:
        deadline = None if step.timeout is None else self._clock.now() + step.timeout
        self._set_state(run, "waiting", f"waiting until {describe(step.condition)}")
        while await self._evaluator.evaluate(step.condition, tz) is not True:
            now = self._clock.now()
            if deadline is not None and now >= deadline:
                raise StepFailed(f"condition not met within {format_duration(step.timeout)}")
            delay = POLL if deadline is None else min(POLL, (deadline - now).total_seconds())
            await self._clock.sleep(delay)
        return "ok", None

    async def _set_wake(self, step: SetWakeStep) -> Outcome:
        if self._request_wake is None:
            raise NotSupported(
                "set_wake", "wake-up scheduling arrives with the WakePlanner (roadmap M5)"
            )
        when = step.when or self._clock.now() + (step.after or timedelta(0))
        await self._request_wake(when.astimezone(UTC))
        return "ok", when.astimezone(UTC).isoformat()

    async def _command(self, step: RunStep) -> Outcome:
        env = {**os.environ, **step.env} if step.env else None
        output = asyncio.subprocess.PIPE if step.wait else asyncio.subprocess.DEVNULL
        options: dict[str, Any] = {
            "cwd": step.cwd,
            "env": env,
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": output,
            "stderr": asyncio.subprocess.STDOUT,
        }
        if step.shell:
            process = await asyncio.create_subprocess_shell(step.cmd[0], **options)
        else:
            process = await asyncio.create_subprocess_exec(*step.cmd, **options)
        if not step.wait:
            self._reap(process)
            return "ok", f"started in the background (pid {process.pid})"
        reader = asyncio.create_task(_read_tail(process.stdout))
        try:
            finished = await self._within(process.wait(), step.timeout)
        except asyncio.CancelledError:
            reader.cancel()
            await _stop(process)
            raise
        if not finished:
            reader.cancel()
            await _stop(process)
            raise StepFailed(f"timed out after {format_duration(step.timeout)}")
        tail = await reader
        if process.returncode != 0:
            raise StepFailed(f"exit code {process.returncode}" + (f": {tail}" if tail else ""))
        return "ok", tail or None

    async def _within(self, awaitable: Awaitable[Any], limit: timedelta | None) -> bool:
        """Await with a time limit measured on the engine's clock; False if it ran out."""
        work = asyncio.ensure_future(awaitable)
        if limit is None:
            await work
            return True
        timer = asyncio.ensure_future(self._clock.sleep(limit.total_seconds()))
        try:
            await asyncio.wait({work, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            timer.cancel()
            if not work.done():
                work.cancel()
        if work.done() and not work.cancelled():
            work.result()
            return True
        return False

    def _reap(self, process: asyncio.subprocess.Process) -> None:
        task = asyncio.create_task(process.wait())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # ── Bookkeeping ───────────────────────────────────────────────────────────

    def _new_run(
        self, rule: Rule, cause: RunCause, scheduled_for: datetime | None, missed: bool
    ) -> Run:
        return Run(
            rule_id=rule.id,
            rule_name=rule.name,
            cause=cause,
            scheduled_for=scheduled_for,
            missed=missed,
            dry_run=self._dry_run or rule.dry_run,
            started_at=self._clock.now(),
        )

    def _finish(self, run: Run, state: RunState, reason: str | None) -> None:
        run.state, run.reason = state, reason
        run.finished_at = self._clock.now()
        run.deadline = None
        self.recent.append(run)
        log.info("run %s of rule %s: %s (%s)", run.id, run.rule_id, state, reason or "-")
        self._emit("run_finished", run, state=state, reason=reason)

    @staticmethod
    def _set_state(run: Run, state: RunState, reason: str | None) -> None:
        run.state, run.reason = state, reason

    def _emit(self, type_: EventType, run: Run, **data: Any) -> None:
        if self._sink is None:
            return
        event = Event(
            type=type_, at=self._clock.now(), rule_id=run.rule_id, run_id=run.id, data=data
        )
        try:
            self._sink(event)
        except Exception:
            log.exception("event listener failed")


async def _read_tail(stream: asyncio.StreamReader | None) -> str:
    """Read a command's output to the end, keeping only its last OUTPUT_TAIL characters."""
    if stream is None:
        return ""
    tail = b""
    while chunk := await stream.read(65536):
        tail = (tail + chunk)[-OUTPUT_TAIL * 4 :]
    return tail.decode(errors="replace").strip()[-OUTPUT_TAIL:]


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Ask a command to stop; kill it if it is still running after TERMINATE_GRACE."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), TERMINATE_GRACE)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
