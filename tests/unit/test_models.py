import json
from datetime import timedelta
from typing import Annotated, Any, get_args, get_origin

import pytest
from pydantic import ValidationError

from powerclock.models import (
    Action,
    AllOf,
    AnyOf,
    Idle,
    NotOf,
    PowerStep,
    Predicate,
    Rule,
    SshSession,
    Trigger,
)
from powerclock.platform.base import PowerAction, PowerMode

# One valid sample per type. test_every_type_has_a_sample fails when a new type is
# added to a union without a sample here.
TRIGGERS: dict[str, dict[str, Any]] = {
    "at": {"type": "at", "when": "2026-09-24T07:30:00+02:00"},
    "countdown": {"type": "countdown", "duration": "30m"},
    "cron": {"type": "cron", "expr": "0 3 * * *"},
    "idle": {"type": "idle", "for": "20m"},
    "process_exit": {"type": "process_exit", "name": "ffmpeg"},
    "cpu_below": {"type": "cpu_below", "percent": 10, "for": "5m"},
    "net_below": {"type": "net_below", "kbps": 50, "for": "5m", "direction": "down"},
    "battery": {"type": "battery", "below": 15},
    "power_source": {"type": "power_source", "is": "battery"},
    "desktop_session": {"type": "desktop_session"},
    "sun": {"type": "sun", "event": "sunset", "offset_minutes": -30},
    "calendar": {"type": "calendar", "source": "https://example.org/cal.ics", "before": "5m"},
    "wifi_ssid": {"type": "wifi_ssid", "ssid": "Casa"},
    "active": {"type": "active", "for": "50m"},
    "used_today": {"type": "used_today", "for": "2h"},
    "file": {"type": "file", "path": "~/Descargas", "pattern": "*.pdf"},
    "device": {"type": "device", "name": "COPIAS"},
    "temperature": {"type": "temperature", "above": 85},
    "startup": {"type": "startup", "on": ["resume"], "delay": "30s"},
    "manual": {"type": "manual"},
}

PREDICATES: dict[str, dict[str, Any]] = {
    "process_running": {"type": "process_running", "name": "ffmpeg"},
    "power_source": {"type": "power_source", "is": "ac"},
    "battery": {"type": "battery", "above": 30},
    "idle": {"type": "idle", "for": "10m"},
    "cpu_below": {"type": "cpu_below", "percent": 20, "for": "1m"},
    "net_below": {"type": "net_below", "kbps": 50, "for": "5m", "interface": "wlp2s0"},
    "media_playing": {"type": "media_playing"},
    "ssh_session": {"type": "ssh_session"},
    "time_window": {"type": "time_window", "start": "22:00", "end": "07:00"},
    "weekday": {"type": "weekday", "days": ["sat", "sun"]},
    "wifi_ssid": {"type": "wifi_ssid", "ssid": "Casa"},
    "desktop_session": {"type": "desktop_session"},
    "holiday": {"type": "holiday", "extra": ["2026-05-15"]},
    "tariff_period": {"type": "tariff_period", "period": "valley"},
    "active": {"type": "active", "for": "50m", "pause": "5m"},
    "used_today": {"type": "used_today", "for": "2h"},
    "file": {"type": "file", "path": "/tmp/flag"},
    "device": {"type": "device", "name": "WH-1000XM4"},
    "temperature": {"type": "temperature", "above": 80, "sensor": "coretemp"},
    "all": {"all": [{"type": "media_playing"}, {"type": "ssh_session"}]},
    "any": {"any": [{"type": "media_playing"}]},
    "not": {"not": {"type": "ssh_session"}},
}

ACTIONS: dict[str, dict[str, Any]] = {
    "power": {"type": "power", "action": "suspend"},
    "run": {"type": "run", "cmd": ["echo", "hola"], "timeout": "1m"},
    "launch": {
        "type": "launch",
        "app": "google-chrome",
        "args": ["--kiosk", "https://panel.example.org"],
        "recipe": "chromium.kiosk",
        "window": {"screen": 2, "state": "fullscreen"},
        "keep_open": True,
    },
    "media": {"type": "media", "command": "open", "player": "vlc", "uri": "https://radio.es/live"},
    "volume": {"type": "volume", "level": 40, "mute": "off", "fade": "5m"},
    "sound": {"type": "sound", "say": "Hora de la pastilla", "language": "es"},
    "desktop": {"type": "desktop", "theme": "dark", "brightness": 40, "power_profile": "balanced"},
    "network": {"type": "network", "connect": "VPN Oficina", "wifi": "on"},
    "inhibit": {"type": "inhibit", "do_not_disturb": True, "duration": "1h"},
    "screenshot": {"type": "screenshot", "file": "/tmp/{date}.png"},
    "push": {"type": "push", "url": "https://ntfy.sh/mi-tema", "message": "Copia hecha"},
    "ask": {"type": "ask", "title": "¿Pastilla?", "buttons": ["Hecho"], "repeat": "5m"},
    "open": {"type": "open", "target": "https://example.org"},
    "close_app": {"type": "close_app", "name": "firefox"},
    "notify": {"type": "notify", "title": "PowerClock", "body": "hola"},
    "wait": {"type": "wait", "duration": "10s"},
    "wait_until": {"type": "wait_until", "condition": {"type": "idle", "for": "1m"}},
    "set_wake": {"type": "set_wake", "after": "8h"},
}


