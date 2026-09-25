"""Where powerclock keeps its files, the daemon settings (daemon.json) and the API token."""

import contextlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, ConfigDict, Field, ValidationError

APP = "powerclock"
HOME_ENV = "POWERCLOCK_HOME"  # one directory for everything: tests and isolated experiments
LEGACY_PREFIX = "KSE_"  # the working name's variables still count: an old habit never loses dry run


def setting(name: str) -> str | None:
    """An environment variable, e.g. POWERCLOCK_HOME, or its old name (KSE_HOME)."""
    value = os.environ.get(name)
    if value is None and name.startswith("POWERCLOCK_"):
        value = os.environ.get(LEGACY_PREFIX + name.removeprefix("POWERCLOCK_"))
    return value


DEFAULT_PORT = 47831


@dataclass(frozen=True)
class Paths:
    config: Path
    data: Path

    @classmethod
    def default(cls) -> "Paths":
        home = setting(HOME_ENV)
        if home:
            return cls(Path(home), Path(home))
        return cls(Path(user_config_dir(APP)), Path(user_data_dir(APP)))

    @property
    def rules(self) -> Path:
        return self.config / "rules.json"

    @property
    def settings(self) -> Path:
        return self.config / "daemon.json"

    @property
    def token(self) -> Path:
        return self.config / "api.token"

    @property
    def history(self) -> Path:
        return self.data / "history.sqlite"

    @property
    def secrets(self) -> Path:
        return self.config / "secrets.json"


class Settings(BaseModel):
    """daemon.json. The API only ever listens on 127.0.0.1."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    dry_run: bool = False
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    tariff: Literal["es-2.0td"] | None = None  # time-of-use electricity prices, if any
    # For the savings estimate: the computer's average consumption when on and the price of
    # electricity (None: a typical value is used).
    watts: float | None = Field(default=None, gt=0, le=5000)
    price_kwh: float | None = Field(default=None, ge=0, le=10)
    currency: str = Field(default="€", min_length=1, max_length=5)


# What clients may change (PATCH /settings); the rest needs a restart of the daemon.
USER_SETTINGS = frozenset({"tariff", "watts", "price_kwh", "currency"})


class SettingsError(Exception):
    pass


def load_settings(paths: Paths) -> Settings:
    try:
        text = paths.settings.read_text()
    except FileNotFoundError:
        return Settings()
    try:
        return Settings.model_validate_json(text)
    except ValidationError as exc:
        raise SettingsError(f"{paths.settings} is not valid:\n{exc}") from None


def ensure_token(path: Path) -> str:
    """The API token, created on first use with permissions 0600."""
    token = read_token(path)
    if token:
        if path.stat().st_mode & 0o077:
            path.chmod(0o600)
        return token
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    atomic_write(path, token + "\n")
    return token


def read_token(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except FileNotFoundError:
        return None


SECRET_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


def read_secrets(paths: Paths) -> dict[str, str]:
    """secrets.json (0600): tokens that steps use by name (telegram_token…), kept out of
    rules.json so exporting rules never leaks them."""
    try:
        data = json.loads(paths.secrets.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def write_secret(paths: Paths, name: str, value: str | None) -> None:
    """Store a secret (None: forget it)."""
    if not SECRET_NAME.fullmatch(name):
        raise ValueError(f"a secret's name is lowercase letters, digits and _: {name!r}")
    stored = read_secrets(paths)
    if value is None:
        stored.pop(name, None)
    else:
        stored[name] = value
    atomic_write(paths.secrets, json.dumps(stored, indent=2) + "\n")


def atomic_write(path: Path, text: str) -> None:
    """Write to a temporary file (0600) in the same directory, then rename it over `path`:
    readers see the old or the new content, never half of it."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        Path(temporary).replace(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            Path(temporary).unlink()
        raise
