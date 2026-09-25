"""The pieces of the redesigned screens (ARCHITECTURE §10): the «Next» band, the cards of
what is scheduled, choices shown as buttons and the countdown ring."""

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from powerclock.gui import style
from powerclock.gui.icons import TrayState
from powerclock.gui.summary import Item, Summary
from powerclock.i18n import _

# The tray's state → the colour of the band.
BAND_TONES: dict[TrayState, style.State] = {
    "idle": "neutral",
    "scheduled": "scheduled",
    "watching": "watching",
    "wake": "wake",
    "countdown": "countdown",
    "offline": "failed",
}


def state_word(state: style.State) -> str:
    words: dict[style.State, str] = {
        "scheduled": _("Scheduled"),
        "wake": _("Will turn on"),
        "watching": _("Watching"),
        "countdown": _("Countdown"),
        "done": _("Done"),
        "failed": _("Failed"),
        "neutral": _("Nothing scheduled"),
    }
    return words[state]


def scrollable(widget: QWidget) -> QScrollArea:
    """`widget` in a frameless vertical scroll area: a tall page still fits the window."""
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    widget.setAutoFillBackground(False)  # setWidget turns it on: keep the page's background
    area.viewport().setAutoFillBackground(False)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


# ── The «Next» band ──────────────────────────────────────────────────────────


class NextBand(QFrame):
    """What PowerClock will do next and when, in the colour of its state, with Cancel and
    Postpone when there is something to cancel, and Start when PowerClock isn't running."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("band")
        self.state: TrayState = "idle"
        self.symbol = QLabel()
        style.use_scale(self.symbol, 3)
        self.label = QLabel(_("Next").upper())
        style.use_scale(self.label, -1, bold=True)
        self.title = QLabel()
        style.use_scale(self.title, 2, bold=True)
        self.title.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setFont(style.tabular(self.detail.font()))
        self.cancel = QPushButton(_("Cancel"))
        self.postpone = QPushButton(_("Postpone 10 min"))
        self.postpone.setToolTip(_("Postpone 10 minutes"))
        self.start = QPushButton(_("Start PowerClock"))

        texts = QVBoxLayout()
        texts.setSpacing(style.SPACE[0])
        texts.addWidget(self.label)
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(style.SPACE[4], style.SPACE[3], style.SPACE[4], style.SPACE[3])
        layout.setSpacing(style.SPACE[3])
        layout.addWidget(self.symbol, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(texts, 1)
        for button in (self.postpone, self.cancel, self.start):
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.show_summary(Summary("idle", _("Nothing scheduled")))

    def show_summary(self, summary: Summary) -> None:
        self.state = summary.state
        tone = BAND_TONES[summary.state]
        colors = style.TONES[tone]
        self.setStyleSheet(
            style.band_style(tone)
            + f"QFrame#band QPushButton {{ color: {colors.on_fill}; background: transparent;"
            f" border: 1px solid {colors.on_fill}; border-radius: {style.SPACE[1]}px;"
            f" padding: {style.SPACE[1]}px {style.SPACE[3]}px; }}"
            f"QFrame#band QPushButton:focus {{ border-width: 2px; }}"
        )
        self.symbol.setText(colors.symbol)
        self.title.setText(summary.title or summary.headline)
        self.detail.setText(summary.detail)
        self.detail.setVisible(bool(summary.detail))
        self.cancel.setVisible(summary.can_cancel)
        self.postpone.setVisible(summary.can_postpone)
        self.start.setVisible(summary.state == "offline")
        self.setAccessibleName(f"{_('Next')}: {self.title.text()}. {summary.detail}")

    def show_remaining(self, text: str) -> None:
        """A countdown's tick: the seconds change, the rest stays."""
        if self.state == "countdown":
            self.detail.setText(text)


# ── Cards ─────────────────────────────────────────────────────────────────────


def item_state(item: Item) -> style.State:
    if item.counting_down:
        return "countdown"
    return "watching" if item.watched else "scheduled"


