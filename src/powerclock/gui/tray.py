"""The tray icon: what comes next at a glance, and the most common actions one click away."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from powerclock.gui.client import DaemonLink
from powerclock.gui.icons import themed, tray_icon
from powerclock.gui.summary import Summary, summarize
from powerclock.gui.tasks import spawn
from powerclock.i18n import _, power_action_label
from powerclock.platform.base import PowerAction

# Harmless actions act at once; the others keep the cancellable countdown.
NO_COUNTDOWN = {PowerAction.LOCK, PowerAction.SCREEN_OFF}
MENU_ACTIONS = (
    PowerAction.SHUTDOWN,
    PowerAction.REBOOT,
    PowerAction.SUSPEND,
    PowerAction.HIBERNATE,
    PowerAction.LOCK,
    PowerAction.LOGOUT,
    PowerAction.SCREEN_OFF,
)
ACTION_ICONS = {
    PowerAction.SHUTDOWN: "system-shutdown",
    PowerAction.REBOOT: "system-reboot",
    PowerAction.SUSPEND: "system-suspend",
    PowerAction.HIBERNATE: "system-suspend-hibernate",
    PowerAction.LOCK: "system-lock-screen",
    PowerAction.LOGOUT: "system-log-out",
    PowerAction.SCREEN_OFF: "video-display",
}


def quick_now(action: PowerAction) -> dict[str, Any]:
    payload: dict[str, Any] = {"action": action.value}
    if action in NO_COUNTDOWN:
        payload["warning"] = "0s"
    return payload


class Tray(QObject):
    def __init__(
        self,
        link: DaemonLink,
        *,
        show_window: Callable[[str | None], None],
        quit_app: Callable[[], None],
    ) -> None:
        super().__init__()
        self._link = link
        self._show_window = show_window
        self.icon = QSystemTrayIcon(tray_icon("offline"))
        self.menu = QMenu()
        self.headline = self.menu.addAction("")
        self.headline.setEnabled(False)
        self.cancel = self.menu.addAction(themed("dialog-cancel"), _("Cancel"))
        self.cancel.triggered.connect(lambda: spawn(link.api.post("/cancel")))
        self.postpone = self.menu.addAction(themed("chronometer"), _("Postpone 10 minutes"))
        self.postpone.triggered.connect(
            lambda: spawn(link.api.post("/postpone", json={"delay": "10m"}))
        )
        self.menu.addSeparator()
        self.now = self.menu.addMenu(_("Now"))
        self.actions: dict[PowerAction, QAction] = {}
        for action in MENU_ACTIONS:
            item = self.now.addAction(themed(ACTION_ICONS[action]), power_action_label(action))
            item.triggered.connect(lambda _=False, a=action: self._act_now(a))
            self.actions[action] = item
        schedule = self.menu.addAction(themed("chronometer-start"), _("Schedule…"))
        schedule.triggered.connect(lambda: show_window("quick"))
        self.menu.addSeparator()
        self.open = self.menu.addAction(themed("configure"), _("Open PowerClock"))
        self.open.triggered.connect(lambda: show_window(None))
        leave = self.menu.addAction(
            themed("application-exit"), _("Hide the icon (PowerClock keeps working)")
        )
        leave.setToolTip(_("Your rules keep running in the background."))
        leave.triggered.connect(quit_app)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        link.changed.connect(self.update)
        link.event.connect(self._on_event)
        self.summary: Summary = summarize(False, {})
        self.update()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def update(self) -> None:
        self.summary = summary = summarize(self._link.online, self._link.pending)
        self.icon.setIcon(tray_icon(summary.state))
        tooltip = f"PowerClock\n{summary.headline}"
        if summary.upcoming > 1:
            tooltip += "\n" + _("{count} scheduled in total").format(count=summary.upcoming)
        self.icon.setToolTip(tooltip)
        self.headline.setText(summary.headline)
        self.cancel.setEnabled(summary.can_cancel)
        self.postpone.setEnabled(summary.can_postpone)
        self.now.setEnabled(self._link.online)

    def _on_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "tick" and self.summary.countdown is not None:
            text = _("{rule}: acts in {seconds} s").format(
                rule=self.summary.countdown["rule_name"], seconds=event["data"]["remaining"]
            )
            self.icon.setToolTip(f"PowerClock\n{text}")
            self.headline.setText(text)

    def _act_now(self, action: PowerAction) -> None:
        spawn(self._link.api.post("/quick", json=quick_now(action)))

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # left click
            self._show_window(None)
