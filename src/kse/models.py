"""Rule model: the single source of truth for rules.json, the local API and the JSON Schema.

A rule is a trigger + conditions + guards + a sequence of actions + options
(docs/ARCHITECTURE.md §4). Every object rejects unknown fields, so a typo in a
hand-edited rules.json is reported instead of being silently ignored.
"""

import re
from datetime import time, timedelta
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    PlainValidator,
    Tag,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic.json_schema import GenerateJsonSchema

from kse.platform.base import PowerAction, PowerMode

# ── Durations ─────────────────────────────────────────────────────────────────

DURATION_PATTERN = r"^(?=\d)(?:\d+d)?(?:\d+h)?(?:\d+m)?(?:\d+s)?$"
_DURATION_RE = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
_UNITS = (("d", 86_400), ("h", 3_600), ("m", 60), ("s", 1))


def parse_duration(text: str) -> timedelta:
    """Parse "30s", "5m", "2h", "1d" or a compound in that order, such as "1h30m"."""
    match = _DURATION_RE.fullmatch(text)
    if not text or match is None:
        raise ValueError(f"invalid duration {text!r}: use e.g. '30s', '5m', '2h', '1d' or '1h30m'")
    seconds = sum(
        int(amount) * unit
        for amount, (_, unit) in zip(match.groups(), _UNITS, strict=True)
        if amount
    )
    try:
        return timedelta(seconds=seconds)
    except OverflowError:
        raise ValueError(f"duration {text!r} is too large") from None


def format_duration(value: timedelta) -> str:
    """Inverse of parse_duration: timedelta(minutes=90) -> "1h30m"."""
    seconds = _whole_seconds(value)
    if seconds == 0:
        return "0s"
    parts = []
    for suffix, unit in _UNITS:
        amount, seconds = divmod(seconds, unit)
        if amount:
            parts.append(f"{amount}{suffix}")
    return "".join(parts)


def _whole_seconds(value: timedelta) -> int:
    if value < timedelta(0):
        raise ValueError("durations cannot be negative")
    if value.microseconds:
        raise ValueError("durations have a resolution of one second")
    return value.days * 86_400 + value.seconds


def _validate_duration(value: Any) -> timedelta:
    if isinstance(value, timedelta):
        _whole_seconds(value)
        return value
    if isinstance(value, str):
        return parse_duration(value)
    raise ValueError("a duration must be a string such as '30s', '5m', '2h', '1d' or '1h30m'")


def _positive(value: timedelta) -> timedelta:
    if value <= timedelta(0):
        raise ValueError("duration must be greater than zero")
    return value


Duration = Annotated[
    timedelta,
    PlainValidator(_validate_duration),
    PlainSerializer(format_duration, return_type=str),
    WithJsonSchema(
        {"type": "string", "pattern": DURATION_PATTERN, "examples": ["30s", "5m", "1h30m"]}
    ),
]
PositiveDuration = Annotated[Duration, AfterValidator(_positive)]


# ── Shared helpers ────────────────────────────────────────────────────────────


def _check_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(
            f"unknown time zone {name!r}: use an IANA name such as 'Europe/Madrid'"
        ) from None
    return name


TimeZoneName = Annotated[str, AfterValidator(_check_timezone)]
RuleId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
DayName = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _exactly_one(model: BaseModel, *fields: str) -> None:
    given = [name for name in fields if getattr(model, name) is not None]
    if len(given) != 1:
        raise ValueError(f"set exactly one of: {', '.join(fields)}")


def _require_type(schema: dict[str, Any]) -> None:
    # `type` has a default for convenience in Python, but JSON documents must carry it.
    required = schema.setdefault("required", [])
    if "type" not in required:
        required.insert(0, "type")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_by_name=True, serialize_by_alias=True)


class _Tagged(_Model):
    """Object told apart from its siblings by its `type` field."""

    model_config = ConfigDict(json_schema_extra=_require_type)


