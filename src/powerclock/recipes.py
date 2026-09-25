"""Recipes: ready-made arguments for common applications (a kiosk, a playlist on a loop, a
PDF as a presentation…), kept as data in recipes.json so adding one needs no code.

In `args`, `<name>` is something the user fills in when choosing the recipe (its label is
in `inputs`), and `{date}`, `{data}`… are replaced when the step runs (engine/variables.py).
"""

import json
import locale
import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from powerclock.platform.base import WindowPlacement

DATA = Path(__file__).with_name("recipes.json")
INPUT = re.compile(r"<([a-z_]+)>")


@dataclass(frozen=True)
class Recipe:
    id: str
    apps: tuple[str, ...]
    label: dict[str, str]
    args: tuple[str, ...]
    inputs: dict[str, dict[str, str]] = field(default_factory=dict)
    note: dict[str, str] = field(default_factory=dict)
    window: WindowPlacement | None = None
    keep_open: bool = False

    def text(self, value: dict[str, str], language: str | None = None) -> str:
        """A translated text of the recipe (English when there is no translation)."""
        return value.get(language or current_language()) or value.get("en", "")

    def title(self, language: str | None = None) -> str:
        return self.text(self.label, language)

    def fill(self, values: dict[str, str]) -> list[str]:
        """The arguments with each `<input>` replaced; a missing one stays as `<input>`."""
        return [INPUT.sub(lambda m: values.get(m[1]) or m[0], arg) for arg in self.args]

    def for_app(self, app: str, flatpak: str | None = None) -> bool:
        return app in self.apps or (flatpak is not None and flatpak in self.apps)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "apps": list(self.apps),
            "label": self.label,
            "note": self.note,
            "args": list(self.args),
            "inputs": self.inputs,
            "window": None if self.window is None else self.window.model_dump(),
            "keep_open": self.keep_open,
        }


@cache
def recipes() -> tuple[Recipe, ...]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return tuple(_recipe(item) for item in data["recipes"])


def _recipe(item: dict[str, Any]) -> Recipe:
    window = item.get("window")
    return Recipe(
        id=item["id"],
        apps=tuple(item["apps"]),
        label=item["label"],
        args=tuple(item["args"]),
        inputs=item.get("inputs", {}),
        note=item.get("note", {}),
        window=None if window is None else WindowPlacement.model_validate(window),
        keep_open=bool(item.get("keep_open", False)),
    )


def for_app(app: str, flatpak: str | None = None) -> list[Recipe]:
    return [recipe for recipe in recipes() if recipe.for_app(app, flatpak)]


def get(recipe_id: str) -> Recipe | None:
    return next((recipe for recipe in recipes() if recipe.id == recipe_id), None)


def current_language() -> str:
    """The two-letter language of the interface (as gettext picks it), "en" by default."""
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "")
        if value:
            code = value.split(":")[0].split("_")[0].split(".")[0].lower()
            return "en" if code in ("c", "posix") else code
    code = (locale.getlocale()[0] or "en").split("_")[0].lower()
    return code or "en"
