"""PowerClock's look on top of the desktop theme (ARCHITECTURE §10): the "night and dawn"
colours only mark states, the «Next» band and the main button; text grows by √φ per step and
things are spaced with Fibonacci numbers. Backgrounds, text and controls follow the desktop
(light or dark), and the font is the desktop's."""

from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from powerclock.platform import desktop_font

PHI = (1 + 5**0.5) / 2
STEP = PHI**0.5  # each text size is √φ times the previous one: every two steps, φ times
SPACE = (3, 5, 8, 13, 21, 34, 55, 89)  # 3-5 inside controls, 8-13 between items, 21-34 blocks
WINDOW = (987, 610)  # a golden rectangle of two Fibonacci numbers (987 / 610 = φ)
MAIN_SHARE = (618, 382)  # the Quick tab: form and what is scheduled, 61.8 / 38.2 %
RING = 144  # the countdown ring, px

State = Literal["scheduled", "wake", "watching", "countdown", "done", "failed", "neutral"]


@dataclass(frozen=True)
class Tone:
    fill: str  # bands, badges and the main button
    on_fill: str  # text on the fill
    light: str  # text and icons on a light theme (≥ 4.5:1 on white)
    dark: str  # on a dark theme (≥ 4.5:1 on #202326)
    symbol: str  # the state is never shown by colour alone


TONES: dict[State, Tone] = {
    "scheduled": Tone("#2F5FD0", "#FFFFFF", "#2F5FD0", "#8EAEF5", "◷"),  # Crepúsculo
    "wake": Tone("#E8A33D", "#2B1A00", "#8A4F00", "#F2B55C", "☀"),  # Alba
    "watching": Tone("#6A4FC7", "#FFFFFF", "#6A4FC7", "#B3A1F0", "◉"),  # Lavanda
    "countdown": Tone("#B33A0A", "#FFFFFF", "#B33A0A", "#F5926A", "◴"),  # Brasa
    "done": Tone("#177245", "#FFFFFF", "#177245", "#5CCB8F", "✔"),  # Hoja
    "failed": Tone("#B42323", "#FFFFFF", "#B42323", "#F28B8B", "✘"),  # Grana
    "neutral": Tone("#586379", "#FFFFFF", "#586379", "#A7B0C2", "⊘"),  # Pizarra
}

# A run's state (history) → its tone.
RUN_TONES: dict[str, State] = {
    "done": "done",
    "failed": "failed",
    "cancelled": "neutral",
    "skipped": "neutral",
    "running": "scheduled",
    "waiting": "watching",
    "warning": "countdown",
}


def dark_theme() -> bool:
    """The desktop uses a dark colour scheme (its window colour is dark)."""
    app = QGuiApplication.instance()
    if not isinstance(app, QGuiApplication):
        return False
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def text_color(state: State) -> QColor:
    tone = TONES[state]
    return QColor(tone.dark if dark_theme() else tone.light)


def badge(state: State, text: str) -> str:
    """ "✔ done": symbol and words, readable without colour."""
    return f"{TONES[state].symbol} {text}"


def scaled(font: QFont, step: int, *, bold: bool = False) -> QFont:
    """`font` `step` sizes up the φ scale (14 → 18 → 23 → 29 → 37 px; -1: 11 px)."""
    result = QFont(font)
    if font.pointSizeF() > 0:
        result.setPointSizeF(font.pointSizeF() * STEP**step)
    else:
        result.setPixelSize(round(font.pixelSize() * STEP**step))
    if bold:
        result.setWeight(QFont.Weight.DemiBold)
    return result


def use_scale(widget: QWidget, step: int, *, bold: bool = False) -> None:
    widget.setFont(scaled(widget.font(), step, bold=bold))


def tabular(font: QFont) -> QFont:
    """Digits of the same width, so a countdown does not wobble."""
    result = QFont(font)
    result.setFeature(QFont.Tag("tnum"), 1)
    return result


def primary(button: QPushButton, state: State = "scheduled") -> QPushButton:
    """The one highlighted button of a screen, with its verb and object."""
    tone = TONES[state]
    pad = f"{SPACE[1]}px {SPACE[3]}px"
    button.setStyleSheet(
        f"QPushButton {{ background: {tone.fill}; color: {tone.on_fill}; border: none;"
        f" border-radius: {SPACE[1]}px; padding: {pad}; font-weight: 600; }}"
        f"QPushButton:hover {{ background: {QColor(tone.fill).darker(112).name()}; }}"
        "QPushButton:focus { border: 2px solid palette(highlighted-text); }"
        "QPushButton:disabled { background: palette(mid); color: palette(window); }"
    )
    button.setProperty("primary", True)
    return button


def band_style(state: State) -> str:
    tone = TONES[state]
    return (
        f"QFrame#band {{ background: {tone.fill}; border-radius: {SPACE[2]}px; }}"
        f"QFrame#band QLabel {{ color: {tone.on_fill}; background: transparent; }}"
    )


def card_style(state: State) -> str:
    """A card: the theme's base colour with a stripe of the state's colour on the left."""
    tone = TONES[state]
    return (
        f"QFrame#card {{ background: palette(base); border: 1px solid palette(mid);"
        f" border-left: {SPACE[1]}px solid {tone.fill}; border-radius: {SPACE[1]}px; }}"
        "QFrame#card QLabel { background: transparent; border: none; }"
    )


def apply(app: QApplication) -> None:
    """The desktop's font (Qt from pip does not load Plasma's or GNOME's)."""
    found = desktop_font()
    if found is None:
        return
    family, points = found
    font = QFont(app.font())
    font.setFamily(family)
    font.setPointSizeF(points)
    app.setFont(font)
