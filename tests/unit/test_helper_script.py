"""The root helper, exercised on temporary files (never the real /sys/class/rtc)."""

import os
import stat
from pathlib import Path

import pytest

from kse.helper import kse_helper_linux as helper

NOW = 1_790_000_000


@pytest.fixture
def rtc(tmp_path: Path) -> Path:
    alarm = tmp_path / "wakealarm"
    alarm.write_text("")
    return alarm


def fake_rtcwake(tmp_path: Path, exit_code: int = 0) -> Path:
    """A stand-in for rtcwake that records its arguments."""
    script = tmp_path / "rtcwake"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/rtcwake.log"\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def run(argv: list[str], rtc: Path, **kwargs: object) -> int:
    return helper.main(argv, now=NOW, wakealarm=rtc, **kwargs)  # type: ignore[arg-type]


def test_wake_set_uses_rtcwake(tmp_path: Path, rtc: Path) -> None:
    rtcwake = fake_rtcwake(tmp_path)
    assert run(["wake-set", str(NOW + 3600)], rtc, rtcwake=rtcwake) == 0
    assert (tmp_path / "rtcwake.log").read_text() == f"-m no -t {NOW + 3600}\n"
    assert rtc.read_text() == ""  # sysfs untouched


def test_sysfs_fallback_writes_a_relative_value(tmp_path: Path, rtc: Path) -> None:
    broken = fake_rtcwake(tmp_path, exit_code=1)
    assert run(["wake-set", str(NOW + 120)], rtc, rtcwake=broken) == 0
    assert rtc.read_text() == "+120"
    missing = tmp_path / "no-rtcwake"
    assert run(["wake-set", str(NOW + 60)], rtc, rtcwake=missing) == 0
    assert rtc.read_text() == "+60"


def test_wake_clear(tmp_path: Path, rtc: Path) -> None:
    assert run(["wake-clear"], rtc, rtcwake=fake_rtcwake(tmp_path)) == 0
    assert (tmp_path / "rtcwake.log").read_text() == "-m disable\n"
    rtc.write_text("1790000100")
    assert run(["wake-clear"], rtc, rtcwake=tmp_path / "no-rtcwake") == 0
    assert rtc.read_text() == "0"


@pytest.mark.parametrize(
    "argument",
    [
        str(NOW),  # now is not the future
        str(NOW + 4),  # too soon
        str(NOW + 367 * 86400),  # more than a year ahead
        "-5",
        "1e9",
        "12 ",
        "$(reboot)",
        "1790000100; rm -rf /",
        "9" * 13,
    ],
)
def test_wake_set_rejects(
    tmp_path: Path, rtc: Path, argument: str, capsys: pytest.CaptureFixture[str]
) -> None:
    rtcwake = fake_rtcwake(tmp_path)
    assert run(["wake-set", argument], rtc, rtcwake=rtcwake) == helper.EXIT_USAGE
    assert not (tmp_path / "rtcwake.log").exists()
    assert "kse-helper:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [[], ["wake-set"], ["wake-set", "1", "2"], ["shutdown"], ["wake-get", "x"]]
)
def test_usage(rtc: Path, argv: list[str]) -> None:
    assert run(argv, rtc) == helper.EXIT_USAGE


def test_wake_get(rtc: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    adjtime = tmp_path / "adjtime"
    assert run(["wake-get"], rtc, adjtime=adjtime) == 0
    assert capsys.readouterr().out == "none\n"
    rtc.write_text("1790003600\n")
    adjtime.write_text("0.0 0 0.0\n0\nUTC\n")
    assert run(["wake-get"], rtc, adjtime=adjtime) == 0
    assert capsys.readouterr().out == "1790003600\n"


def test_wake_get_converts_a_local_time_rtc(
    rtc: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TZ", "Europe/Madrid")
    helper.time.tzset()
    try:
        adjtime = tmp_path / "adjtime"
        adjtime.write_text("0.0 0 0.0\n0\nLOCAL\n")
        rtc.write_text(str(1790003600 + 2 * 3600))  # 2 h ahead: local summer time as UTC
        assert run(["wake-get"], rtc, adjtime=adjtime) == 0
        assert capsys.readouterr().out == "1790003600\n"
    finally:
        monkeypatch.delenv("TZ")
        helper.time.tzset()


def test_errors_are_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    unwritable = tmp_path / "missing-dir" / "wakealarm"
    assert (
        helper.main(
            ["wake-set", str(NOW + 60)], now=NOW, rtcwake=tmp_path / "none", wakealarm=unwritable
        )
        == helper.EXIT_FAILED
    )
    assert "cannot program the RTC alarm" in capsys.readouterr().err


def test_the_script_is_standalone() -> None:
    source = Path(helper.__file__).read_text()
    assert source.startswith("#!/usr/bin/python3\n")
    assert "import kse" not in source
    assert "from kse" not in source
    imports = {
        line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))
    }
    assert imports <= {"os", "re", "subprocess", "sys", "time", "pathlib"}
    assert os.access(helper.__file__, os.R_OK)
