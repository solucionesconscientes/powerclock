"""Translations: every text of the code is translated, keeps its placeholders and markup,
and the compiled catalogue is up to date."""

import gettext
import importlib.util
import re
import string
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCALE = ROOT / "src" / "powerclock" / "locale"
MARKUP = re.compile(r"\[/?[a-z ]*\]")


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("i18n_tool", ROOT / "scripts" / "i18n.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()
CATALOGS = sorted(LOCALE.glob("*/LC_MESSAGES/powerclock.po"))


def fields(text: str) -> list[tuple[str | None, str | None]]:
    return sorted(
        (name, spec) for _, name, spec, _ in string.Formatter().parse(text) if name is not None
    )


@pytest.mark.parametrize("po", CATALOGS, ids=lambda path: path.parts[-3])
def test_every_text_is_translated(po: Path) -> None:
    catalog = tool.read_po(po)
    missing = [msgid for msgid in tool.extract() if not catalog.get(msgid)]
    assert missing == [], "run: uv run python scripts/i18n.py update, then translate"


@pytest.mark.parametrize("po", CATALOGS, ids=lambda path: path.parts[-3])
def test_translations_keep_placeholders_and_markup(po: Path) -> None:
    for msgid, msgstr in tool.read_po(po).items():
        if not msgid or not msgstr:
            continue
        assert fields(msgstr) == fields(msgid), msgid
        assert sorted(MARKUP.findall(msgstr)) == sorted(MARKUP.findall(msgid)), msgid


@pytest.mark.parametrize("po", CATALOGS, ids=lambda path: path.parts[-3])
def test_compiled_catalog_is_up_to_date(po: Path) -> None:
    compiled = tool.compile_mo(tool.read_po(po))
    assert po.with_suffix(".mo").read_bytes() == compiled, (
        "run: uv run python scripts/i18n.py compile"
    )


def test_spanish_is_loaded() -> None:
    spanish = gettext.translation("powerclock", LOCALE, languages=["es"])
    assert spanish.gettext("Cancel") == "Cancelar"
    assert (
        spanish.gettext("{action} when {process} ends").format(action="Apagar", process="ffmpeg")
        == "Apagar cuando termine ffmpeg"
    )
    sentence = spanish.gettext("The computer will shut down in {seconds} s")
    assert sentence.format(seconds=42) == "El equipo se apagará en 42 s"


GUI_JARGON = re.compile(r"\b(daemon|dry run|helper|unattended|guards?|triggers?)\b", re.IGNORECASE)
SPANISH_JARGON = re.compile(
    r"demonio|simulacro|ayudante|desatendid|disparador|guardas|una guarda", re.I
)


def test_the_gui_speaks_the_users_words() -> None:
    """Vocabulary of docs/ARCHITECTURE.md §10: the technical words stay in the CLI."""
    for msgid, places in tool.extract().items():
        if any(place.startswith("powerclock/gui/") for place in places):
            assert not GUI_JARGON.search(msgid), (msgid, places)
    for po in CATALOGS:
        for msgid, msgstr in tool.read_po(po).items():
            assert not SPANISH_JARGON.search(msgstr), msgid


def test_tests_run_in_english() -> None:
    from powerclock.i18n import _

    assert _("Cancel") == "Cancel"


def test_po_round_trip(tmp_path: Path) -> None:
    po = tmp_path / "powerclock.po"
    texts = {'Say "hi"\nnow': ["powerclock/x.py:1"], "Plain": ["powerclock/y.py:2"]}
    tool.write_po(po, "Content-Type: text/plain; charset=UTF-8\n", texts, {"Plain": "Llano"})
    assert tool.read_po(po) == {
        "": "Content-Type: text/plain; charset=UTF-8\n",
        'Say "hi"\nnow': "",
        "Plain": "Llano",
    }
