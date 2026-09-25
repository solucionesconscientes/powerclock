"""Editors generated from the JSON Schema of the rule models: one widget per field, so the
rule editor follows models.py without a hand-written form for every trigger, predicate and
step. Values go in and out as JSON (what `model_dump(mode="json")` gives)."""

import json
import shlex
import zoneinfo
from collections.abc import Callable
from datetime import datetime, time
from typing import Any, ClassVar

from pydantic import BaseModel
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from powerclock import recipes
from powerclock.gui.icons import themed
from powerclock.gui.widgets import (
    AppCombo,
    DurationEdit,
    LocalDateTimeEdit,
    ProcessCombo,
    next_quarter,
)
from powerclock.i18n import _
from powerclock.labels import field_label, kind_label, value_label
from powerclock.models import (
    DURATION_PATTERN,
    AtTrigger,
    BatteryLevel,
    CloseAppStep,
    CountdownTrigger,
    CpuBelow,
    CronTrigger,
    DesktopSession,
    Idle,
    LaunchStep,
    ManualTrigger,
    MediaPlaying,
    NetBelow,
    NotifyStep,
    OpenStep,
    PowerSource,
    PowerStep,
    ProcessExitTrigger,
    ProcessRunning,
    RunStep,
    SetWakeStep,
    SshSession,
    StartupTrigger,
    TimeWindow,
    WaitStep,
    WaitUntilStep,
    Weekday,
    WifiSsid,
    model_json_schema,
)

TRIGGERS: list[type[BaseModel]] = [
    AtTrigger,
    CountdownTrigger,
    CronTrigger,
    Idle,
    ProcessExitTrigger,
    CpuBelow,
    NetBelow,
    BatteryLevel,
    PowerSource,
    DesktopSession,
    StartupTrigger,
    ManualTrigger,
]
PREDICATES: list[type[BaseModel]] = [
    ProcessRunning,
    MediaPlaying,
    SshSession,
    Idle,
    CpuBelow,
    NetBelow,
    BatteryLevel,
    PowerSource,
    TimeWindow,
    Weekday,
    WifiSsid,
    DesktopSession,
]
ACTIONS: list[type[BaseModel]] = [
    PowerStep,
    RunStep,
    LaunchStep,
    NotifyStep,
    OpenStep,
    CloseAppStep,
    WaitStep,
    WaitUntilStep,
    SetWakeStep,
]
HIDDEN = {"type", "armed_at"}  # the discriminator and what the daemon fills in
PROCESS_MODELS = (ProcessRunning, ProcessExitTrigger, CloseAppStep)  # their `name` is a program
JSON_KIND = "json"
INT_MAX = 2**31 - 1

# Friendly starting values for a new item (required fields have no default).
STARTERS: dict[tuple[str, str], Any] = {
    ("countdown", "duration"): "30m",
    ("cron", "expr"): "0 3 * * *",
    ("idle", "for"): "20m",
    ("cpu_below", "percent"): 10,
    ("cpu_below", "for"): "5m",
    ("net_below", "kbps"): 50,
    ("net_below", "for"): "5m",
    ("battery", "below"): 15,
    ("power_source", "is"): "battery",
    ("time_window", "start"): "22:00:00",
    ("time_window", "end"): "07:00:00",
    ("weekday", "days"): ["mon", "tue", "wed", "thu", "fri"],
    ("power", "action"): "shutdown",
    ("notify", "title"): "PowerClock",
    ("wait", "duration"): "1m",
    ("wait_until", "condition"): {"type": "net_below", "kbps": 50, "for": "5m"},
    ("set_wake", "after"): "8h",
}


def type_of(model: type[BaseModel]) -> str:
    kind = model.model_fields["type"].default
    assert isinstance(kind, str)
    return kind


# ── Field editors ─────────────────────────────────────────────────────────────


class FieldEditor:
    """One field: its widget, and its value as JSON."""

    def __init__(self, name: str, widget: QWidget) -> None:
        self.name = name
        self.widget = widget

    def get(self) -> Any:
        raise NotImplementedError

    def set(self, value: Any) -> None:
        raise NotImplementedError


