"""Translatable user-facing text (catalogues in locale/, see scripts/i18n.py), and the phrases
built around a power action, which each language words in its own way."""

import gettext
from pathlib import Path

from powerclock.platform.base import PowerAction

_translation = gettext.translation(
    "powerclock", localedir=Path(__file__).parent / "locale", fallback=True
)


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


def schedule_label(action: PowerAction | None) -> str:
    """The Quick tab's button when the action waits for a moment ("Schedule shutdown")."""
    labels = {
        PowerAction.SHUTDOWN: _("Schedule shutdown"),
        PowerAction.REBOOT: _("Schedule restart"),
        PowerAction.SUSPEND: _("Schedule suspend"),
        PowerAction.HIBERNATE: _("Schedule hibernation"),
        PowerAction.HYBRID_SLEEP: _("Schedule hybrid sleep"),
        PowerAction.LOCK: _("Schedule screen lock"),
        PowerAction.LOGOUT: _("Schedule log out"),
        PowerAction.SCREEN_OFF: _("Schedule screen off"),
    }
    return labels[action] if action is not None else _("Schedule the program")


def now_label(action: PowerAction | None) -> str:
    """The Quick tab's button when the action is for now ("Shut down now")."""
    labels = {
        PowerAction.SHUTDOWN: _("Shut down now"),
        PowerAction.REBOOT: _("Restart now"),
        PowerAction.SUSPEND: _("Suspend now"),
        PowerAction.HIBERNATE: _("Hibernate now"),
        PowerAction.HYBRID_SLEEP: _("Hybrid sleep now"),
        PowerAction.LOCK: _("Lock the screen now"),
        PowerAction.LOGOUT: _("Log out now"),
        PowerAction.SCREEN_OFF: _("Turn off the screen now"),
    }
    return labels[action] if action is not None else _("Run now")


def countdown_sentence(action: PowerAction | None, seconds: int) -> str:
    """What is about to happen, as a sentence: "The computer will shut down in 42 s"."""
    sentences = {
        PowerAction.SHUTDOWN: _("The computer will shut down in {seconds} s"),
        PowerAction.REBOOT: _("The computer will restart in {seconds} s"),
        PowerAction.SUSPEND: _("The computer will suspend in {seconds} s"),
        PowerAction.HIBERNATE: _("The computer will hibernate in {seconds} s"),
        PowerAction.HYBRID_SLEEP: _("The computer will go into hybrid sleep in {seconds} s"),
        PowerAction.LOCK: _("The screen will lock in {seconds} s"),
        PowerAction.LOGOUT: _("Your session will close in {seconds} s"),
        PowerAction.SCREEN_OFF: _("The screen will turn off in {seconds} s"),
    }
    text = sentences[action] if action is not None else _("PowerClock will act in {seconds} s")
    return text.format(seconds=seconds)


def can_cancel_text() -> str:
    return _("You can cancel it until the last second.")
