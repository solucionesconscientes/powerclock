"""The Linux installer script, run for real with sh but with a fake uv, curl and uname in a
temporary home: nothing is downloaded or installed."""

import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "installers" / "install-powerclock.sh"

pytestmark = pytest.mark.skipif(os.name != "posix", reason="a POSIX shell script")


def executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + text)
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def fakes(tmp_path: Path, home: Path) -> Path:
    """A folder of fake programs, first on the PATH; each logs how it was called."""
    folder = tmp_path / "fakes"
    tools = tmp_path / "tools-bin"
    log = tmp_path / "log"
    executable(tools / "powerclock", f'echo "powerclock $*" >> {log}\n')
    executable(tools / "powerclock-gui", f'echo "powerclock-gui $*" >> {log}\n')
    uv = home / ".local" / "share" / "powerclock" / "uv" / "uv"
    executable(
        uv,
        f"""echo "uv $* [$UV_PYTHON_PREFERENCE]" >> {log}
case "$1" in
    --version) echo "uv 0.12.14" ;;
    tool) if [ "$2" = dir ]; then echo "{tools}"; fi ;;
esac
""",
    )
    return folder


def run(home: Path, fakes: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {
        "HOME": str(home),
        "PATH": f"{fakes}:/usr/bin:/bin",
        "POWERCLOCK_IN_TERMINAL": "1",  # as if already in a terminal: no new window
        "LC_ALL": "C.UTF-8",
    }
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env={**base, **env},
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )


def log(fakes: Path) -> list[str]:
    path = fakes.parent / "log"
    return path.read_text().splitlines() if path.exists() else []


def test_installs_with_a_managed_python_then_sets_up(home: Path, fakes: Path) -> None:
    result = run(home, fakes)  # no DISPLAY: the terminal version of the setup
    assert result.returncode == 0, result.stderr
    assert "uv tool install --reinstall --python 3.13 powerclock[gui] [only-managed]" in log(fakes)
    assert log(fakes)[-1] == "powerclock setup"
    assert "Downloading uv" not in result.stdout  # the right uv is there already


def test_opens_the_installation_window_on_a_desktop(home: Path, fakes: Path) -> None:
    result = run(home, fakes, WAYLAND_DISPLAY="wayland-0")
    assert result.returncode == 0, result.stderr
    for _ in range(100):  # started in the background
        if "powerclock-gui --setup" in log(fakes):
            break
        time.sleep(0.05)
    assert "powerclock-gui --setup" in log(fakes)


def test_another_source(home: Path, fakes: Path) -> None:
    source = "powerclock[gui] @ file:///tmp/powerclock"
    run(home, fakes, POWERCLOCK_SOURCE=source)
    assert f"uv tool install --reinstall --python 3.13 {source} [only-managed]" in log(fakes)


def test_a_tampered_download_is_refused(home: Path, fakes: Path) -> None:
    (home / ".local" / "share" / "powerclock" / "uv" / "uv").unlink()
    executable(  # "downloads" a file that is not the real uv
        fakes / "curl",
        'while [ $# -gt 0 ]; do [ "$1" = --output ] && echo evil > "$2"; shift; done\n',
    )
    result = run(home, fakes)
    assert result.returncode == 1
    assert "SHA-256 does not match" in result.stderr
    assert not (home / ".local" / "share" / "powerclock" / "uv" / "uv").exists()
    assert log(fakes) == []  # nothing ran


def test_unsupported_processor(home: Path, fakes: Path) -> None:
    executable(fakes / "uname", '[ "$1" = -s ] && echo Linux || echo riscv64\n')
    result = run(home, fakes)
    assert result.returncode == 1
    assert "processor (riscv64) is not supported yet" in result.stderr
