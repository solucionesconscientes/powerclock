"""The recipes shipped in recipes.json: valid, translated, and filled in correctly."""

import re

import pytest

from powerclock import recipes
from powerclock.engine.variables import NAMES

RECIPES = recipes.recipes()


def test_ids_are_unique() -> None:
    ids = [recipe.id for recipe in RECIPES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("recipe", RECIPES, ids=lambda r: r.id)
def test_recipe_is_complete(recipe: recipes.Recipe) -> None:
    assert recipe.apps, "which apps is it for?"
    assert recipe.label.get("en")
    assert recipe.label.get("es")
    for label in recipe.inputs.values():
        assert label.get("en")
        assert label.get("es")
    if recipe.note:
        assert recipe.note.get("es")
    used = {name for arg in recipe.args for name in recipes.INPUT.findall(arg)}
    assert used == set(recipe.inputs), "every <input> is declared and used"
    for arg in recipe.args:  # runtime variables: only the known ones and {home}/{data}
        for name in re.findall(r"\{([a-z]+)\}", arg):
            assert name in (*NAMES, "home", "data")


def test_fill_and_lookup() -> None:
    kiosk = recipes.get("chromium.kiosk")
    assert kiosk is not None
    assert kiosk.keep_open
    assert kiosk.fill({"url": "https://x.org"})[-1] == "https://x.org"
    assert kiosk.fill({})[-1] == "<url>"  # left for the user
    floorp = [recipe.id for recipe in recipes.for_app("one.ablaze.floorp")]
    assert floorp == ["firefox.kiosk", "firefox.window"]
    assert recipes.for_app("some.flatpak", flatpak="org.videolan.VLC")[0].id == "vlc.loop"
    assert kiosk.title("es").startswith("Quiosco")
    assert kiosk.title("fr") == kiosk.label["en"]


def test_language(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "es_ES.UTF-8")
    assert recipes.current_language() == "es"
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    assert recipes.current_language() == "en"
