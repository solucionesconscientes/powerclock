"""Rule model: the single source of truth for rules.json, the local API and the JSON Schema.

A rule is a trigger + conditions + guards + a sequence of actions + options
(docs/ARCHITECTURE.md §4). Every object rejects unknown fields, so a typo in a
hand-edited rules.json is reported instead of being silently ignored.
"""

import re
from datetime import date, time, timedelta
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

from powerclock.platform.base import (
    LogInMode,
    MediaCommand,
    PowerAction,
    PowerMode,
    PowerProfile,
    StopSignal,
    WindowPlacement,
)

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


class WifiSsid(_Tagged):
    """Connected to the Wi-Fi network `ssid` (as a trigger: when it connects)."""

    type: Literal["wifi_ssid"] = "wifi_ssid"
    ssid: str = Field(min_length=1)


class Active(_Tagged):
    """The computer has been in use for `for` without a break of `pause` (no input): time
    for a rest."""

    type: Literal["active"] = "active"
    for_: PositiveDuration = Field(alias="for")
    pause: PositiveDuration = timedelta(minutes=5)


class UsedToday(_Tagged):
    """The computer has been used for `for` in total today (in the rule's time zone)."""

    type: Literal["used_today"] = "used_today"
    for_: PositiveDuration = Field(alias="for")


class FileExists(_Tagged):
    """A file exists, or a folder holds a file matching `pattern` ("*.pdf")."""

    type: Literal["file"] = "file"
    path: str = Field(min_length=1)
    pattern: str | None = None


class Device(_Tagged):
    """A device whose name contains `name` is connected: a USB stick or disk (its product
    or its label), Bluetooth headphones…"""

    type: Literal["device"] = "device"
    name: str = Field(min_length=1)


class Temperature(_Tagged):
    """The hottest temperature sensor (or the one whose name contains `sensor`) is above
    `above` °C."""

    type: Literal["temperature"] = "temperature"
    above: float = Field(gt=0, le=150)
    sensor: str | None = None


class DesktopSession(_Tagged):
    """A desktop session is up, so applications can be opened in it (as a trigger: when
    it starts, e.g. after logging in)."""

    type: Literal["desktop_session"] = "desktop_session"


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


class SunTrigger(_Tagged):
    """At sunrise or sunset (plus `offset_minutes`, which may be negative), computed for
    `latitude`/`longitude` or, without them, for the time zone's city."""

    type: Literal["sun"] = "sun"
    event: Literal["sunrise", "sunset"] = "sunset"
    offset_minutes: int = Field(default=0, ge=-720, le=720)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _both_or_none(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("give both latitude and longitude, or neither")
        return self


class CalendarTrigger(_Tagged):
    """`before` each event of a calendar (an .ics address or file) whose title contains
    `match` (every event without it)."""

    type: Literal["calendar"] = "calendar"
    source: str = Field(min_length=1)
    match: str | None = None
    before: Duration = timedelta(0)


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
    """When a process ends, matched by name or by PID (exactly one).

    Only a process seen running counts: if it is not running yet, the rule waits for it
    to start. With a name, it fires once no process of that name is left.
    """

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
    | SunTrigger
    | CalendarTrigger
    | Idle
    | ProcessExitTrigger
    | CpuBelow
    | NetBelow
    | BatteryLevel
    | PowerSource
    | DesktopSession
    | WifiSsid
    | Active
    | UsedToday
    | FileExists
    | Device
    | Temperature
    | StartupTrigger
    | ManualTrigger,
    Field(discriminator="type"),
]
TIME_TRIGGERS = (AtTrigger, CountdownTrigger, CronTrigger, SunTrigger, CalendarTrigger)


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


class Holiday(_Tagged):
    """Today is a public holiday (Spain's national ones) or one of `extra` (regional and
    local holidays, days off)."""

    type: Literal["holiday"] = "holiday"
    country: Literal["ES"] = "ES"
    extra: list[date] = Field(default_factory=list)


class TariffPeriod(_Tagged):
    """The electricity tariff chosen in the settings is in this period now (unknown when
    no tariff is set: only for contracts with time-of-use prices)."""

    type: Literal["tariff_period"] = "tariff_period"
    period: Literal["valley", "flat", "peak"] = "valley"


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
    | Annotated[DesktopSession, Tag("desktop_session")]
    | Annotated[Holiday, Tag("holiday")]
    | Annotated[TariffPeriod, Tag("tariff_period")]
    | Annotated[Active, Tag("active")]
    | Annotated[UsedToday, Tag("used_today")]
    | Annotated[FileExists, Tag("file")]
    | Annotated[Device, Tag("device")]
    | Annotated[Temperature, Tag("temperature")]
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
    """Run a program. `cmd` is an argument list; with `shell: true`, a single command line.

    `{date}`, `{time}`, `{datetime}`, `{weekday}` and `{rule}` in `cmd`, `cwd` and `env` are
    replaced when it runs (see engine/variables.py)."""

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


