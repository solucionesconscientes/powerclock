"""The gallery: ready-made rules by use case. Pick one and the rule editor opens with it, to
adjust and save."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from powerclock import gallery
from powerclock.gui import forms, style
from powerclock.gui.cards import scrollable
from powerclock.gui.icons import app_icon
from powerclock.i18n import _


class TemplateCard(QFrame):
    def __init__(self, template: gallery.Template, use: "GalleryDialog") -> None:
        super().__init__()
        self.template = template
        self.setObjectName("card")
        self.setStyleSheet(style.card_style("scheduled"))
        title = QLabel(template.title)
        title.setWordWrap(True)
        style.use_scale(title, 1, bold=True)
        text = QLabel(template.description)
        text.setWordWrap(True)
        self.button = style.primary(QPushButton(_("Use this")))
        self.button.clicked.connect(lambda: use.choose(template))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(style.SPACE[3], style.SPACE[2], style.SPACE[3], style.SPACE[2])
        layout.setSpacing(style.SPACE[1])
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addLayout(row)
        self.setAccessibleName(f"{template.title}. {template.description}")


class GalleryDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Gallery of rules"))
        self.setWindowIcon(app_icon())
        self.chosen: gallery.Template | None = None
        tariff = bool(forms.SETTINGS.get("tariff"))
        self.templates = [t for t in gallery.templates() if t.needs != "tariff" or tariff]
        self.groups = QListWidget()
        for key, name in gallery.groups():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.groups.addItem(item)
        self.groups.setFixedWidth(style.SPACE[7] * 2 + style.SPACE[5])
        self.cards: list[TemplateCard] = []
        self._column = QVBoxLayout()
        self._column.setSpacing(style.SPACE[2])
        column = QWidget()
        outer = QVBoxLayout(column)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._column)
        outer.addStretch(1)
        intro = QLabel(_("Pick a starting point: you can change everything before saving."))
        intro.setWordWrap(True)
        body = QHBoxLayout()
        body.setSpacing(style.SPACE[3])
        body.addWidget(self.groups)
        body.addWidget(scrollable(column), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self.resize(style.WINDOW[0] * 3 // 4, style.WINDOW[1])
        self.groups.currentRowChanged.connect(self.show_group)
        self.groups.setCurrentRow(0)

    def show_group(self, row: int) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        key = self.groups.item(row).data(Qt.ItemDataRole.UserRole) if row >= 0 else None
        self.cards = [TemplateCard(t, self) for t in self.templates if t.group == key]
        for card in self.cards:
            self._column.addWidget(card)

    def choose(self, template: gallery.Template) -> None:
        self.chosen = template
        self.accept()
