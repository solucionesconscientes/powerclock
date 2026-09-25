from pathlib import Path

import pytest
from typer.testing import CliRunner

from powerclock.cli.main import app
from powerclock.platform.linux import helper


def test_install_commands(tmp_path: Path) -> None:
    rules = tmp_path / "50-powerclock-unattended.rules"
    commands = helper.install_commands(unattended_user=None, rules_file=rules, managers=["sddm"])
    assert commands == [
        [
            "sudo", "install", "-D", "-o", "root", "-g", "root", "-m", "0755",
            str(helper.packaged("powerclock_helper_linux.py")),
            "/usr/local/libexec/powerclock-helper",
        ],
        [
            "sudo", "install", "-D", "-o", "root", "-g", "root", "-m", "0644",
            str(helper.packaged("org.powerclock.helper.policy")),
            "/usr/share/polkit-1/actions/org.powerclock.helper.policy",
        ],
        [
            "sudo", "install", "-D", "-o", "root", "-g", "root", "-m", "0644",
            str(helper.packaged("powerclock-boot.service")),
            "/etc/systemd/system/powerclock-boot.service",
        ],
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", "powerclock-boot.service"],
        ["sudo", "mkdir", "-p", "/etc/sddm.conf.d"],
        ["sudo", "ln", "-sfn", "/run/powerclock/sddm.conf", "/etc/sddm.conf.d/zz-powerclock.conf"],
    ]  # fmt: skip
    assert not rules.exists()


def test_unattended_rule_is_generated_for_the_user(tmp_path: Path) -> None:
    rules = tmp_path / "50-powerclock-unattended.rules"
    commands = helper.install_commands(unattended_user="pc", rules_file=rules, managers=[])
    assert commands[2][-2:] == [str(rules), "/etc/polkit-1/rules.d/50-powerclock-unattended.rules"]
    text = rules.read_text()
    assert 'subject.user !== "pc"' in text
    assert '"org.powerclock.helper.wake"' in text
    assert "@USER@" not in text


def test_display_managers(tmp_path: Path) -> None:
    assert helper.display_managers(tmp_path) == []
    (tmp_path / "etc/sddm.conf.d").mkdir(parents=True)
    (tmp_path / "etc/lightdm").mkdir()
    assert helper.display_managers(tmp_path) == ["sddm", "lightdm"]
    commands = helper.install_commands(
        unattended_user=None, rules_file=tmp_path / "r", managers=["lightdm"]
    )
    assert commands[-1] == [
        "sudo", "ln", "-sfn", "/run/powerclock/lightdm.conf",
        "/etc/lightdm/lightdm.conf.d/99-powerclock.conf",
    ]  # fmt: skip


@pytest.mark.parametrize("user", ["root; rm -rf /", 'pc"', "Pc", "", "../x"])
def test_odd_user_names_are_refused(tmp_path: Path, user: str) -> None:
    with pytest.raises(ValueError, match="unexpected user name"):
        helper.install_commands(unattended_user=user, rules_file=tmp_path / "r")


def test_uninstall_commands() -> None:
    assert helper.uninstall_commands(helper_present=True) == [
        ["sudo", "/usr/local/libexec/powerclock-helper", "wake-clear"],
        [
            "sudo", "rm", "-rf", "/usr/local/libexec/powerclock-helper",
            "/usr/share/polkit-1/actions/org.powerclock.helper.policy",
            "/etc/polkit-1/rules.d/50-powerclock-unattended.rules",
            "/etc/systemd/system/powerclock-boot.service",
            "/etc/systemd/system/graphical.target.wants/powerclock-boot.service",
            "/etc/sddm.conf.d/zz-powerclock.conf",
            "/etc/lightdm/lightdm.conf.d/99-powerclock.conf",
            "/var/lib/powerclock",
            "/run/powerclock",
        ],
        ["sudo", "systemctl", "daemon-reload"],
    ]  # fmt: skip
    assert len(helper.uninstall_commands(helper_present=False)) == 2


def test_run_all_stops_at_the_first_failure() -> None:
    ran: list[list[str]] = []

    def run(command: list[str]) -> int:
        ran.append(command)
        return 1 if command[0] == "b" else 0

    assert helper.run_all([["a"], ["b"], ["c"]], run) == ["b"]  # type: ignore[arg-type]
    assert ran == [["a"], ["b"]]
    assert helper.run_all([["a"]], lambda command: 0) is None


def test_policy_file() -> None:
    policy = helper.packaged("org.powerclock.helper.policy").read_text()
    assert '<action id="org.powerclock.helper.wake">' in policy
    assert "<allow_active>yes</allow_active>" in policy
    assert "<allow_any>auth_admin</allow_any>" in policy
    assert ">/usr/local/libexec/powerclock-helper</annotate>" in policy


def test_cli_prints_and_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(helper, "run_interactive", lambda command: ran.append(command) or 0)
    runner = CliRunner()

    printed = runner.invoke(app, ["helper", "install", "--print"])
    assert printed.exit_code == 0
    assert "sudo install -D -o root -g root -m 0755" in printed.output
    assert ran == []

    refused = runner.invoke(app, ["helper", "install"], input="n\n")
    assert "Nothing done" in refused.output
    assert ran == []

    accepted = runner.invoke(app, ["helper", "install", "--unattended"], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert "Done: PowerClock can turn the computer on." in accepted.output
    assert "powerclock service install --linger" in accepted.output
    assert ran[0][:3] == ["sudo", "install", "-D"]
    assert ["sudo", "systemctl", "enable", "powerclock-boot.service"] in ran


def test_cli_reports_a_failed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "run_interactive", lambda command: 1)
    result = CliRunner().invoke(app, ["helper", "uninstall"], input="y\n")
    assert result.exit_code == 1
    assert "failed: sudo" in result.output
