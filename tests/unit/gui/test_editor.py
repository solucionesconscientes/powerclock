"""The rule editor: forms generated from the models, JSON view, saving through the API."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from guisupport import pump
from powerclock.gui import forms
from powerclock.gui.client import DaemonLink
from powerclock.gui.editor import RuleEditor
from powerclock.gui.forms import (
    ACTIONS,
    PREDICATES,
    TRIGGERS,
    ActionEditor,
    AppField,
    ArgsField,
    PredicateEditor,
    TextField,
    type_of,
)
from powerclock.models import Rule

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
    qapp: object,
    editor_class: type[Any],
    models: list[type[BaseModel]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(forms.SETTINGS, "tariff", "es-2.0td")  # offers tariff_period
    for model in models:
        editor = editor_class()
        editor.kind.setCurrentIndex(editor.kind.findData(type_of(model)))
        form = editor._form(type_of(model))
        if type_of(model) == "close_app":  # by name or by app: the user picks one
            form.fields["name"].set("x")
        elif type_of(model) == "wake_lan":
            form.fields["mac"].set("00:1a:2b:3c:4d:5e")
        elif type_of(model) in ("media", "sound", "ask"):  # their starting values are enough
            pass
        else:
            for field in form.fields.values():  # what the user must type (a program, a URL…)
                if isinstance(field, TextField | ArgsField | AppField) and not field.get():
                    field.set(["x"] if isinstance(field, ArgsField) else "x")
        model.model_validate(editor.get())


async def test_starting_triggers_are_valid(qapp: object) -> None:
    editor = RuleEditor(None, None)  # type: ignore[arg-type]
    for model in TRIGGERS:
        if type_of(model) == "process_exit":
            continue  # name or PID: the user has to write one
        editor.trigger.kind.setCurrentIndex(editor.trigger.kind.findData(type_of(model)))
        for field in editor.trigger._form(type_of(model)).fields.values():
            if isinstance(field, TextField) and not field.get():  # a Wi-Fi, a device…
                field.set("x")
        editor.validate()


async def test_tariff_period_is_offered_only_with_a_tariff(
    qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert PredicateEditor().kind.findData("tariff_period") < 0
    kept = PredicateEditor()  # a saved one is not lost: it is shown as JSON
    kept.set({"type": "tariff_period", "period": "valley"})
    assert kept.get() == {"type": "tariff_period", "period": "valley"}
    monkeypatch.setitem(forms.SETTINGS, "tariff", "es-2.0td")
    assert PredicateEditor().kind.findData("tariff_period") >= 0


async def test_holiday_days_are_typed_on_one_line(qapp: object) -> None:
    editor = PredicateEditor()
    editor.set({"type": "holiday", "extra": ["2026-06-24", "2026-12-26"]})
    field = editor._form("holiday").fields["extra"]
    assert field.widget.text() == "2026-06-24, 2026-12-26"
    field.widget.setText("2026-06-24 2026-09-11;2026-12-26")
    assert editor.get()["extra"] == ["2026-06-24", "2026-09-11", "2026-12-26"]


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
            "actions": [{"type": "notify", "title": "PowerClock"}],
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


async def test_tabs_use_the_users_words(qapp: object) -> None:
    editor = RuleEditor(None, None)  # type: ignore[arg-type]
    names = [editor.tabs.tabText(index) for index in range(editor.tabs.count())]
    assert names == [
        "When",
        "Only if…",
        "Wait while…",
        "What it does",
        "Options",
        "Advanced (JSON)",
    ]
    editor.close()


async def test_launch_step_with_a_recipe_and_a_window(qapp: object) -> None:
    from powerclock.gui import widgets
    from powerclock.models import LaunchStep

    widgets.APP_CATALOG[:] = [
        {"id": "vlc", "name": "VLC", "names": {"es": "VLC (es)"}, "icon": "vlc", "flatpak": None}
    ]
    editor = ActionEditor()
    editor.kind.setCurrentIndex(editor.kind.findData("launch"))
    form = editor._form("launch")
    form.fields["app"].set("vlc")
    recipe = form.fields["recipe"]
    index = recipe.combo.findData("vlc.loop")
    assert index > 0
    recipe.combo.setCurrentIndex(index)
    recipe._picked(index)
    assert "Replace <file>" in recipe.hint.text()
    form.fields["window"].set({"screen": 2, "state": "fullscreen"})
    data = editor.get()
    assert data["app"] == "vlc"
    assert data["recipe"] == "vlc.loop"
    assert data["args"] == ["--fullscreen", "--loop", "--random", "<file>"]
    assert data["window"] == {"screen": 2, "desktop": None, "state": "fullscreen", "above": False}
    step = LaunchStep.model_validate(data)
    again = ActionEditor()
    again.set(step.model_dump(mode="json"))
    assert again.get() == step.model_dump(mode="json")


async def test_failure_steps_survive_the_editor(qapp: object) -> None:
    data = {
        "id": "copia",
        "name": "Copia",
        "trigger": {"type": "cron", "expr": "0 3 * * *"},
        "actions": [{"type": "run", "cmd": ["backup.sh"]}],
        "on_failure": [
            {"type": "push", "url": "https://ntfy.sh/t", "message": "{rule}: {error}"},
            {"type": "ask", "title": "¿Reintentar?", "buttons": ["Sí", "No"], "go_on": "Sí"},
        ],
    }
    editor = RuleEditor(None, dump(data))  # type: ignore[arg-type]
    assert len(editor.on_failure.editors) == 2
    assert dump(editor.validate())["on_failure"] == dump(data)["on_failure"]


# ── M15: schedules without cron, the sentence, the gallery ───────────────────


@pytest.mark.parametrize(
    ("expr", "kind"),
    [
        ("0 3 * * *", "daily"),
        ("30 7 * * 1-5", "weekdays"),
        ("0 10 * * 0,6", "weekends"),
        ("0 20 * * 1,4", "days"),
        ("15 9 12 * *", "monthly"),
        ("0 */3 * * *", "hours"),
        ("*/20 * * * *", "minutes"),
        ("@daily", "cron"),
        ("0 3 * * 4,1", "cron"),  # the choices would reorder it: kept as written
        ("0 3 * * MON", "cron"),
    ],
)
async def test_schedules_without_cron(qapp: object, expr: str, kind: str) -> None:
    field = forms.ScheduleField("expr")
    field.set(expr)
    assert field.kind.currentData() == kind
    assert field.get() == expr
    assert field.expr.isHidden() == (kind != "cron")


async def test_building_a_schedule(qapp: object) -> None:
    from PySide6.QtCore import QTime

    field = forms.ScheduleField("expr")
    field.kind.setCurrentIndex(field.kind.findData("days"))
    field.time.setTime(QTime(20, 5))
    field.days["sat"].setChecked(True)
    field.days["mon"].setChecked(True)
    assert field.get() == "5 20 * * 1,6"
    assert not field.week.isHidden()
    field.kind.setCurrentIndex(field.kind.findData("cron"))
    field.expr.setText("0 3 * * *")
    assert field.words.text() == "It means: every day at 03:00"


async def test_the_rule_reads_as_a_sentence(qapp: object) -> None:
    backup = next(path for path in EXAMPLES if path.stem == "backup-nocturno")
    editor = RuleEditor(None, dump(json.loads(backup.read_text())))  # type: ignore[arg-type]
    text = editor.sentence.text()
    assert text.startswith("When Repeats: every day at 03:00 · turning the computer on")
    assert "Only if… Plugged in or on battery: Plugged in" in text
    assert "What it does run backup.sh → " in text
    editor.trigger._form("cron").fields["expr"].set("30 7 * * 1-5")
    editor.refresh_sentence()
    assert "on weekdays at 07:30" in editor.sentence.text()
    editor.sentence.values[3].linkActivated.emit("3")
    assert editor.tabs.currentIndex() == 3
    editor.close()


async def test_a_rule_from_the_gallery(
    qapp: object, link: DaemonLink, monkeypatch: pytest.MonkeyPatch
) -> None:
    from powerclock.gui.gallery import GalleryDialog
    from powerclock.gui.rules import RulesTab

    dialog = GalleryDialog()
    assert "cheap-hours" not in [t.id for t in dialog.templates]  # no tariff chosen
    assert [card.template.group for card in dialog.cards] == ["energy"] * len(dialog.cards)
    dialog.groups.setCurrentRow(2)
    assert {card.template.group for card in dialog.cards} == {"screens"}
    dialog.close()
    monkeypatch.setitem(forms.SETTINGS, "tariff", "es-2.0td")
    assert "cheap-hours" in [t.id for t in GalleryDialog().templates]

    tab = RulesTab(link)
    tab.from_gallery()
    assert tab.gallery is not None
    download = next(c for c in tab.gallery.cards if c.template.id == "download-done")
    download.button.click()
    await pump()
    assert tab.editor is not None
    assert tab.editor.general.fields["name"].get() == "Shut down when the download finishes"
    tab.editor.save()
    await pump()
    rules = await link.api.get("/rules")
    assert [r["name"] for r in rules] == ["Shut down when the download finishes"]
