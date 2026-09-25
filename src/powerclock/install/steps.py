"""Setting PowerClock up in a session, and taking it out: the same steps on every OS, done by
the per-OS modules (service, wake helper, menu entry and login start).

Everything happens in the user's own folders except the wake helper, which needs the
administrator password once. The caller decides how to get it (sudo in a terminal, pkexec
from the GUI) by passing `run_root`, which runs a list of commands as root.
"""

import getpass
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

from powerclock.config import Paths
from powerclock.i18n import _
from powerclock.install.autostart import desktop_module
from powerclock.install.helper import helper_module
from powerclock.install.service import service_module
from powerclock.platform.base import NotSupported

Command = list[str]
RunRoot = Callable[[list[Command]], bool]  # True if every command succeeded


@dataclass(frozen=True)
class Options:
    menu: bool = True  # an entry in the applications menu
    login: bool = True  # the tray icon when the session starts
    helper: bool = True  # turn the computer on at a time (needs the password once)
    unattended: bool = False  # …and act with nobody logged in (linger + polkit rule)
    dry_run: bool = False  # the service only logs power actions (testing)


@dataclass
class Report:
    done: list[str]
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def _module(factory: Callable[[], ModuleType]) -> ModuleType | None:
    try:
        return factory()
    except NotSupported:
        return None


class Setup:
    def __init__(
        self,
        *,
        service: ModuleType | None = None,
        helper: ModuleType | None = None,
        desktop: ModuleType | None = None,
        paths: Paths | None = None,
        user: str | None = None,
    ) -> None:
        self.service = service or _module(service_module)
        self.helper = helper or _module(helper_module)
        self.desktop = desktop or _module(desktop_module)
        self.paths = paths or Paths.default()
        self.user = user or getpass.getuser()

    # ── What needs root ───────────────────────────────────────────────────────

    def root_install(self, options: Options) -> list[Command]:
        """The commands that install the wake helper (empty if not wanted or not here)."""
        if not options.helper or self.helper is None:
            return []
        rules_file = self.paths.data / "50-powerclock-unattended.rules"
        user = self.user if options.unattended else None
        commands: list[Command] = self.helper.install_commands(
            unattended_user=user, rules_file=rules_file
        )
        return commands

    def root_uninstall(self) -> list[Command]:
        if self.helper is None:
            return []
        commands: list[Command] = self.helper.uninstall_commands(
            helper_present=self.helper.HELPER.exists()
        )
        return commands

    # ── The steps ─────────────────────────────────────────────────────────────

    def install(self, options: Options, run_root: RunRoot) -> Report:
        """What does not need the password first; the helper last, so that cancelling the
        password dialog leaves everything else working."""
        report = Report(done=[], problems=[])
        desktop = self.desktop
        if desktop is not None:
            menu, login = options.menu, options.login
            self._step(
                report,
                _("In the applications menu") if menu else None,
                _("applications menu"),
                lambda: desktop.set_menu(menu),
            )
            self._step(
                report,
                _("Tray icon when the session starts") if login else None,
                _("start with the session"),
                lambda: desktop.set_login(login),
            )
        service = self.service
        if service is None:
            report.problems.append(_("the background service is not available on this system"))
        else:
            linger = self.user if options.unattended else None
            done = (
                _("Running in the background, also with the session closed")
                if linger
                else _("Running in the background")
            )
            self._step(
                report,
                done,
                _("background service"),
                lambda: service.install(dry_run=options.dry_run, linger_user=linger),
            )
        commands = self.root_install(options)
        if commands:
            if run_root(commands):
                report.done.append(_("PowerClock can turn the computer on"))
            else:
                report.problems.append(
                    _(
                        "PowerClock cannot turn the computer on yet (was the password "
                        "cancelled?): allow it later from Diagnostics"
                    )
                )
        return report

    def uninstall(self, run_root: RunRoot, *, remove_data: bool = False) -> Report:
        """Take PowerClock out of the session. Rules and history stay unless `remove_data`."""
        report = Report(done=[], problems=[])
        service, desktop = self.service, self.desktop
        if service is not None:
            self._step(
                report, _("Background service removed"), _("background service"), service.uninstall
            )
        if desktop is not None:
            self._step(
                report,
                _("Out of the applications menu"),
                _("applications menu"),
                lambda: desktop.set_menu(False),
            )
            self._step(
                report,
                _("No longer starts with the session"),
                _("start with the session"),
                lambda: desktop.set_login(False),
            )
        commands = self.root_uninstall()
        if commands:
            if run_root(commands):
                report.done.append(_("Permission to turn the computer on removed"))
            else:
                report.problems.append(_("the permission to turn the computer on was not removed"))
        if remove_data:
            for folder in {self.paths.config, self.paths.data}:
                if folder.exists():
                    shutil.rmtree(folder)
            report.done.append(_("Rules and history deleted"))
        return report

    @staticmethod
    def _step(report: Report, done: str | None, name: str, action: Callable[[], object]) -> None:
        """Run a step; `done` (None: say nothing) is what the user reads when it works."""
        try:
            action()
        except Exception as exc:
            report.problems.append(f"{name}: {exc}")
            return
        if done is not None:
            report.done.append(done)