class LaunchStep(_Tagged):
    """Open an installed application in the desktop session.

    `app` is its desktop entry id ("org.kde.okular", "one.ablaze.floorp"): the command comes
    from the entry, so Flatpak and Snap apps work too. `args` go to the app (files, web
    addresses, options) and accept the same {date}… variables as `run`. `recipe` records
    which recipe filled them. `stop_signal` is what closing it (close_app with `app`)
    sends."""

    type: Literal["launch"] = "launch"
    app: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    recipe: str | None = None
    window: WindowPlacement | None = None
    keep_open: bool = False
    stop_signal: StopSignal = "TERM"
    wait_desktop: Duration = timedelta(minutes=2)

    @field_validator("app")
    @classmethod
    def _entry_id(cls, app: str) -> str:
        return app.strip().removesuffix(".desktop")


class CloseAppStep(_Tagged):
    """Ask a program to quit and kill it if it is still running after `timeout`: by process
    `name` (sending `signal`), or the instances of an `app` that PowerClock opened."""

    type: Literal["close_app"] = "close_app"
    name: str | None = Field(default=None, min_length=1)
    app: str | None = Field(default=None, min_length=1)
    signal: StopSignal = "TERM"
    timeout: PositiveDuration = timedelta(seconds=30)

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        _exactly_one(self, "name", "app")
        return self


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


OnOff = Literal["on", "off"]


class MediaStep(_Tagged):
    """Control a media player (MPRIS): play, pause, next… or `open` an address in it
    (a file, a radio stream, a spotify: link). `player` is part of its name ("vlc"); without
    it, the one playing (or the first one open)."""

    type: Literal["media"] = "media"
    command: MediaCommand = "play"
    player: str | None = None
    uri: str | None = None

    @model_validator(mode="after")
    def _uri_with_open(self) -> Self:
        if (self.command == "open") != (self.uri is not None):
            raise ValueError("uri goes with command: open (and only with it)")
        return self


class VolumeStep(_Tagged):
    """The computer's volume: a `level` (0 to 150 %), reached little by little over `fade`,
    and/or mute on or off."""

    type: Literal["volume"] = "volume"
    level: int | None = Field(default=None, ge=0, le=150)
    mute: OnOff | None = None
    fade: Duration = timedelta(0)

    @model_validator(mode="after")
    def _something(self) -> Self:
        if self.level is None and self.mute is None:
            raise ValueError("set a level, mute, or both")
        if self.fade > timedelta(0) and self.level is None:
            raise ValueError("fade needs a level")
        return self


class SoundStep(_Tagged):
    """Play a sound (a file, or a sound of the theme by name: "alarm-clock-elapsed"), or
    `say` a text aloud (in `language`: "es", "en"…)."""

    type: Literal["sound"] = "sound"
    file: str | None = None
    say: str | None = None
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")

    @model_validator(mode="after")
    def _one_sound(self) -> Self:
        _exactly_one(self, "file", "say")
        return self


class DesktopStep(_Tagged):
    """Desktop settings: colour `theme` ("light", "dark" or a scheme's name), `wallpaper`,
    screen `brightness` (%) and `power_profile`."""

    type: Literal["desktop"] = "desktop"
    theme: str | None = None
    wallpaper: str | None = None
    brightness: int | None = Field(default=None, ge=1, le=100)
    power_profile: PowerProfile | None = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if all(
            v is None for v in (self.theme, self.wallpaper, self.brightness, self.power_profile)
        ):
            raise ValueError("set at least one of: theme, wallpaper, brightness, power_profile")
        return self


class NetworkStep(_Tagged):
    """Bring a saved connection up (`connect`: a VPN…) or down (`disconnect`), or turn
    Wi-Fi on or off."""

    type: Literal["network"] = "network"
    connect: str | None = None
    disconnect: str | None = None
    wifi: OnOff | None = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if self.connect is None and self.disconnect is None and self.wifi is None:
            raise ValueError("set at least one of: connect, disconnect, wifi")
        return self


class InhibitStep(_Tagged):
    """For `duration` (without holding up the next steps): keep the screen on, hold the
    notifications (Do not disturb) and/or keep the computer from sleeping."""

    type: Literal["inhibit"] = "inhibit"
    screen_on: bool = True
    do_not_disturb: bool = False
    no_sleep: bool = False
    duration: PositiveDuration

    @model_validator(mode="after")
    def _something(self) -> Self:
        if not (self.screen_on or self.do_not_disturb or self.no_sleep):
            raise ValueError("choose at least one of: screen_on, do_not_disturb, no_sleep")
        return self