# ── Sensor states: usable both as triggers and as predicates ─────────────────


class Idle(_Tagged):
    """No user input for at least `for`."""

    type: Literal["idle"] = "idle"
    for_: PositiveDuration = Field(alias="for")


class CpuBelow(_Tagged):
    """Average CPU usage below `percent` for `for`."""

    type: Literal["cpu_below"] = "cpu_below"
    percent: float = Field(gt=0, le=100)
    for_: PositiveDuration = Field(alias="for")


class NetBelow(_Tagged):
    """Network throughput below `kbps` (kilobits per second) for `for`."""

    type: Literal["net_below"] = "net_below"
    kbps: float = Field(gt=0)
    for_: PositiveDuration = Field(alias="for")
    direction: Literal["down", "up", "both"] = "both"
    interface: str | None = None  # None: every interface except loopback


class BatteryLevel(_Tagged):
    """Battery charge below or above a percentage (exactly one of them)."""

    type: Literal["battery"] = "battery"
    below: int | None = Field(default=None, ge=1, le=100)
    above: int | None = Field(default=None, ge=0, le=99)
    for_: Duration = Field(default=timedelta(0), alias="for")

    @model_validator(mode="after")
    def _one_threshold(self) -> Self:
        _exactly_one(self, "below", "above")
        return self


class PowerSource(_Tagged):
    """Running on AC or on battery."""

    type: Literal["power_source"] = "power_source"
    is_: Literal["ac", "battery"] = Field(alias="is")
    for_: Duration = Field(default=timedelta(0), alias="for")


# ── Triggers ──────────────────────────────────────────────────────────────────


class AtTrigger(_Tagged):
    """Once, at an absolute instant with time zone ("2026-09-24T07:30:00+02:00")."""

    type: Literal["at"] = "at"
    when: AwareDatetime


class CountdownTrigger(_Tagged):
    """`duration` after the rule is armed.

    The daemon fills `armed_at` when the rule is enabled, so the countdown survives restarts.
    """

    type: Literal["countdown"] = "countdown"
    duration: PositiveDuration
    armed_at: AwareDatetime | None = None


class CronTrigger(_Tagged):
    """Recurring: a 5-field cron expression (or @daily, @hourly…) in the rule's time zone."""

    type: Literal["cron"] = "cron"
    expr: str

    @field_validator("expr")
    @classmethod
    def _valid_cron(cls, expr: str) -> str:
        fields = expr.split()
        well_formed = len(fields) == 5 or (len(fields) == 1 and expr.startswith("@"))
        if not (well_formed and croniter.is_valid(expr)):
            raise ValueError(
                f"invalid cron expression {expr!r}: use 5 fields "
                "'minute hour day month weekday' or @hourly, @daily, @weekly…"
            )
        return expr


class ProcessExitTrigger(_Tagged):
    """When a process ends, matched by name or by PID (exactly one)."""

    type: Literal["process_exit"] = "process_exit"
    name: str | None = Field(default=None, min_length=1)
    pid: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        _exactly_one(self, "name", "pid")
        return self


class StartupTrigger(_Tagged):
    """When the daemon starts and/or after the machine resumes from sleep."""

    type: Literal["startup"] = "startup"
    on: list[Literal["daemon_start", "resume"]] = Field(
        default_factory=lambda: ["daemon_start", "resume"], min_length=1
    )
    delay: Duration = timedelta(0)


class ManualTrigger(_Tagged):
    """Only when run explicitly (API, CLI or GUI)."""

    type: Literal["manual"] = "manual"


Trigger = Annotated[
    AtTrigger
    | CountdownTrigger
    | CronTrigger
    | Idle
    | ProcessExitTrigger
    | CpuBelow
    | NetBelow
    | BatteryLevel
    | PowerSource
    | StartupTrigger
    | ManualTrigger,
    Field(discriminator="type"),
]
TIME_TRIGGERS = (AtTrigger, CountdownTrigger, CronTrigger)


