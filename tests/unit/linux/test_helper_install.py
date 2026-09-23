from pathlib import Path

import pytest
from typer.testing import CliRunner

from kse.cli.main import app
from kse.platform.linux import helper


def test_install_commands(tmp_path: Path) -> None:
    rules = tmp_path / "50-kse-unattended.rules"
    commands = helper.install_commands(unattended_user=None, rules_file=rules)
    assert commands == [
        [
            "sudo", "install", "-D", "-o", "root", "-g", "root", "-m", "0755",
            str(helper.packaged("kse_helper_linux.py")), "/usr/local/libexec/kse-helper",
        ],
        [
            "sudo", "install", "-D", "-o", "root", "-g", "root", "-m", "0644",
            str(helper.packaged("org.kse.helper.policy")),
            "/usr/share/polkit-1/actions/org.kse.helper.policy",
        ],
    ]  # fmt: skip
    assert not rules.exists()


def test_unattended_rule_is_generated_for_the_user(tmp_path: Path) -> None:
    rules = tmp_path / "50-kse-unattended.rules"
    commands = helper.install_commands(unattended_user="pc", rules_file=rules)
    assert commands[-1][-2:] == [str(rules), "/etc/polkit-1/rules.d/50-kse-unattended.rules"]
    text = rules.read_text()
    assert 'subject.user !== "pc"' in text
    assert '"org.kse.helper.wake"' in text
    assert "@USER@" not in text


@pytest.mark.parametrize("user", ["root; rm -rf /", 'pc"', "Pc", "", "../x"])
def test_odd_user_names_are_refused(tmp_path: Path, user: str) -> None:
    with pytest.raises(ValueError, match="unexpected user name"):
        helper.install_commands(unattended_user=user, rules_file=tmp_path / "r")


def test_uninstall_commands() -> None:
    assert helper.uninstall_commands(helper_present=True) == [
        ["sudo", "/usr/local/libexec/kse-helper", "wake-clear"],
        [
            "sudo", "rm", "-f", "/usr/local/libexec/kse-helper",
            "/usr/share/polkit-1/actions/org.kse.helper.policy",
            "/etc/polkit-1/rules.d/50-kse-unattended.rules",
        ],
    ]  # fmt: skip
    assert len(helper.uninstall_commands(helper_present=False)) == 1


def test_run_all_stops_at_the_first_failure() -> None:
    ran: list[list[str]] = []

    def run(command: list[str]) -> int:
        ran.append(command)
        return 1 if command[0] == "b" else 0

    assert helper.run_all([["a"], ["b"], ["c"]], run) == ["b"]  # type: ignore[arg-type]
    assert ran == [["a"], ["b"]]
    assert helper.run_all([["a"]], lambda command: 0) is None


def test_policy_file() -> None:
    policy = helper.packaged("org.kse.helper.policy").read_text()
    assert '<action id="org.kse.helper.wake">' in policy
    assert "<allow_active>yes</allow_active>" in policy
    assert "<allow_any>auth_admin</allow_any>" in policy
    assert ">/usr/local/libexec/kse-helper</annotate>" in policy


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
    assert "Helper installed." in accepted.output
    assert "kse service install --linger" in accepted.output
    assert len(ran) == 3


def test_cli_reports_a_failed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(helper, "run_interactive", lambda command: 1)
    result = CliRunner().invoke(app, ["helper", "uninstall"], input="y\n")
    assert result.exit_code == 1
    assert "failed: sudo" in result.output