class TextField(FieldEditor):
    """Text; with `optional`, an empty box means null."""

    def __init__(self, name: str, *, optional: bool = False) -> None:
        self.edit = QLineEdit()
        super().__init__(name, self.edit)
        self.optional = optional

    def get(self) -> Any:
        text = self.edit.text()
        return None if self.optional and not text.strip() else text

    def set(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))


class ProgramField(TextField):
    """A process name: typed or picked from the running ones."""

    def __init__(self, name: str, *, optional: bool = False) -> None:
        FieldEditor.__init__(self, name, ProcessCombo())
        self.optional = optional
        assert isinstance(self.widget, ProcessCombo)
        self.combo = self.widget

    def get(self) -> Any:
        text = self.combo.value()
        return None if self.optional and not text else text

    def set(self, value: Any) -> None:
        self.combo.setEditText("" if value is None else str(value))


class TimezoneField(FieldEditor):
    def __init__(self, name: str) -> None:
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItem(_("The computer's"), None)
        for zone in sorted(zoneinfo.available_timezones()):
            self.combo.addItem(zone, zone)
        super().__init__(name, self.combo)

    def get(self) -> Any:
        text = self.combo.currentText().strip()
        return None if not text or text == self.combo.itemText(0) else text

    def set(self, value: Any) -> None:
        if value is None:
            self.combo.setCurrentIndex(0)
        else:
            self.combo.setEditText(str(value))


class BoolField(FieldEditor):
    def __init__(self, name: str) -> None:
        self.box = QCheckBox(field_label(name))
        super().__init__(name, self.box)

    def get(self) -> Any:
        return self.box.isChecked()

    def set(self, value: Any) -> None:
        self.box.setChecked(bool(value))


class ChoiceField(FieldEditor):
    def __init__(self, name: str, choices: list[str]) -> None:
        self.combo = QComboBox()
        for choice in choices:
            self.combo.addItem(value_label(name, choice), choice)
        super().__init__(name, self.combo)

    def get(self) -> Any:
        return self.combo.currentData()

    def set(self, value: Any) -> None:
        index = self.combo.findData(value)
        self.combo.setCurrentIndex(max(0, index))


class MultiChoiceField(FieldEditor):
    def __init__(self, name: str, choices: list[str]) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        self.boxes: dict[str, QCheckBox] = {}
        for choice in choices:
            box = QCheckBox(value_label(name, choice))
            layout.addWidget(box)
            self.boxes[choice] = box
        layout.addStretch(1)
        super().__init__(name, row)

    def get(self) -> Any:
        return [choice for choice, box in self.boxes.items() if box.isChecked()]

    def set(self, value: Any) -> None:
        chosen = set(value or [])
        for choice, box in self.boxes.items():
            box.setChecked(choice in chosen)


class DurationField(FieldEditor):
    def __init__(self, name: str, *, optional: bool = False) -> None:
        self.edit = DurationEdit(allow_zero=True)
        super().__init__(name, self.edit)
        self.optional = optional

    def get(self) -> Any:
        text = self.edit.text().strip().replace(" ", "")
        return None if self.optional and not text else text

    def set(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))


class NumberField(FieldEditor):
    def __init__(self, name: str, schema: dict[str, Any], *, integer: bool) -> None:
        low = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        high = schema.get("maximum", INT_MAX if integer else 1e9)
        if integer:
            self.spin: QSpinBox | QDoubleSpinBox = QSpinBox()
            self.spin.setRange(int(low), int(high))
        else:
            spin = QDoubleSpinBox()
            spin.setDecimals(1)
            spin.setRange(float(low), float(high))
            self.spin = spin
        self.integer = integer
        super().__init__(name, self.spin)

    def get(self) -> Any:
        value = self.spin.value()
        return int(value) if self.integer else float(value)

    def set(self, value: Any) -> None:
        if value is not None:
            self.spin.setValue(value)


