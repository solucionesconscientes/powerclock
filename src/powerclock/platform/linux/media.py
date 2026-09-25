"""Media players (MPRIS), the output volume (PipeWire's wpctl or PulseAudio's pactl), sounds
and speech (speech-dispatcher, espeak-ng)."""

import re
from collections.abc import Mapping
from pathlib import Path

from powerclock.platform.base import MediaCommand, NotSupported
from powerclock.platform.linux.commands import Commands
from powerclock.platform.linux.dbus import Bus, DBusError, get_property, list_names

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
METHODS: dict[str, str] = {
    "play": "Play",
    "pause": "Pause",
    "toggle": "PlayPause",
    "stop": "Stop",
    "next": "Next",
    "previous": "Previous",
}
SINK_WPCTL = "@DEFAULT_AUDIO_SINK@"
SINK_PACTL = "@DEFAULT_SINK@"
SOUND_THEMES = (Path("usr/share/sounds/freedesktop/stereo"), Path("usr/share/sounds/ocean/stereo"))
SOUND_LIMIT = 120.0  # seconds a sound or a sentence may last
SOUND_NAME = re.compile(r"[a-z0-9-]+")


class Media:
    def __init__(
        self, bus: Bus, commands: Commands, env: Mapping[str, str], root: Path = Path("/")
    ) -> None:
        self._bus = bus
        self._commands = commands
        self._env = env
        self._root = root

    # ── Players ───────────────────────────────────────────────────────────────

    async def control(self, command: MediaCommand, player: str | None, uri: str | None) -> str:
        name = await self._choose(player)
        if command == "open":
            if not uri:
                raise ValueError("open needs an address")
            await self._bus.call(name, MPRIS_PATH, PLAYER, "OpenUri", "s", [uri])
        else:
            await self._bus.call(name, MPRIS_PATH, PLAYER, METHODS[command])
        return name.removeprefix(MPRIS_PREFIX)

    async def _choose(self, wanted: str | None) -> str:
        try:
            names = [n for n in await list_names(self._bus) if n.startswith(MPRIS_PREFIX)]
        except DBusError as exc:
            raise NotSupported("media", f"no session bus: {exc}") from exc
        if wanted:
            names = [n for n in names if wanted.lower() in n.lower()]
        if not names:
            raise NotSupported(
                "media",
                f"no media player {wanted!r} is open" if wanted else "no media player is open",
                fix_hint="open it first, e.g. with an 'Open an application' step",
            )
        for name in names:
            try:
                status = await get_property(self._bus, name, MPRIS_PATH, PLAYER, "PlaybackStatus")
            except DBusError:
                continue
            if status == "Playing":
                return name
        return sorted(names)[0]

    # ── Volume ────────────────────────────────────────────────────────────────

    async def volume(self) -> tuple[float | None, bool | None]:
        if self._commands.which("wpctl"):
            code, output = await self._commands.run(["wpctl", "get-volume", SINK_WPCTL])
            match = re.search(r"Volume:\s*([0-9.]+)", output) if code == 0 else None
            if match:
                return float(match[1]), "[MUTED]" in output
        if self._commands.which("pactl"):
            _, volume = await self._commands.run(["pactl", "get-sink-volume", SINK_PACTL])
            _, mute = await self._commands.run(["pactl", "get-sink-mute", SINK_PACTL])
            percent = re.search(r"(\d+)%", volume)
            level = int(percent[1]) / 100 if percent else None
            return level, ("yes" in mute) if mute else None
        raise NotSupported("volume", "neither wpctl (PipeWire) nor pactl (PulseAudio) found")

    async def set_volume(self, level: float | None, mute: bool | None) -> None:
        if self._commands.which("wpctl"):
            if level is not None:
                await self._check(["wpctl", "set-volume", "-l", "1.5", SINK_WPCTL, f"{level:.2f}"])
            if mute is not None:
                await self._check(["wpctl", "set-mute", SINK_WPCTL, "1" if mute else "0"])
            return
        if self._commands.which("pactl"):
            if level is not None:
                await self._check(
                    ["pactl", "set-sink-volume", SINK_PACTL, f"{round(level * 100)}%"]
                )
            if mute is not None:
                await self._check(["pactl", "set-sink-mute", SINK_PACTL, "1" if mute else "0"])
            return
        raise NotSupported("volume", "neither wpctl (PipeWire) nor pactl (PulseAudio) found")

    # ── Sounds and speech ─────────────────────────────────────────────────────

    async def play(self, sound: str) -> None:
        path = self._sound_file(sound)
        for player in ("pw-play", "paplay", "aplay"):
            if self._commands.which(player):
                await self._check([player, str(path)], limit=SOUND_LIMIT)
                return
        raise NotSupported("sound", "no sound player found (pw-play, paplay or aplay)")

    def _sound_file(self, sound: str) -> Path:
        """A path, or the name of a sound of the theme ("alarm-clock-elapsed")."""
        if SOUND_NAME.fullmatch(sound):
            for folder in SOUND_THEMES:
                for suffix in (".oga", ".ogg", ".wav"):
                    candidate = self._root / folder / f"{sound}{suffix}"
                    if candidate.is_file():
                        return candidate
        path = Path(sound).expanduser()
        if not path.is_file():
            raise OSError(f"there is no sound {sound!r}")
        return path

    async def say(self, text: str, language: str | None) -> None:
        if self._commands.which("spd-say"):
            argv = ["spd-say", "--wait"]
            argv += ["--language", language] if language else []
            await self._check([*argv, "--", text], limit=SOUND_LIMIT)
            return
        if self._commands.which("espeak-ng"):
            argv = ["espeak-ng"] + (["-v", language] if language else [])
            await self._check([*argv, "--", text], limit=SOUND_LIMIT)
            return
        raise NotSupported(
            "say", "no speech synthesis found", fix_hint="install speech-dispatcher or espeak-ng"
        )

    async def _check(self, argv: list[str], limit: float | None = None) -> None:
        code, output = await self._commands.run(argv, self._env, limit=limit)
        if code != 0:
            raise OSError(f"{argv[0]} failed ({code}): {output}")