class ItemCard(QFrame):
    """One scheduled quick action: its state (colour, symbol and word), what and when, and
    its buttons."""

    def __init__(
        self,
        item: Item,
        cancel: Callable[[Item], None],
        postpone: Callable[[Item], None] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("card")
        state = item_state(item)
        self.setStyleSheet(style.card_style(state))
        self.badge = QLabel(style.badge(state, state_word(state)))
        style.use_scale(self.badge, -1, bold=True)
        palette = self.badge.palette()
        palette.setColor(self.badge.foregroundRole(), style.text_color(state))
        self.badge.setPalette(palette)
        self.name = QLabel(item.name)
        self.name.setWordWrap(True)
        style.use_scale(self.name, 0, bold=True)
        self.detail = QLabel(item.detail)
        self.detail.setWordWrap(True)
        self.detail.setFont(style.tabular(self.detail.font()))
        self.buttons: list[QPushButton] = []
        row = QHBoxLayout()
        row.addStretch(1)
        if postpone is not None:
            later = QPushButton(_("Postpone 10 min"))
            later.setToolTip(_("Postpone 10 minutes"))
            later.clicked.connect(lambda: postpone(item))
            self.buttons.append(later)
            row.addWidget(later)
        stop = QPushButton(_("Cancel"))
        stop.clicked.connect(lambda: cancel(item))
        self.buttons.append(stop)
        row.addWidget(stop)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(style.SPACE[3], style.SPACE[2], style.SPACE[2], style.SPACE[2])
        layout.setSpacing(style.SPACE[1])
        layout.addWidget(self.badge)
        layout.addWidget(self.name)
        layout.addWidget(self.detail)
        layout.addLayout(row)
        self.setAccessibleName(f"{state_word(state)}: {item.name}, {item.detail}")


# ── Choices as buttons ────────────────────────────────────────────────────────


class ChoiceButtons(QWidget):
    """One choice among a few, all visible as buttons (instead of a drop-down list). It
    answers like a QComboBox (currentData, findData, setCurrentIndex, currentIndexChanged)."""

    currentIndexChanged = Signal(int)

    def __init__(
        self,
        choices: Sequence[tuple[Any, str, QIcon | None]],
        *,
        columns: int,
        under_icon: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = [data for data, _label, _icon in choices]
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QToolButton] = []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(style.SPACE[1])
        tone = style.TONES["scheduled"]
        for index, (_data, label, icon) in enumerate(choices):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setAccessibleName(label)
            if icon is not None and not icon.isNull():
                button.setIcon(icon)
                button.setIconSize(QSize(style.SPACE[4], style.SPACE[4]))
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                if under_icon
                else Qt.ToolButtonStyle.ToolButtonTextOnly
            )
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            button.setStyleSheet(
                f"QToolButton {{ padding: {style.SPACE[1]}px; border: 1px solid palette(mid);"
                f" border-radius: {style.SPACE[1]}px; }}"
                f"QToolButton:checked {{ border: 2px solid {tone.fill};"
                f" background: {QColor(tone.fill).lighter(185).name()}; color: #141B2B; }}"
            )
            self.group.addButton(button, index)
            self.buttons.append(button)
            grid.addWidget(button, index // columns, index % columns)
        self.group.idToggled.connect(self._toggled)
        if self.buttons:
            self.buttons[0].setChecked(True)

    def count(self) -> int:
        return len(self._data)

    def currentIndex(self) -> int:
        return self.group.checkedId()

    def currentData(self) -> Any:
        index = self.currentIndex()
        return self._data[index] if index >= 0 else None

    def itemData(self, index: int) -> Any:
        return self._data[index]

    def findData(self, data: Any) -> int:
        return self._data.index(data) if data in self._data else -1

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def _toggled(self, index: int, checked: bool) -> None:
        if checked:
            self.currentIndexChanged.emit(index)


class WhenPicker(QWidget):
    """«When»: Now · At · In · When… (the last one opens a list of conditions)."""

    currentIndexChanged = Signal(int)

    def __init__(
        self,
        segments: Sequence[tuple[str, str]],
        conditions: Sequence[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._segments = [value for value, _label in segments]
        self._conditions = [value for value, _label in conditions]
        self.segments = ChoiceButtons(
            [(value, label, None) for value, label in segments],
            columns=len(segments),
            under_icon=False,
        )
        self.condition = QComboBox()
        for value, label in conditions:
            self.condition.addItem(label, value)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(style.SPACE[1])
        layout.addWidget(self.segments)
        layout.addWidget(self.condition)
        self.segments.currentIndexChanged.connect(self._changed)
        self.condition.currentIndexChanged.connect(self._changed)
        self._changed()

    @property
    def values(self) -> list[str]:
        return [*self._segments[:-1], *self._conditions]

    def currentData(self) -> str:
        segment = self.segments.currentData()
        return self.condition.currentData() if segment == self._segments[-1] else segment

    def findData(self, value: str) -> int:
        return self.values.index(value) if value in self.values else -1

    def setCurrentIndex(self, index: int) -> None:
        if index < 0:
            return
        value = self.values[index]
        if value in self._conditions:
            self.condition.setCurrentIndex(self._conditions.index(value))
            self.segments.setCurrentIndex(len(self._segments) - 1)
        else:
            self.segments.setCurrentIndex(self._segments.index(value))
        self._changed()

    def _changed(self, *_args: object) -> None:
        self.condition.setVisible(self.segments.currentData() == self._segments[-1])
        self.currentIndexChanged.emit(self.findData(self.currentData()))


# ── The countdown ring ────────────────────────────────────────────────────────


class Ring(QWidget):
    """A ring that empties as time passes, with the seconds in the middle: the number rules."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fraction = 1.0
        self.text = ""
        self.setFixedSize(style.RING, style.RING)
        self.setFont(style.tabular(style.scaled(self.font(), 3, bold=True)))

    def set(self, fraction: float, text: str) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.text = text
        self.setAccessibleName(text)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = style.SPACE[3] - style.SPACE[0]
        area = QRectF(self.rect()).adjusted(width, width, -width, -width)
        track = QPen(self.palette().mid().color(), width)
        painter.setPen(track)
        painter.drawEllipse(area)
        arc = QPen(style.text_color("countdown"), width)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(area, 90 * 16, round(-360 * 16 * self.fraction))
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        painter.end()