def make_rule(**overrides: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "test-rule",
        "name": "Test",
        "trigger": {"type": "manual"},
        "actions": [{"type": "notify", "title": "PowerClock"}],
    }
    rule.update(overrides)
    return rule


def assert_round_trip(rule: Rule) -> None:
    assert Rule.model_validate_json(rule.model_dump_json()) == rule
    assert Rule.model_validate(rule.model_dump(mode="json")) == rule


def union_tags(annotated: Any) -> set[str]:
    tags = set()
    for member in get_args(get_args(annotated)[0]):
        if get_origin(member) is Annotated:
            tags.add(get_args(member)[1].tag)
        else:
            tags.add(member.model_fields["type"].default)
    return tags


def test_every_type_has_a_sample() -> None:
    assert union_tags(Trigger) == set(TRIGGERS)
    assert union_tags(Predicate) == set(PREDICATES)
    assert union_tags(Action) == set(ACTIONS)


@pytest.mark.parametrize("trigger", TRIGGERS.values(), ids=TRIGGERS.keys())
def test_every_trigger_validates_and_round_trips(trigger: dict[str, Any]) -> None:
    rule = Rule.model_validate(make_rule(trigger=trigger))
    assert rule.trigger.type == trigger["type"]
    assert_round_trip(rule)


@pytest.mark.parametrize("predicate", PREDICATES.values(), ids=PREDICATES.keys())
def test_every_predicate_works_as_condition_guard_and_wait(predicate: dict[str, Any]) -> None:
    rule = Rule.model_validate(
        make_rule(
            conditions=predicate,
            guards={"any": [predicate]},
            actions=[{"type": "wait_until", "condition": predicate}],
        )
    )
    assert_round_trip(rule)


@pytest.mark.parametrize("action", ACTIONS.values(), ids=ACTIONS.keys())
def test_every_action_validates_and_round_trips(action: dict[str, Any]) -> None:
    rule = Rule.model_validate(make_rule(actions=[action]))
    assert rule.actions[0].type == action["type"]
    assert_round_trip(rule)


def test_defaults() -> None:
    rule = Rule.model_validate(make_rule(guards={"any": [{"type": "ssh_session"}]}))
    assert rule.enabled is True
    assert rule.wake is False
    assert rule.warning == timedelta(seconds=60)
    assert (rule.on_missed, rule.on_error) == ("skip", "stop")
    assert (rule.one_shot, rule.dry_run, rule.timezone) == (False, False, None)
    assert rule.guards is not None
    assert (rule.guards.retry, rule.guards.max_wait) == (timedelta(minutes=5), timedelta(hours=2))
    power = PowerStep.model_validate({"type": "power", "action": "shutdown"})
    assert power.mode is PowerMode.GRACEFUL


def test_nested_logic_tree() -> None:
    conditions = {
        "all": [
            {"any": [{"type": "power_source", "is": "ac"}, {"type": "battery", "above": 50}]},
            {"not": {"all": [{"type": "ssh_session"}, {"type": "media_playing"}]}},
        ]
    }
    rule = Rule.model_validate(make_rule(conditions=conditions))
    assert isinstance(rule.conditions, AllOf)
    first, second = rule.conditions.all
    assert isinstance(first, AnyOf)
    assert isinstance(second, NotOf)
    assert isinstance(second.not_, AllOf)
    assert_round_trip(rule)


def test_json_uses_public_field_names() -> None:
    rule = Rule.model_validate(
        make_rule(
            trigger={"type": "idle", "for": "20m"},
            conditions={"not": {"type": "power_source", "is": "battery"}},
        )
    )
    dumped = json.loads(rule.model_dump_json())
    assert dumped["trigger"] == {"type": "idle", "for": "20m"}
    assert dumped["conditions"] == {"not": {"type": "power_source", "is": "battery", "for": "0s"}}
    assert dumped["warning"] == "1m"


def test_python_construction_by_field_name() -> None:
    rule = Rule(
        id="py",
        name="Built in Python",
        trigger=Idle(for_=timedelta(minutes=5)),
        conditions=NotOf(not_=SshSession()),
        actions=[PowerStep(action=PowerAction.LOCK)],
    )
    assert rule.model_dump(mode="json")["trigger"] == {"type": "idle", "for": "5m"}
    assert_round_trip(rule)


def test_actions_may_follow_suspend_but_not_shutdown() -> None:
    notify = {"type": "notify", "title": "PowerClock", "body": "back"}
    Rule.model_validate(make_rule(actions=[{"type": "power", "action": "suspend"}, notify]))
    Rule.model_validate(make_rule(actions=[notify, {"type": "power", "action": "shutdown"}]))
    with pytest.raises(ValidationError, match="must be the last action"):
        Rule.model_validate(make_rule(actions=[{"type": "power", "action": "shutdown"}, notify]))


