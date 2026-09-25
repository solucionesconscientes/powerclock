"""The desktop's font, read for the GUI (Qt from pip does not load Plasma's or GNOME's)."""

from pathlib import Path

import pytest

from powerclock.platform.linux.look import PLASMA_DEFAULT, desktop_font, gnome_font, kde_font


def test_plasma_font(tmp_path: Path) -> None:
    config = tmp_path / ".config"
    config.mkdir()
    env = {"XDG_CURRENT_DESKTOP": "KDE"}
    assert desktop_font(env, tmp_path) == PLASMA_DEFAULT  # nothing set: Plasma's default
    (config / "kdeglobals").write_text(
        "[General]\nfont=Inter,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1\n[KDE]\nSingleClick=false\n"
    )
    assert desktop_font(env, tmp_path) == ("Inter", 11.0)
    assert kde_font(tmp_path / "missing") is None


@pytest.mark.parametrize(
    ("value", "font"),
    [
        ("'Cantarell 11'\n", ("Cantarell", 11.0)),
        ("'Ubuntu Sans 10.5'", ("Ubuntu Sans", 10.5)),
        ("'Noto Sans Medium 10'", ("Noto Sans", 10.0)),
        ("''", None),
    ],
)
def test_gnome_font(value: str, font: tuple[str, float] | None) -> None:
    assert gnome_font(value) == font


def test_gnome_and_others(tmp_path: Path) -> None:
    asked: list[list[str]] = []

    def run(args: list[str]) -> str:
        asked.append(args)
        return "'Cantarell 11'"

    gnome = {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}
    assert desktop_font(gnome, tmp_path, run) == ("Cantarell", 11.0)
    assert asked == [["org.gnome.desktop.interface", "font-name"]]

    def broken(args: list[str]) -> str:
        raise OSError("no gsettings")

    assert desktop_font(gnome, tmp_path, broken) is None
    assert desktop_font({"XDG_CURRENT_DESKTOP": "XFCE"}, tmp_path) is None
