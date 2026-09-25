"""The redesign (M14): colours, sizes, the «Next» band, cards, choice buttons and the ring."""

from datetime import UTC, datetime
from typing import Any

import pytest
from PySide6.QtGui import QFont

from powerclock.gui import style
from powerclock.gui.cards import ChoiceButtons, ItemCard, NextBand, Ring, WhenPicker
from powerclock.gui.summary import Item, summarize

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


def contrast(a: str, b: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("state", list(style.TONES))
def test_every_state_reads_well_in_light_and_dark(state: style.State) -> None:
    tone = style.TONES[state]
    assert contrast(tone.light, "#FFFFFF") >= 4.5
    assert contrast(tone.light, "#EFF0F1") >= 4.5  # Breeze light window
    assert contrast(tone.dark, "#202326") >= 4.5  # Breeze dark window
    assert contrast(tone.dark, "#141B2B") >= 4.5  # Medianoche
    assert contrast(tone.on_fill, tone.fill) >= 4.5
    assert tone.symbol  # never by colour alone


def test_phi_scale_and_golden_window(qapp: object) -> None:
    base = QFont()
    base.setPixelSize(14)
    sizes = [style.scaled(base, step).pixelSize() for step in range(-1, 5)]
    assert sizes == [11, 14, 18, 23, 29, 37]
    width, height = style.WINDOW
    assert width / height == pytest.approx(style.PHI, abs=0.001)
    assert style.MAIN_SHARE[0] / style.MAIN_SHARE[1] == pytest.approx(style.PHI, abs=0.01)


def pending(**parts: Any) -> dict[str, Any]:
    return {"next": [], "active": [], "watching": [], "wake": None, **parts}


def test_band_states() -> None:
    wake = {"at": "2026-09-25T05:28:00Z"}
    shutdown = {"rule_id": "quick-1", "name": "Shut down", "at": "2026-09-24T21:30:00Z"}
    scheduled = summarize(True, pending(next=[shutdown], wake=wake), NOW)
    assert (scheduled.state, scheduled.title) == ("scheduled", "Shut down")
    assert "in 13h 30m" in scheduled.detail
    assert "turns the computer back on" in scheduled.detail
    waking = summarize(True, pending(wake=wake), NOW)
    assert (waking.state, waking.title) == ("wake", "Turn the computer on")
    watch = {
        "rule_id": "quick-2",
        "name": "Suspend after 20m without use",
        "trigger": {"type": "idle", "for": "20m"},
        "value": 65.0,
        "measured": None,
    }
    watching = summarize(True, pending(watching=[watch]), NOW)
    assert (watching.state, watching.title) == ("watching", "Suspend after 20m without use")
    run = {"id": "r", "rule_id": "quick-3", "rule_name": "Restart", "state": "warning"}
    run["deadline"] = "2026-09-24T08:00:42Z"
    counting = summarize(True, pending(active=[run]), NOW)
    assert counting.detail.startswith("acts in 42 s · You can cancel")
    idle = summarize(True, pending(), NOW)
    assert (idle.state, idle.detail) == ("idle", "Nothing will turn off or on by itself.")


async def test_next_band(qapp: object) -> None:
    band = NextBand()
    shutdown = {"rule_id": "quick-1", "name": "Shut down", "at": "2026-09-24T21:30:00Z"}
    band.show_summary(summarize(True, pending(next=[shutdown]), NOW))
    assert (band.state, band.title.text(), band.symbol.text()) == ("scheduled", "Shut down", "◷")
    assert not band.cancel.isHidden()
    assert not band.postpone.isHidden()
    assert band.start.isHidden()
    assert "Shut down" in band.accessibleName()
    band.show_summary(summarize(False, {}, NOW))
    assert band.state == "offline"
    assert band.cancel.isHidden()
    assert not band.start.isHidden()
    assert "#B42323" in band.styleSheet()  # Grana: something is wrong


async def test_cards_say_their_state_in_words(qapp: object) -> None:
    calls: list[str] = []
    item = Item("quick-1", "Suspend", "idle for 5m", watched=True)
    card = ItemCard(item, lambda i: calls.append("cancel " + i.rule_id), None)
    assert card.badge.text() == "◉ Watching"
    assert [button.text() for button in card.buttons] == ["Cancel"]
    card.buttons[0].click()
    assert calls == ["cancel quick-1"]
    assert "#6A4FC7" in card.styleSheet()


async def test_choice_buttons_answer_like_a_combo(qapp: object) -> None:
    picked: list[int] = []
    choices = ChoiceButtons([("a", "A", None), ("b", "B", None), ("c", "C", None)], columns=3)
    choices.currentIndexChanged.connect(picked.append)
    assert (choices.count(), choices.currentData(), choices.findData("c")) == (3, "a", 2)
    choices.setCurrentIndex(2)
    assert (choices.currentIndex(), choices.currentData(), picked) == (2, "c", [2])
    choices.buttons[1].click()
    assert choices.currentData() == "b"
    assert choices.findData("zzz") == -1


async def test_when_picker_opens_the_conditions(qapp: object) -> None:
    when = WhenPicker(
        [("now", "Now"), ("at", "At"), ("when", "When…")], [("idle", "Idle"), ("cpu", "CPU")]
    )
    assert (when.currentData(), when.condition.isHidden()) == ("now", True)
    when.setCurrentIndex(when.findData("cpu"))
    assert (when.currentData(), when.condition.isHidden()) == ("cpu", False)
    assert when.segments.currentData() == "when"
    when.setCurrentIndex(when.findData("at"))
    assert (when.currentData(), when.condition.isHidden()) == ("at", True)


async def test_ring(qapp: object) -> None:
    ring = Ring()
    assert (ring.width(), ring.height()) == (style.RING, style.RING)
    ring.set(1.4, "42 s")
    assert (ring.fraction, ring.text, ring.accessibleName()) == (1.0, "42 s", "42 s")
    ring.set(-1, "0 s")
    assert ring.fraction == 0.0
    ring.grab()  # paints without errors
