"""Running a command in a terminal window (a `run` step with `terminal: true`), for scripts
that ask questions or for the password (sudo, dialog menus…).

The desktop's own terminal is preferred (Konsole on Plasma, Console or GNOME Terminal on
GNOME…). A small `sh` wrapper runs the command, writes its exit code where PowerClock waits
for it (129 if the window is closed first) and keeps the window open until Enter.
"""

import shlex
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

# (program, what goes before the command). The order is the fallback order.
TERMINALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("konsole", ("-e",)),
    ("ptyxis", ("--",)),
    ("kgx", ("--",)),
    ("gnome-terminal", ("--wait", "--")),
    ("xfce4-terminal", ("-x",)),
    ("mate-terminal", ("-x",)),
    ("lxterminal", ("-e",)),
    ("terminator", ("-x",)),
    ("alacritty", ("-e",)),
    ("kitty", ()),
    ("foot", ()),
    ("wezterm", ("start", "--")),
    ("x-terminal-emulator", ("-e",)),
    ("xterm", ("-e",)),
)
FIRST_FOR_DESKTOP = {"KDE": "konsole", "GNOME": "ptyxis", "XFCE": "xfce4-terminal"}

# $1: where to write the exit code; $2: the words shown at the end; then the command.
WRAPPER = (
    "result=$1; done=$2; shift 2; trap 'echo 129 > \"$result\"; exit 129' HUP; "
    '"$@"; code=$?; echo "$code" > "$result"; '
    'printf "\\n%s %s\\n" "$done" "$code"; read -r _'
)


def pick(env: Mapping[str, str]) -> tuple[str, tuple[str, ...]] | None:
    """The terminal to use: the desktop's own first, else the first one installed."""
    desktops = env.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    preferred = [FIRST_FOR_DESKTOP[d] for d in desktops if d in FIRST_FOR_DESKTOP]
    if "GNOME" in desktops:
        preferred += ["kgx", "gnome-terminal"]
    known = dict(TERMINALS)
    order = [*preferred, *(name for name, _ in TERMINALS if name not in preferred)]
    for name in order:
        program = shutil.which(name, path=env.get("PATH"))
        if program is not None:
            return program, known[name]
    return None


def command(
    terminal: tuple[str, tuple[str, ...]],
    argv: Sequence[str],
    *,
    shell: bool,
    env: Mapping[str, str],
    result: Path,
    done: str,
) -> list[str]:
    """The whole command line: the terminal, `env` for the step's variables, the wrapper
    and the step's command (`sh -c` when it is one shell line)."""
    program, before = terminal
    inner = ["/bin/sh", "-c", argv[0]] if shell else list(argv)
    variables = [f"{key}={value}" for key, value in env.items()]
    return [
        program,
        *before,
        "/usr/bin/env",
        *variables,
        "/bin/sh",
        "-c",
        WRAPPER,
        "powerclock",
        str(result),
        done,
        *inner,
    ]


def shown(argv: Sequence[str]) -> str:
    return shlex.join(argv)


def folder(cwd: str | None, home: Path) -> Path:
    """Where the command runs: its `cwd` ("~" is the home folder) or the home folder."""
    if not cwd or cwd == "~":
        return home
    return home / cwd[2:] if cwd.startswith("~/") else Path(cwd)
