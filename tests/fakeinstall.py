"""Fake per-OS install modules (service, desktop entries, wake helper) that only record."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ServiceState:
    installed: bool


class FakeService:
    def __init__(self, installed: bool = False) -> None:
        self.installed = installed
        self.calls: list[tuple[str, Any]] = []

    def status(self) -> ServiceState:
        return ServiceState(self.installed)

    def start(self) -> list[str]:
        self.calls.append(("start", None))
        return ["started"]

    def restart(self) -> list[str]:
        self.calls.append(("restart", None))
        return ["restarted"]

    def install(self, *, dry_run: bool, linger_user: str | None = None) -> list[str]:
        self.calls.append(("install", (dry_run, linger_user)))
        self.installed = True
        return ["service installed"]

    def uninstall(self) -> list[str]:
        self.calls.append(("uninstall", None))
        self.installed = False
        return ["service removed"]


class FakeDesktop:
    def __init__(self) -> None:
        self.menu = False
        self.login = False

    def in_menu(self) -> bool:
        return self.menu

    def at_login(self) -> bool:
        return self.login

    def set_menu(self, on: bool) -> list[str]:
        self.menu = on
        return [f"menu {'on' if on else 'off'}"]

    def set_login(self, on: bool) -> list[str]:
        self.login = on
        return [f"login {'on' if on else 'off'}"]


class FakeHelper:
    """Like platform/linux/helper.py, without touching the system."""

    def __init__(self, present: bool = False) -> None:
        self.HELPER = Path(
            "/nonexistent/powerclock-helper-present" if present else "/nonexistent/x"
        )
        self.present = present
        self.install_calls: list[dict[str, Any]] = []

    def install_commands(self, *, unattended_user: str | None, rules_file: Path) -> list[list[str]]:
        self.install_calls.append({"user": unattended_user, "rules_file": rules_file})
        commands = [["sudo", "install", "helper"], ["sudo", "install", "policy"]]
        if unattended_user:
            commands.append(["sudo", "install", f"rules-for-{unattended_user}"])
        return commands

    def uninstall_commands(self, helper_present: bool) -> list[list[str]]:
        return [["sudo", "rm", "-f", "helper", "policy", "rules"]]

    def elevated(self, commands: list[list[str]]) -> list[str]:
        return ["pkexec", "/bin/sh", "-c", " && ".join(" ".join(c[1:]) for c in commands)]

    def shell(self, command: list[str]) -> str:
        return " ".join(command)
