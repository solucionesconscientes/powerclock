"""Translatable user-facing text. The es/en catalogues arrive with the GUI (roadmap M7)."""

import gettext
from pathlib import Path

from kse.platform.base import PowerAction

_translation = gettext.translation("kse", localedir=Path(__file__).parent / "locale", fallback=True)


def _(message: str) -> str:
    return _translation.gettext(message)


def power_action_label(action: PowerAction) -> str:
    labels = {
        PowerAction.SHUTDOWN: _("Shut down"),
        PowerAction.REBOOT: _("Restart"),
        PowerAction.SUSPEND: _("Suspend"),
        PowerAction.HIBERNATE: _("Hibernate"),
        PowerAction.HYBRID_SLEEP: _("Hybrid sleep"),
        PowerAction.LOCK: _("Lock the screen"),
        PowerAction.LOGOUT: _("Log out"),
        PowerAction.SCREEN_OFF: _("Turn off the screen"),
    }
    return labels[action]