class TimeField(FieldEditor):
    def __init__(self, name: str) -> None:
        self.edit = QTimeEdit()
        self.edit.setDisplayFormat("HH:mm")
        super().__init__(name, self.edit)

    def get(self) -> Any:
        return self.edit.time().toString("HH:mm:ss")

    def set(self, value: Any) -> None:
        if value:
            parsed = time.fromisoformat(str(value))
            self.edit.setTime(QTime(parsed.hour, parsed.minute, parsed.second))


class DateTimeField(FieldEditor):
    def __init__(self, name: str) -> None:
        self.edit = LocalDateTimeEdit()
        self.edit.set_value(next_quarter())
        super().__init__(name, self.edit)

    def get(self) -> Any:
        return self.edit.value().astimezone().isoformat()  # local time, as the user sees it

    def set(self, value: Any) -> None:
        if value:
            self.edit.set_value(datetime.fromisoformat(str(value)))


class ArgsField(FieldEditor):
    """A command as one line: split like a shell would (or kept whole with `raw`)."""

    def __init__(self, name: str) -> None:
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(_("e.g. /home/pc/bin/backup.sh --full"))
        super().__init__(name, self.edit)
        self.raw = False

    def get(self) -> Any:
        text = self.edit.text().strip()
        if self.raw:
            return [text] if text else []
        try:
            return shlex.split(text)
        except ValueError:
            return [text]  # an unbalanced quote: let validation explain

    def set(self, value: Any) -> None:
        items = list(value or [])
        self.edit.setText(items[0] if self.raw and len(items) == 1 else shlex.join(items))


class EnvField(FieldEditor):
    def __init__(self, name: str) -> None:
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("LANG=C BACKUP_DIR=/mnt/backup")
        super().__init__(name, self.edit)

    def get(self) -> Any:
        pairs = {}
        for item in shlex.split(self.edit.text()):
            key, _sep, value = item.partition("=")
            pairs[key] = value
        return pairs

    def set(self, value: Any) -> None:
        self.edit.setText(" ".join(shlex.quote(f"{k}={v}") for k, v in (value or {}).items()))


class AppField(FieldEditor):
    """An installed application (its desktop entry id); optional: empty means null."""

    def __init__(self, name: str, *, optional: bool = False) -> None:
        self.combo = AppCombo()
        super().__init__(name, self.combo)
        self.optional = optional

    def get(self) -> Any:
        value = self.combo.value()
        return None if self.optional and not value else value

    def set(self, value: Any) -> None:
        self.combo.set_value(None if value is None else str(value))


class RecipeField(FieldEditor):
    """The recipe that filled the arguments. Picking one fills them in (`on_pick`); what
    the user must still write (`<url>`…) is listed below it."""

    def __init__(self, name: str) -> None:
        self.combo = QComboBox()
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addWidget(self.hint)
        super().__init__(name, box)
        self.on_pick: Callable[[recipes.Recipe], None] | None = None
        self.offer(None, None)
        self.combo.activated.connect(self._picked)  # the user's choice, not set()

    def offer(self, app: str | None, flatpak: str | None) -> None:
        """List the recipes made for `app`, keeping the current one."""
        current = self.get()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(_("(none)"), None)
        for recipe in recipes.for_app(app or "", flatpak):
            self.combo.addItem(recipe.title(), recipe.id)
            note = recipe.text(recipe.note)
            if note:
                self.combo.setItemData(self.combo.count() - 1, note, Qt.ItemDataRole.ToolTipRole)
        self.combo.blockSignals(False)
        self.set(current)

    def get(self) -> Any:
        return self.combo.currentData()

    def set(self, value: Any) -> None:
        index = self.combo.findData(value) if value else 0
        if index < 0:  # a recipe of another app, or one that no longer exists: keep it
            self.combo.addItem(str(value), value)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)
        self._show_hint(recipes.get(value) if value else None)

    def _picked(self, index: int) -> None:
        recipe = recipes.get(self.combo.itemData(index) or "")
        self._show_hint(recipe)
        if recipe is not None and self.on_pick is not None:
            self.on_pick(recipe)

    def _show_hint(self, recipe: recipes.Recipe | None) -> None:
        lines = []
        if recipe is not None:
            note = recipe.text(recipe.note)
            if note:
                lines.append(note)
            for key, label in recipe.inputs.items():
                lines.append(
                    _("Replace <{key}> with: {what}").format(key=key, what=recipe.text(label))
                )
        self.hint.setText("\n".join(lines))
        self.hint.setVisible(bool(lines))


