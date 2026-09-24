#!/bin/sh
# PowerClock installer for Linux.
#
# Give it permission to run (right click → Properties → Permissions) and double-click it,
# or run it in a terminal:  sh install-powerclock.sh
#
# It downloads uv (a fixed version, checked against the SHA-256 written below), installs
# PowerClock with its own Python in your home folder, and opens PowerClock's installation
# window, which asks for your password once (for the wake-up helper).
#
# For testing: POWERCLOCK_SOURCE installs from elsewhere than PyPI, e.g.
#   POWERCLOCK_SOURCE="powerclock[gui] @ file:///path/to/powerclock" sh install-powerclock.sh
# and POWERCLOCK_DRY_RUN=1 makes the service only log power actions.
set -eu

UV_VERSION="0.12.14"
UV_SHA256_X86_64="18ef5c3888ae59828cb13f38d57e9389b8173ecc719eff163bfafc74b38f5936"
UV_SHA256_AARCH64="7fb91bd5d10529c60723eaec3caf44726f89280e5aeed78af8fc63fcad004c9b"
PYTHON_VERSION="3.13"
SOURCE="${POWERCLOCK_SOURCE:-powerclock[gui]}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/powerclock"
UV="$DATA/uv/uv"

say() { printf '%s\n' "$*"; }

pause() {
    # A terminal opened for us closes when we end: leave time to read.
    if [ -n "${POWERCLOCK_IN_TERMINAL:-}" ]; then
        printf '\n%s' "Press Enter to close this window… "
        read -r _ || true
    fi
}

fail() {
    say "" "✘ $*" >&2
    pause
    exit 1
}

# 1. Double-clicked in a file manager (no terminal): open one, so progress can be seen.
if [ ! -t 1 ] && [ -z "${POWERCLOCK_IN_TERMINAL:-}" ]; then
    export POWERCLOCK_IN_TERMINAL=1
    for terminal in konsole gnome-terminal kgx xfce4-terminal mate-terminal x-terminal-emulator xterm; do
        command -v "$terminal" >/dev/null 2>&1 || continue
        case "$terminal" in
            gnome-terminal | kgx) exec "$terminal" -- sh "$0" "$@" ;;
            xfce4-terminal | mate-terminal) exec "$terminal" -x sh "$0" "$@" ;;
            *) exec "$terminal" -e sh "$0" "$@" ;;
        esac
    done
    # No terminal emulator found: carry on without one.
fi

say "PowerClock — shutdown, wake-up and task scheduler" ""

[ "$(uname -s)" = "Linux" ] || fail "This installer is for Linux."
case "$(uname -m)" in
    x86_64 | amd64) ARCH="x86_64"; SUM="$UV_SHA256_X86_64" ;;
    aarch64 | arm64) ARCH="aarch64"; SUM="$UV_SHA256_AARCH64" ;;
    *) fail "This computer's processor ($(uname -m)) is not supported yet." ;;
esac

download() { # URL FILE
    if command -v curl >/dev/null 2>&1; then
        curl --fail --silent --show-error --location --retry 3 --output "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document "$2" "$1"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"
    else
        return 1
    fi
}

sha256() { # FILE
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
    fi
}

# 2. uv, in a folder of its own (it does not touch the rest of the system).
if [ ! -x "$UV" ] || [ "$("$UV" --version 2>/dev/null | cut -d ' ' -f 2)" != "$UV_VERSION" ]; then
    say "Downloading uv $UV_VERSION…"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$ARCH-unknown-linux-gnu.tar.gz"
    download "$URL" "$TMP/uv.tar.gz" || fail "Could not download uv: check the internet connection."
    [ "$(sha256 "$TMP/uv.tar.gz")" = "$SUM" ] \
        || fail "The downloaded uv is not the expected file (its SHA-256 does not match): nothing was installed."
    tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
    mkdir -p "$(dirname "$UV")"
    mv "$TMP/uv-$ARCH-unknown-linux-gnu/uv" "$UV"
    chmod 0755 "$UV"
fi

# 3. PowerClock with a Python of its own: the system's version, venv or pip do not matter.
say "Installing PowerClock and its own Python (about 130 MB to download the first time)…"
UV_PYTHON_PREFERENCE=only-managed "$UV" tool install --reinstall --python "$PYTHON_VERSION" "$SOURCE" \
    || fail "PowerClock could not be installed (see the messages above)."
BIN="$("$UV" tool dir --bin)"

# 4. The installation window (or its terminal version without a desktop).
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ -x "$BIN/powerclock-gui" ]; then
    say "Opening the installation window…"
    if command -v setsid >/dev/null 2>&1; then
        setsid "$BIN/powerclock-gui" --setup </dev/null >/dev/null 2>&1 &
    else
        nohup "$BIN/powerclock-gui" --setup </dev/null >/dev/null 2>&1 &
    fi
    sleep 2
else
    "$BIN/powerclock" setup || fail "The setup did not finish."
    pause
fi