@pytest.mark.parametrize("trigger", ["at", "countdown", "cron"])
def test_wake_accepts_time_triggers(trigger: str) -> None:
    Rule.model_validate(make_rule(trigger=TRIGGERS[trigger], wake=True))


def test_cron_accepts_nicknames() -> None:
    Rule.model_validate(make_rule(trigger={"type": "cron", "expr": "@daily"}))


INVALID: list[tuple[str, dict[str, Any], str]] = [
    ("unknown field", {"enabeld": False}, "Extra inputs are not permitted"),
    ("bad id", {"id": "Backup Nocturno"}, "should match pattern"),
    ("empty name", {"name": ""}, "at least 1 character"),
    ("no actions", {"actions": []}, "at least 1 item"),
    ("unknown trigger", {"trigger": {"type": "sunrise"}}, "sunrise"),
    ("trigger without type", {"trigger": {"expr": "0 3 * * *"}}, "Unable to extract tag"),
    ("extra trigger field", {"trigger": {**TRIGGERS["cron"], "tz": "UTC"}}, "Extra inputs"),
    ("cron out of range", {"trigger": {"type": "cron", "expr": "61 * * * *"}}, "invalid cron"),
    ("cron 6 fields", {"trigger": {"type": "cron", "expr": "0 0 3 * * *"}}, "invalid cron"),
    ("cron @reboot", {"trigger": {"type": "cron", "expr": "@reboot"}}, "invalid cron"),
    ("naive datetime", {"trigger": {"type": "at", "when": "2026-09-24T07:30:00"}}, "timezone"),
    ("zero countdown", {"trigger": {"type": "countdown", "duration": "0s"}}, "greater than zero"),
    ("cpu without for", {"trigger": {"type": "cpu_below", "percent": 10}}, "Field required"),
    ("cpu over 100", {"trigger": {**TRIGGERS["cpu_below"], "percent": 101}}, "less than or equal"),
    ("zero kbps", {"trigger": {**TRIGGERS["net_below"], "kbps": 0}}, "greater than 0"),
    ("process name and pid", {"trigger": {**TRIGGERS["process_exit"], "pid": 42}}, "exactly one"),
    ("process nothing", {"trigger": {"type": "process_exit"}}, "exactly one"),
    ("battery both", {"trigger": {"type": "battery", "below": 20, "above": 80}}, "exactly one"),
    ("battery neither", {"trigger": {"type": "battery"}}, "exactly one"),
    ("startup empty", {"trigger": {"type": "startup", "on": []}}, "at least 1 item"),
    ("wake on idle", {"trigger": TRIGGERS["idle"], "wake": True}, "needs a time trigger"),
    ("bad timezone", {"timezone": "Mars/Olympus"}, "unknown time zone"),
    ("bad duration", {"warning": "5 minutes"}, "invalid duration"),
    ("numeric duration", {"warning": 300}, "must be a string"),
    ("bad on_missed", {"on_missed": "later"}, "skip"),
    ("predicate shape", {"conditions": {"foo": 1}}, "needs a 'type' or exactly one"),
    ("two logic keys", {"conditions": {"all": [], "any": []}}, "needs a 'type' or exactly one"),
    ("empty all", {"conditions": {"all": []}}, "at least 1 item"),
    ("bad weekday", {"conditions": {"type": "weekday", "days": ["monday"]}}, "'mon'"),
    (
        "empty window",
        {"conditions": {"type": "time_window", "start": "08:00", "end": "08:00"}},
        "must differ",
    ),
    (
        "aware window",
        {"conditions": {"type": "time_window", "start": "08:00+02:00", "end": "09:00"}},
        "plain time of day",
    ),
    ("guards without any", {"guards": {"retry": "5m"}}, "Field required"),
    ("zero retry", {"guards": {"any": [{"type": "ssh_session"}], "retry": "0s"}}, "greater than"),
    ("bad power action", {"actions": [{"type": "power", "action": "explode"}]}, "shutdown"),
    ("empty cmd", {"actions": [{"type": "run", "cmd": []}]}, "at least 1 item"),
    ("empty program", {"actions": [{"type": "run", "cmd": [""]}]}, "cannot be empty"),
    (
        "shell with args",
        {"actions": [{"type": "run", "cmd": ["ls", "-l"], "shell": True}]},
        "single command line",
    ),
    (
        "timeout without wait",
        {"actions": [{"type": "run", "cmd": ["x"], "timeout": "1m", "wait": False}]},
        "only applies with wait",
    ),
    ("set_wake nothing", {"actions": [{"type": "set_wake"}]}, "exactly one"),
    (
        "set_wake both",
        {"actions": [{"type": "set_wake", "after": "1h", "when": "2026-09-24T07:30:00Z"}]},
        "exactly one",
    ),
]


@pytest.mark.parametrize(
    ("overrides", "message"), [case[1:] for case in INVALID], ids=[case[0] for case in INVALID]
)
def test_invalid_rules_are_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Rule.model_validate(make_rule(**overrides))