# ── Predicates (conditions, guards, wait_until) ──────────────────────────────


class ProcessRunning(_Tagged):
    type: Literal["process_running"] = "process_running"
    name: str = Field(min_length=1)


class MediaPlaying(_Tagged):
    """Some media player is playing (MPRIS on Linux)."""

    type: Literal["media_playing"] = "media_playing"


class SshSession(_Tagged):
    """Someone is logged in over SSH."""

    type: Literal["ssh_session"] = "ssh_session"


class TimeWindow(_Tagged):
    """Time of day between `start` and `end` in the rule's time zone.

    The window crosses midnight when start > end (e.g. 22:00 → 07:00).
    """

    type: Literal["time_window"] = "time_window"
    start: time
    end: time

    @field_validator("start", "end")
    @classmethod
    def _plain_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("use a plain time of day such as '22:30'; the rule sets the time zone")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class Weekday(_Tagged):
    """Today is one of `days`, in the rule's time zone."""

    type: Literal["weekday"] = "weekday"
    days: list[DayName] = Field(min_length=1)


class WifiSsid(_Tagged):
    type: Literal["wifi_ssid"] = "wifi_ssid"
    ssid: str = Field(min_length=1)


class AllOf(_Model):
    """True when every predicate is true."""

    all: list["Predicate"] = Field(min_length=1)


class AnyOf(_Model):
    """True when at least one predicate is true."""

    any: list["Predicate"] = Field(min_length=1)


class NotOf(_Model):
    """Negates a predicate."""

    not_: "Predicate" = Field(alias="not")


def _predicate_tag(value: Any) -> str | None:
    # Leaves carry a `type`; logic nodes are recognised by their single key.
    if isinstance(value, dict):
        kind = value.get("type")
        if isinstance(kind, str):
            return kind
        keys = [key for key in ("all", "any", "not") if key in value]
        return keys[0] if len(keys) == 1 else None
    if isinstance(value, AllOf):
        return "all"
    if isinstance(value, AnyOf):
        return "any"
    if isinstance(value, NotOf):
        return "not"
    kind = getattr(value, "type", None)
    return kind if isinstance(kind, str) else None


Predicate = Annotated[
    Annotated[ProcessRunning, Tag("process_running")]
    | Annotated[PowerSource, Tag("power_source")]
    | Annotated[BatteryLevel, Tag("battery")]
    | Annotated[Idle, Tag("idle")]
    | Annotated[CpuBelow, Tag("cpu_below")]
    | Annotated[NetBelow, Tag("net_below")]
    | Annotated[MediaPlaying, Tag("media_playing")]
    | Annotated[SshSession, Tag("ssh_session")]
    | Annotated[TimeWindow, Tag("time_window")]
    | Annotated[Weekday, Tag("weekday")]
    | Annotated[WifiSsid, Tag("wifi_ssid")]
    | Annotated[AllOf, Tag("all")]
    | Annotated[AnyOf, Tag("any")]
    | Annotated[NotOf, Tag("not")],
    Discriminator(
        _predicate_tag,
        custom_error_type="invalid_predicate",
        custom_error_message="a predicate needs a 'type' or exactly one of 'all', 'any', 'not'",
    ),
]

for _logic_node in (AllOf, AnyOf, NotOf):
    _logic_node.model_rebuild()


class Guards(_Model):
    """If any predicate is true, the run is postponed.

    It is checked again every `retry` and skipped once `max_wait` has passed.
    """

    any: list[Predicate] = Field(min_length=1)
    retry: PositiveDuration = timedelta(minutes=5)
    max_wait: Duration = timedelta(hours=2)


# ── Actions ───────────────────────────────────────────────────────────────────


class PowerStep(_Tagged):
    type: Literal["power"] = "power"
    action: PowerAction
    mode: PowerMode = PowerMode.GRACEFUL