class WindowField(FieldEditor):
    """Where the window goes: off (null), or a screen, a virtual desktop, a state and
    whether it stays on top."""

    STATES = ("normal", "maximized", "fullscreen", "minimized")

    def __init__(self, name: str) -> None:
        self.box = QCheckBox(_("Place it:"))
        self.screen = QSpinBox()
        self.screen.setRange(0, 16)
        self.screen.setSpecialValueText(_("any screen"))
        self.screen.setPrefix(_("screen") + " ")
        self.desktop = QSpinBox()
        self.desktop.setRange(0, 20)
        self.desktop.setSpecialValueText(_("current desktop"))
        self.desktop.setPrefix(_("desktop") + " ")
        self.state = QComboBox()
        for state in self.STATES:
            self.state.addItem(value_label("state", state), state)
        self.above = QCheckBox(_("on top"))
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.box, self.screen, self.desktop, self.state, self.above):
            layout.addWidget(widget)
        layout.addStretch(1)
        super().__init__(name, row)
        self.box.toggled.connect(self._enable)
        self._enable(False)

    def _enable(self, on: bool) -> None:
        for widget in (self.screen, self.desktop, self.state, self.above):
            widget.setEnabled(on)

    def get(self) -> Any:
        if not self.box.isChecked():
            return None
        return {
            "screen": self.screen.value() or None,
            "desktop": self.desktop.value() or None,
            "state": self.state.currentData(),
            "above": self.above.isChecked(),
        }

    def set(self, value: Any) -> None:
        data = value or {}
        self.box.setChecked(value is not None)
        self.screen.setValue(int(data.get("screen") or 0))
        self.desktop.setValue(int(data.get("desktop") or 0))
        self.state.setCurrentIndex(max(0, self.state.findData(data.get("state", "normal"))))
        self.above.setChecked(bool(data.get("above")))


class OptionalField(FieldEditor):
    """A checkbox that enables a field; unchecked means null (for numbers and dates)."""

    def __init__(self, inner: FieldEditor) -> None:
        self.inner = inner
        self.box = QCheckBox()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.box)
        layout.addWidget(inner.widget, 1)
        self.box.toggled.connect(inner.widget.setEnabled)
        inner.widget.setEnabled(False)
        super().__init__(inner.name, row)

    def get(self) -> Any:
        return self.inner.get() if self.box.isChecked() else None

    def set(self, value: Any) -> None:
        self.box.setChecked(value is not None)
        if value is not None:
            self.inner.set(value)


class PredicateField(FieldEditor):
    """A nested condition (the `condition` of wait_until)."""

    def __init__(self, name: str) -> None:
        self.editor = PredicateEditor(removable=False)
        super().__init__(name, self.editor)

    def get(self) -> Any:
        return self.editor.get()

    def set(self, value: Any) -> None:
        self.editor.set(value)


class JsonField(FieldEditor):
    """Anything the other editors do not cover, as JSON text."""

    def __init__(self, name: str) -> None:
        self.edit = QLineEdit()
        super().__init__(name, self.edit)

    def get(self) -> Any:
        text = self.edit.text().strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(_("invalid JSON: {error}").format(error=exc)) from None

    def set(self, value: Any) -> None:
        self.edit.setText("" if value is None else json.dumps(value, ensure_ascii=False))


