"""Records of what the engine did and why: runs, their steps and the events it emits."""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunState = Literal[
    "running", "waiting", "postponed", "warning", "done", "failed", "cancelled", "skipped"
]
FINAL_STATES = frozenset({"done", "failed", "cancelled", "skipped"})
StepStatus = Literal["running", "ok", "dry_run", "skipped", "failed", "cancelled"]
RunCause = Literal["schedule", "trigger", "manual"]  # trigger: a state or startup trigger
EventType = Literal[
    "run_started",
    "warning_started",
    "tick",
    "postponed",
    "cancelled",
    "run_finished",
    "rule_changed",
    "wake_changed",
]


class StepResult(BaseModel):
    index: int
    type: str
    status: StepStatus = "running"
    started_at: datetime
    finished_at: datetime | None = None
    detail: str | None = None


class Run(BaseModel):
    """One firing of a rule, from its conditions to its last action."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    rule_id: str
    rule_name: str
    cause: RunCause
    scheduled_for: datetime | None = None
    missed: bool = False  # fired late: the machine was off/asleep at `scheduled_for`
    dry_run: bool = False
    state: RunState = "running"
    reason: str | None = None  # why it is waiting/postponed, or why it ended that way
    deadline: datetime | None = None  # end of the power countdown in progress
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[StepResult] = Field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.state in FINAL_STATES


class Event(BaseModel):
    """Pushed to clients over the /events WebSocket (docs/ARCHITECTURE.md §8)."""

    type: EventType
    at: datetime
    rule_id: str | None = None
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


EventSink = Callable[[Event], None]
