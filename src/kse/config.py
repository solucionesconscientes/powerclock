"""Where kse keeps its files, the daemon settings (daemon.json) and the API token."""

import contextlib
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, ConfigDict, Field, ValidationError

APP = "kse"
HOME_ENV = "KSE_HOME"  # one directory for everything: tests and isolated experiments
DEFAULT_PORT = 47831


@dataclass(frozen=True)
class Paths:
    config: Path
    data: Path

    @classmethod
    def default(cls) -> "Paths":
        home = os.environ.get(HOME_ENV)
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


class Settings(BaseModel):
    """daemon.json. The API only ever listens on 127.0.0.1."""

    model_config = ConfigDict(extra="forbid")

    port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    dry_run: bool = False
    log_level: Literal["debug", "info", "warning", "error"] = "info"


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