def editor_for(
    name: str, schema: dict[str, Any], defs: dict[str, Any], *, program: bool = False
) -> FieldEditor:
    """Pick the editor that fits a property of the JSON Schema (`program`: a process name)."""
    if name == "condition":
        return PredicateField(name)
    if name == "timezone":
        return TimezoneField(name)
    if name == "recipe":
        return RecipeField(name)
    if name == "window":
        return WindowField(name)
    optional = False
    if "anyOf" in schema:
        options = [option for option in schema["anyOf"] if option.get("type") != "null"]
        optional = len(options) < len(schema["anyOf"])
        if len(options) != 1:
            return JsonField(name)
        schema = options[0]
    schema = _resolve(schema, defs)
    kind, fmt = schema.get("type"), schema.get("format")
    if "enum" in schema:
        return ChoiceField(name, list(schema["enum"]))
    if kind == "boolean":
        return BoolField(name)
    if kind == "string" and schema.get("pattern") == DURATION_PATTERN:
        return DurationField(name, optional=optional)
    if kind == "string" and fmt == "date-time":
        field: FieldEditor = DateTimeField(name)
        return OptionalField(field) if optional else field
    if kind == "string" and fmt == "time":
        return TimeField(name)
    if kind in ("integer", "number"):
        field = NumberField(name, schema, integer=kind == "integer")
        return OptionalField(field) if optional else field
    if kind == "array":
        items = _resolve(schema.get("items", {}), defs)
        if "enum" in items:
            return MultiChoiceField(name, list(items["enum"]))
        if items.get("type") == "string":
            return ArgsField(name)
    if kind == "object" and schema.get("additionalProperties", {}).get("type") == "string":
        return EnvField(name)
    if kind == "string":
        if program:
            return ProgramField(name, optional=optional)
        if name == "app":
            return AppField(name, optional=optional)
        return TextField(name, optional=optional)
    return JsonField(name)


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return {
            **defs[ref.removeprefix("#/$defs/")],
            **{k: v for k, v in schema.items() if k != "$ref"},
        }
    return schema


# ── A model's form ────────────────────────────────────────────────────────────


