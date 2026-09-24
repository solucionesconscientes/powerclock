"""The rule editor: forms generated from the models, JSON view, saving through the API."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from guisupport import pump
from kse.gui.client import DaemonLink
from kse.gui.editor import RuleEditor
from kse.gui.forms import (
    ACTIONS,
    PREDICATES,
    TRIGGERS,
    ActionEditor,
    ArgsField,
    PredicateEditor,
    TextField,
    type_of,
)
from kse.models import Rule

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((ROOT / "examples").glob("*.json"))


def dump(data: dict[str, Any]) -> dict[str, Any]:
    return Rule.model_validate(data).model_dump(mode="json")


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.stem)
def test_examples_survive_the_forms(qapp: object, example: Path) -> None:
    original = dump(json.loads(example.read_text()))
    editor = RuleEditor(None, original)  # type: ignore[arg-type]
    assert dump(editor.validate()) == original


def rich_rule() -> dict[str, Any]:
    return {
        "id": "everything",
        "name": "Everything",
        "enabled": False,
        "trigger": {"type": "startup", "on": ["resume"], "delay": "30s"},
        "conditions": {
            "all": [
                {"not": {"type": "wifi_ssid", "ssid": "Bar"}},
                {"type": "weekday", "days": ["sat", "sun"]},
                {"type": "time_window", "start": "22:00", "end": "07:00"},
                {"any": [{"type": "ssh_session"}, {"type": "media_playing"}]},
            ]
        },
        "guards": {"any": [{"type": "battery", "below": 20}], "retry": "1m", "max_wait": "10m"},
        "actions": [
            {"type": "run", "cmd": ["echo $HOME > /tmp/x"], "shell": True, "timeout": "1m"},
            {"type": "run", "cmd": ["cp", "a file", "b"], "env": {"LANG": "C"}, "wait": False},
            {"type": "open", "target": "https://example.org"},
            {"type": "close_app", "name": "firefox", "timeout": "10s"},
            {"type": "set_wake", "after": "8h"},
            {"type": "set_wake", "when": "2026-10-01T07:30:00+02:00"},
            {"type": "power", "action": "suspend", "mode": "force"},
        ],
        "warning": "0s",
        "on_missed": "run_once",
        "on_error": "continue",
        "timezone": "Europe/Madrid",
        "dry_run": True,
    }


def same_instants(rule: dict[str, Any]) -> dict[str, Any]:
    """Dates come back in local time: compare them as instants."""
    for step in rule["actions"]:
        if step.get("when"):
            step["when"] = datetime.fromisoformat(step["when"]).astimezone(UTC).isoformat()
    return rule


async def test_every_kind_of_field_survives(qapp: object) -> None:
    original = dump(rich_rule())
    editor = RuleEditor(None, original)  # type: ignore[arg-type]
    assert same_instants(dump(editor.validate())) == same_instants(dump(rich_rule()))
    [nested] = [e for e in editor.conditions.editors if e.kind.currentData() == "json"]
    assert json.loads(nested.json.text()) == original["conditions"]["all"][3]


@pytest.mark.parametrize(
    ("editor_class", "models"),
    [(PredicateEditor, PREDICATES), (ActionEditor, ACTIONS)],
)
async def test_starting_values_are_valid(
    qapp: object, editor_class: type[Any], models: list[type[BaseModel]]
) -> None:
    for model in models:
        editor = editor_class()
        editor.kind.setCurrentIndex(editor.kind.findData(type_of(model)))
        form = editor._form(type_of(model))
        for field in form.fields.values():  # what the user must type (a program, a URL…)
            if isinstance(field, TextField | ArgsField) and not field.get():
                field.set(["x"] if isinstance(field, ArgsField) else "x")
        model.model_validate(editor.get())


async def test_starting_triggers_are_valid(qapp: object) -> None:
    editor = RuleEditor(None, None)  # type: ignore[arg-type]
    for model in TRIGGERS:
        if type_of(model) == "process_exit":
            continue  # name or PID: the user has to write one
        editor.trigger.kind.setCurrentIndex(editor.trigger.kind.findData(type_of(model)))
        editor.validate()


async def test_json_view_follows_the_form_and_back(qapp: object) -> None:
    editor = RuleEditor(None, dump(json.loads(EXAMPLES[0].read_text())))  # type: ignore[arg-type]
    editor.general.fields["name"].set("Renamed")
    editor.tabs.setCurrentWidget(editor.json)
    data = json.loads(editor.json.toPlainText())
    assert data["name"] == "Renamed"
    data["trigger"] = {"type": "idle", "for": "15m"}
    editor.json.setPlainText(json.dumps(data))
    editor.tabs.setCurrentIndex(0)
    assert editor.trigger.get() == {"type": "idle", "for": "15m"}
    editor.tabs.setCurrentWidget(editor.json)
    editor.json.setPlainText("{ not json")
    editor.tabs.setCurrentIndex(0)
    assert editor.tabs.currentWidget() is editor.json  # it stays until the JSON is fixed
    assert "invalid JSON" in editor.error.text()


async def test_editing_a_countdown_does_not_restart_it(qapp: object) -> None:
    rule = dump(
        {
            "id": "c",
            "name": "C",
            "trigger": {"type": "countdown", "duration": "1h", "armed_at": "2026-09-24T08:00:00Z"},
            "actions": [{"type": "notify", "title": "KSE"}],
        }
    )
    editor = RuleEditor(None, rule)  # type: ignore[arg-type]
    assert editor.validate()["trigger"]["armed_at"] == "2026-09-24T08:00:00Z"
    editor.trigger.set({"type": "countdown", "duration": "2h"})
    assert "armed_at" not in editor.validate()["trigger"]  # another countdown: starts anew


async def test_save_new_and_edited_rules(link: DaemonLink) -> None:
    editor = RuleEditor(link, None)
    editor.general.fields["name"].set("Nightly")
    editor.save()
    await pump()
    [rule] = await link.api.get("/rules")
    assert (rule["name"], rule["trigger"]["expr"]) == ("Nightly", "0 3 * * *")
    assert rule["id"].startswith("rule-")
    editor = RuleEditor(link, rule)
    assert editor.rule_id.isReadOnly()
    editor.options.fields["one_shot"].set(True)
    editor.save()
    await pump()
    assert (await link.api.get(f"/rules/{rule['id']}"))["one_shot"] is True


async def test_invalid_rules_are_explained(link: DaemonLink) -> None:
    editor = RuleEditor(link, None)
    editor.actions.set([])
    editor.save()
    await pump()
    assert editor.error.isVisible() or editor.error.text()
    assert "actions" in editor.error.text()
    assert await link.api.get("/rules") == []
    editor.actions.set([{"type": "power", "action": "shutdown"}, {"type": "notify", "title": "x"}])
    editor.save()
    assert "must be the last action" in editor.error.text()