# These end the user's session: nothing after them could run.
TERMINAL_POWER_ACTIONS = frozenset({PowerAction.SHUTDOWN, PowerAction.REBOOT, PowerAction.LOGOUT})


class RunStep(_Tagged):
    """Run a program. `cmd` is an argument list; with `shell: true`, a single command line."""

    type: Literal["run"] = "run"
    cmd: list[str] = Field(min_length=1)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    shell: bool = False
    timeout: PositiveDuration | None = None
    wait: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.cmd[0]:
            raise ValueError("cmd[0] (the program) cannot be empty")
        if self.shell and len(self.cmd) != 1:
            raise ValueError("with shell: true, cmd must be a single command line")
        if self.timeout is not None and not self.wait:
            raise ValueError("timeout only applies with wait: true")
        return self


class OpenStep(_Tagged):
    """Open a file or URL with the default application."""

    type: Literal["open"] = "open"
    target: str = Field(min_length=1)


class CloseAppStep(_Tagged):
    """Ask a program to quit and kill it if it is still running after `timeout`."""

    type: Literal["close_app"] = "close_app"
    name: str = Field(min_length=1)
    timeout: PositiveDuration = timedelta(seconds=30)


class NotifyStep(_Tagged):
    type: Literal["notify"] = "notify"
    title: str = Field(min_length=1)
    body: str = ""


class WaitStep(_Tagged):
    type: Literal["wait"] = "wait"
    duration: PositiveDuration


class WaitUntilStep(_Tagged):
    """Wait until `condition` is true; fails after `timeout` (None: no limit)."""

    type: Literal["wait_until"] = "wait_until"
    condition: Predicate
    timeout: PositiveDuration | None = None


class SetWakeStep(_Tagged):
    """Program a wake-up at an instant (`when`) or after a delay (`after`)."""

    type: Literal["set_wake"] = "set_wake"
    when: AwareDatetime | None = None
    after: PositiveDuration | None = None

    @model_validator(mode="after")
    def _one_moment(self) -> Self:
        _exactly_one(self, "when", "after")
        return self


Action = Annotated[
    PowerStep
    | RunStep
    | OpenStep
    | CloseAppStep
    | NotifyStep
    | WaitStep
    | WaitUntilStep
    | SetWakeStep,
    Field(discriminator="type"),
]


# ── Rule ──────────────────────────────────────────────────────────────────────


class Rule(_Model):
    id: RuleId
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    trigger: Trigger
    wake: bool = False
    conditions: Predicate | None = None
    guards: Guards | None = None
    actions: list[Action] = Field(min_length=1)
    warning: Duration = timedelta(seconds=60)
    on_missed: Literal["skip", "run_once"] = "skip"
    on_error: Literal["stop", "continue"] = "stop"
    one_shot: bool = False
    dry_run: bool = False
    timezone: TimeZoneName | None = None  # None: the system's time zone

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.wake and not isinstance(self.trigger, TIME_TRIGGERS):
            raise ValueError("wake: true needs a time trigger (at, countdown or cron)")
        for step in self.actions[:-1]:
            if isinstance(step, PowerStep) and step.action in TERMINAL_POWER_ACTIONS:
                raise ValueError(
                    f"power action {step.action.value!r} ends the session, "
                    "so it must be the last action"
                )
        return self


class _RuleSchemaGenerator(GenerateJsonSchema):
    def encode_default(self, dft: Any) -> Any:
        # Pydantic encodes timedelta defaults as ISO 8601 ("PT1M"); rules write "1m".
        if isinstance(dft, timedelta):
            return format_duration(dft)
        return super().encode_default(dft)


def rule_json_schema() -> dict[str, Any]:
    """JSON Schema of a rule (served at /schema/rule for the GUI and the AI assistant)."""
    schema = Rule.model_json_schema(schema_generator=_RuleSchemaGenerator)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
