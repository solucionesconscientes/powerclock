"""Electricity: the tariff (for the tariff_period condition) and the consumption and price
used to estimate what PowerClock saves (the summary at the top of the History tab)."""

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

from powerclock.gui.client import DaemonLink
from powerclock.gui.tasks import spawn
from powerclock.i18n import _
from powerclock.labels import savings_text


class EnergyBox(QGroupBox):
    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(_("Electricity"), parent)
        self._link = link
        self._loading = False
        self.tariff = QComboBox()
        self.tariff.addItem(_("No time-of-use prices"), None)
        self.tariff.addItem(_("Spain 2.0TD (peak, flat, valley)"), "es-2.0td")
        self.tariff.setToolTip(
            _("Only for contracts with a different price by hour (PVPC or three periods).")
        )
        self.tariff.activated.connect(lambda _index: self._save())
        self.watts = _spin(0, 5000, 0, " W")
        self.watts.setToolTip(_("What the computer uses when it is on (typical: 15 W a laptop)."))
        self.price = _spin(0, 10, 3, "")
        self.price.setToolTip(_("What you pay for a kWh (look at your bill)."))
        for spin in (self.watts, self.price):
            spin.editingFinished.connect(self._save)
        layout = QFormLayout(self)
        layout.addRow(_("Tariff:"), self.tariff)
        layout.addRow(_("Consumption when on:"), self.watts)
        layout.addRow(_("Price of a kWh:"), self.price)

    def reload(self) -> None:
        spawn(self._load(), self)

    async def _load(self) -> None:
        self.show_settings(await self._link.api.get("/settings"))

    def show_settings(self, settings: dict[str, Any]) -> None:
        self._loading = True
        try:
            self.tariff.setCurrentIndex(max(0, self.tariff.findData(settings.get("tariff"))))
            self.watts.setValue(settings.get("watts") or 0)
            self.price.setValue(settings.get("price_kwh") or 0)
            self.price.setSuffix(f" {settings.get('currency', '€')}")
        finally:
            self._loading = False

    def values(self) -> dict[str, Any]:
        return {
            "tariff": self.tariff.currentData(),
            "watts": self.watts.value() or None,  # 0: the typical value
            "price_kwh": self.price.value() or None,
        }

    def _save(self) -> None:
        if not self._loading:
            spawn(self._send(self.values()), self)

    async def _send(self, values: dict[str, Any]) -> None:
        await self._link.api.request("PATCH", "/settings", json=values)
        self._link.refresh()


class SavingsLabel(QLabel):
    """Time on and off in the last 30 days and what PowerClock saved."""

    def __init__(self, link: DaemonLink, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._link = link
        self.setWordWrap(True)

    def reload(self) -> None:
        spawn(self._load(), self)

    async def _load(self) -> None:
        self.setText(savings_text(await self._link.api.get("/stats", params={"days": 30})))


def _spin(low: float, high: float, decimals: int, suffix: str) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setSpecialValueText(_("Typical"))  # shown at 0: the estimate uses a typical value
    return spin