class ModelForm(QWidget):
    """The fields of one model (or some of them), laid out as a form."""

    def __init__(
        self,
        model: type[BaseModel],
        *,
        only: tuple[str, ...] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        schema = model_json_schema(model)
        defs = schema.get("$defs", {})
        kind = model.model_fields["type"].default if "type" in model.model_fields else None
        self.fields: dict[str, FieldEditor] = {}
        self.defaults: dict[str, Any] = {}
        self._loading = False
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        names = only or tuple(schema["properties"])
        for name in names:
            if name in HIDDEN:
                continue
            prop = schema["properties"][name]
            program = name == "name" and model in PROCESS_MODELS
            field = editor_for(name, prop, defs, program=program)
            self.fields[name] = field
            self.defaults[name] = STARTERS.get((str(kind), name), self._default(name, prop))
            label = "" if isinstance(field, BoolField) else field_label(name) + ":"
            layout.addRow(label, field.widget)
        if isinstance(self.fields.get("cmd"), ArgsField) and "shell" in self.fields:
            shell = self.fields["shell"]
            assert isinstance(shell, BoolField)
            shell.box.toggled.connect(self._shell_toggled)
        app, recipe = self.fields.get("app"), self.fields.get("recipe")
        if isinstance(app, AppField) and isinstance(recipe, RecipeField):
            app.combo.currentTextChanged.connect(lambda _text: self._offer_recipes())
            recipe.on_pick = self._apply_recipe
        self.set({})

    def get(self) -> dict[str, Any]:
        return {name: field.get() for name, field in self.fields.items()}

    def set(self, data: dict[str, Any]) -> None:
        """Show `data`; fields it does not mention get their default."""
        shell = data.get("shell", self.defaults.get("shell"))
        if isinstance(self.fields.get("cmd"), ArgsField):
            args = self.fields["cmd"]
            assert isinstance(args, ArgsField)
            args.raw = bool(shell)
        self._loading = True  # showing a value is not the user ticking "shell"
        try:
            for name, field in self.fields.items():
                field.set(data.get(name, self.defaults.get(name)))
        finally:
            self._loading = False

    def _default(self, name: str, prop: dict[str, Any]) -> Any:
        if "default" in prop:
            return prop["default"]
        info = self.model.model_fields.get(name) or next(
            (f for f in self.model.model_fields.values() if f.alias == name), None
        )
        if info is not None and info.default_factory is not None:
            return info.default_factory()  # type: ignore[call-arg]
        return None

    def _offer_recipes(self) -> None:
        app, recipe = self.fields["app"], self.fields["recipe"]
        assert isinstance(app, AppField)
        assert isinstance(recipe, RecipeField)
        chosen = app.combo.app()
        recipe.offer(app.get(), chosen.get("flatpak") if chosen else None)

    def _apply_recipe(self, recipe: recipes.Recipe) -> None:
        """A recipe was picked: its arguments (with `<inputs>` to replace), and whether the
        app is kept open and where its window goes."""
        self.fields["args"].set(recipe.fill({}))
        if "keep_open" in self.fields:
            self.fields["keep_open"].set(recipe.keep_open)
        if recipe.window is not None and "window" in self.fields:
            self.fields["window"].set(recipe.window.model_dump())

    def _shell_toggled(self, on: bool) -> None:
        if self._loading:
            return
        args = self.fields["cmd"]
        assert isinstance(args, ArgsField)
        value = args.get()
        args.raw = on
        args.set([shlex.join(value)] if on else shlex.split(value[0]) if value else [])


# ── A type chooser plus the chosen type's form ────────────────────────────────


class KindEditor(QWidget):
    """Pick a trigger, condition or step type; its fields appear below."""

    removed = Signal()
    moved = Signal(int)  # -1 up, +1 down
    models: ClassVar[list[type[BaseModel]]] = []

    def __init__(
        self,
        *,
        removable: bool = True,
        movable: bool = False,
        allow_json: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = QComboBox()
        for model in self.models:
            self.kind.addItem(kind_label(type_of(model)), type_of(model))
        if allow_json:
            self.kind.addItem(kind_label(JSON_KIND), JSON_KIND)
        self.stack = QStackedWidget()
        self._forms: dict[str, ModelForm] = {}
        self.json = QLineEdit()
        self.json.setPlaceholderText('{"any": [...]}')
        self._json_page = self.json if allow_json else None

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.extra = QHBoxLayout()  # subclasses add widgets next to the chooser
        header.addLayout(self.extra)
        header.addWidget(self.kind, 1)
        if movable:
            for delta, icon, tip in ((-1, "go-up", _("Move up")), (1, "go-down", _("Move down"))):
                button = QToolButton()
                button.setIcon(themed(icon))
                button.setText("↑" if delta < 0 else "↓")
                button.setToolTip(tip)
                button.clicked.connect(lambda _=False, d=delta: self.moved.emit(d))
                header.addWidget(button)
        if removable:
            remove = QToolButton()
            remove.setIcon(themed("list-remove"))
            remove.setText("✕")
            remove.setToolTip(_("Remove"))
            remove.clicked.connect(self.removed.emit)
            header.addWidget(remove)

        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        body = QVBoxLayout(frame)
        body.addLayout(header)
        body.addWidget(self.stack)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(frame)
        self.kind.currentIndexChanged.connect(self._show_kind)
        self._show_kind()

    def get(self) -> dict[str, Any]:
        kind = self.kind.currentData()
        if kind == JSON_KIND:
            try:
                value = json.loads(self.json.text())
            except json.JSONDecodeError as exc:
                raise ValueError(_("invalid JSON: {error}").format(error=exc)) from None
            if not isinstance(value, dict):
                raise ValueError(_("the JSON must be an object"))
            return value
        return {"type": kind, **self._form(kind).get()}

    def set(self, data: dict[str, Any] | None) -> None:
        kind = (data or {}).get("type")
        index = self.kind.findData(kind)
        if index < 0 and data and self._json_page is not None:
            self.kind.setCurrentIndex(self.kind.findData(JSON_KIND))
            self.json.setText(json.dumps(data, ensure_ascii=False))
            return
        self.kind.setCurrentIndex(max(0, index))
        self._form(self.kind.currentData()).set(data or {})

    def _form(self, kind: str) -> ModelForm:
        if kind not in self._forms:
            model = next(model for model in self.models if type_of(model) == kind)
            self._forms[kind] = form = ModelForm(model)
            self.stack.addWidget(form)
        return self._forms[kind]

    def _show_kind(self) -> None:
        kind = self.kind.currentData()
        if kind == JSON_KIND:
            if self.stack.indexOf(self.json) < 0:
                self.stack.addWidget(self.json)
            current: QWidget = self.json
        else:
            current = self._form(kind)
        self.stack.setCurrentWidget(current)
        # A stack is as tall as its tallest page: hidden pages must not count.
        for index in range(self.stack.count()):
            page = self.stack.widget(index)
            policy = QSizePolicy.Policy.Preferred if page is current else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
        self.stack.adjustSize()


class TriggerEditor(KindEditor):
    models: ClassVar[list[type[BaseModel]]] = TRIGGERS

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(removable=False, parent=parent)


class ActionEditor(KindEditor):
    models: ClassVar[list[type[BaseModel]]] = ACTIONS

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(removable=True, movable=True, parent=parent)


class PredicateEditor(KindEditor):
    """A condition: one of the simple ones (optionally negated) or any tree as JSON."""

    models: ClassVar[list[type[BaseModel]]] = PREDICATES

    def __init__(self, *, removable: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(removable=removable, allow_json=True, parent=parent)
        self.negate = QCheckBox(_("not"))
        self.negate.setToolTip(_("True when the condition does not hold"))
        self.extra.addWidget(self.negate)

    def get(self) -> dict[str, Any]:
        value = super().get()
        return {"not": value} if self.negate.isChecked() else value

    def set(self, data: dict[str, Any] | None) -> None:
        inner = data.get("not") if isinstance(data, dict) and set(data) == {"not"} else None
        simple = isinstance(inner, dict) and self.kind.findData(inner.get("type")) >= 0
        self.negate.setChecked(simple)
        super().set(inner if simple else data)


# ── Lists: conditions, guards and steps ───────────────────────────────────────


class EditorList(QWidget):
    """A column of editors with an Add button."""

    def __init__(
        self, factory: type[KindEditor], add_text: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._factory = factory
        self.editors: list[KindEditor] = []
        self._column = QVBoxLayout()
        self._column.setContentsMargins(0, 0, 0, 0)
        add = QPushButton(themed("list-add"), add_text)
        add.clicked.connect(lambda: self.add(None))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._column)
        layout.addWidget(add, 0)
        self.empty = QLabel(_("(none)"))
        self._column.addWidget(self.empty)

    def add(self, data: dict[str, Any] | None) -> KindEditor:
        editor = self._factory()
        editor.set(data)
        editor.removed.connect(lambda: self._remove(editor))
        editor.moved.connect(lambda delta: self._move(editor, delta))
        self.editors.append(editor)
        self._column.addWidget(editor)
        self.empty.setVisible(False)
        return editor

    def get(self) -> list[dict[str, Any]]:
        return [editor.get() for editor in self.editors]

    def set(self, items: list[dict[str, Any]]) -> None:
        for editor in list(self.editors):
            self._remove(editor)
        for item in items:
            self.add(item)

    def _remove(self, editor: KindEditor) -> None:
        self.editors.remove(editor)
        self._column.removeWidget(editor)
        editor.deleteLater()
        self.empty.setVisible(not self.editors)

    def _move(self, editor: KindEditor, delta: int) -> None:
        index = self.editors.index(editor)
        target = index + delta
        if not 0 <= target < len(self.editors):
            return
        self.editors.insert(target, self.editors.pop(index))
        self._column.removeWidget(editor)
        self._column.insertWidget(target + 1, editor)  # +1: the "(none)" label comes first
