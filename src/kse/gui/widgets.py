"""Small widgets shared by the tabs and the rule editor."""

from datetime import UTC, datetime, timedelta

import psutil
from PySide6.QtCore import QDateTime
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QComboBox, QDateTimeEdit, QLineEdit, QWidget

from kse.i18n import _
from kse.models import format_duration, parse_duration

INVALID_STYLE = "QLineEdit { border: 1px solid #da4453; }"


class _DurationValidator(QValidator):
    def __init__(self, allow_zero: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._allow_zero = allow_zero

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        cleaned = text.strip().replace(" ", "")
        if not cleaned:
            return QValidator.State.Intermediate, text, pos
        try:
            value = parse_duration(cleaned)
        except ValueError:
            # "1h3" may still become "1h30m": let the user go on typing
            ok = all(ch.isdigit() or ch in "dhms" for ch in cleaned)
            return (QValidator.State.Intermediate if ok else QValidator.State.Invalid), text, pos
        if value <= timedelta(0) and not self._allow_zero:
            return QValidator.State.Intermediate, text, pos
        return QValidator.State.Acceptable, text, pos


class DurationEdit(QLineEdit):
    """A duration written as in the rules: 30s, 5m, 2h, 1d or 1h30m."""

    def __init__(
        self, default: str = "", *, allow_zero: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(default, parent)
        self.setValidator(_DurationValidator(allow_zero, self))
        self.setPlaceholderText(_("e.g. 30s, 5m, 1h30m"))
        self.setToolTip(_("Durations: 30s, 5m, 2h, 1d or combined, such as 1h30m"))
        self.setMaximumWidth(140)
        self.textChanged.connect(self._mark)
        self._mark()

    def value(self) -> timedelta:
        """The duration; ValueError (with a message for the user) if it is not valid."""
        text = self.text().strip().replace(" ", "")
        if not self.hasAcceptableInput():
            raise ValueError(
                _("{text!r} is not a valid duration: use e.g. 30s, 5m or 1h30m").format(text=text)
            )
        return parse_duration(text)

    def set_value(self, value: timedelta | str) -> None:
        self.setText(value if isinstance(value, str) else format_duration(value))

    def _mark(self) -> None:
        self.setStyleSheet("" if self.hasAcceptableInput() or not self.text() else INVALID_STYLE)


class LocalDateTimeEdit(QDateTimeEdit):
    """A date and time shown in the computer's local time; `value()` is timezone-aware."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd HH:mm")

    def value(self) -> datetime:
        return datetime.fromtimestamp(self.dateTime().toSecsSinceEpoch(), UTC)

    def set_value(self, when: datetime) -> None:
        self.setDateTime(QDateTime.fromSecsSinceEpoch(round(when.timestamp())))


def next_quarter(after: timedelta = timedelta(hours=1)) -> datetime:
    """A round default time: `after` from now, up to the next quarter of an hour."""
    when = datetime.now(UTC) + after
    when = when.replace(second=0, microsecond=0)
    return when + timedelta(minutes=(15 - when.minute % 15) % 15)


class ProcessCombo(QComboBox):
    """A program name, typed or picked from the ones running now."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.lineEdit()
        assert line is not None
        line.setPlaceholderText(_("e.g. ffmpeg, or a PID"))
        self.setMinimumContentsLength(18)

    def showPopup(self) -> None:
        self.fill()
        super().showPopup()

    def fill(self) -> None:
        text = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(running_programs())
        self.setEditText(text)
        self.blockSignals(False)

    def value(self) -> str:
        return self.currentText().strip()


def running_programs() -> list[str]:
    """Names of the programs running for this user, sorted (the ones to wait for)."""
    try:
        user = psutil.Process().username()
        names = {
            p.info["name"]
            for p in psutil.process_iter(["name", "username"])
            if p.info["name"] and p.info["username"] == user
        }
    except psutil.Error:
        return []
    return sorted(names, key=str.lower)