class ScreenshotStep(_Tagged):
    """Save a picture of the screen (proof in the history). `file` takes the {date}…
    variables."""

    type: Literal["screenshot"] = "screenshot"
    file: str = "{data}/screenshots/{rule}-{datetime}.png"


class PushStep(_Tagged):
    """Send a message out of the computer: to your phone with ntfy (`url`: the topic's
    address, https://ntfy.sh/…) or Telegram (a bot: its token is the secret
    `telegram_token`, `chat` the chat's id), or to any `webhook` (a JSON POST to `url`).
    `title` and `message` take the {date}… variables, and {error} in "if it fails" steps."""

    type: Literal["push"] = "push"
    service: Literal["ntfy", "telegram", "webhook"] = "ntfy"
    url: str | None = None
    chat: str | None = None
    title: str = "PowerClock"
    message: str = ""
    priority: Literal["low", "default", "high", "urgent"] = "default"

    @model_validator(mode="after")
    def _where(self) -> Self:
        if self.service in ("ntfy", "webhook") and not (self.url or "").startswith(
            ("https://", "http://")
        ):
            raise ValueError(f"{self.service} needs the url to send to (https://…)")
        if self.service == "telegram" and not self.chat:
            raise ValueError("telegram needs the chat to send to")
        return self


class AskStep(_Tagged):
    """A notification with buttons that waits for an answer: the rule goes on with the
    answer `go_on` (any answer if it is not set) and stops with any other. Without an answer
    it is shown again every `repeat` (a reminder), and after `timeout` it gives up."""

    type: Literal["ask"] = "ask"
    title: str = Field(min_length=1)
    body: str = ""
    buttons: list[str] = Field(min_length=1, max_length=3)
    go_on: str | None = None
    repeat: PositiveDuration | None = None
    timeout: PositiveDuration = timedelta(hours=1)
    if_no_answer: Literal["stop", "continue"] = "stop"

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.go_on is not None and self.go_on not in self.buttons:
            raise ValueError("go_on must be one of the buttons")
        return self


class SetWakeStep(_Tagged):
    """Program a wake-up at an instant (`when`) or after a delay (`after`)."""

    type: Literal["set_wake"] = "set_wake"
    when: AwareDatetime | None = None
    after: PositiveDuration | None = None

    @model_validator(mode="after")
    def _one_moment(self) -> Self:
        _exactly_one(self, "when", "after")
        return self


MAC_PATTERN = r"^(([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|[0-9A-Fa-f]{12})$"


class WakeLanStep(_Tagged):
    """Turn on another computer on the local network (Wake-on-LAN): its network card must
    have it enabled in the BIOS/UEFI and the system (`ethtool -s eth0 wol g`)."""

    type: Literal["wake_lan"] = "wake_lan"
    mac: str = Field(pattern=MAC_PATTERN)
    broadcast: str = Field(default="255.255.255.255", min_length=1)
    port: int = Field(default=9, ge=1, le=65535)


Action = Annotated[
    PowerStep
    | RunStep
    | LaunchStep
    | MediaStep
    | VolumeStep
    | SoundStep
    | DesktopStep
    | NetworkStep
    | InhibitStep
    | ScreenshotStep
    | PushStep
    | AskStep
    | OpenStep
    | CloseAppStep
    | NotifyStep
    | WaitStep
    | WaitUntilStep
    | SetWakeStep
    | WakeLanStep,
    Field(discriminator="type"),
]


# ── Rule ──────────────────────────────────────────────────────────────────────


class Rule(_Model):
    id: RuleId
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    trigger: Trigger
    wake: bool = False
    log_in: LogInMode | None = None  # with wake: log in once if it powered the computer on
    conditions: Predicate | None = None
    guards: Guards | None = None
    actions: list[Action] = Field(min_length=1)
    on_failure: list[Action] = Field(default_factory=list)  # run when a step fails ({error})
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
        if self.log_in is not None and not self.wake:
            raise ValueError("log_in needs wake: true (it logs in after turning the computer on)")
        for steps in (self.actions, self.on_failure):
            for step in steps[:-1]:
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


def model_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema of one part of a rule, with defaults written as in rules.json ("1m")."""
    return model.model_json_schema(schema_generator=_RuleSchemaGenerator)


def rule_json_schema() -> dict[str, Any]:
    """JSON Schema of a rule (served at /schema/rule for the GUI and the AI assistant)."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **model_json_schema(Rule)}
