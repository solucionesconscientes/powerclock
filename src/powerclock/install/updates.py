"""Knowing that a new PowerClock is out without having to ask for it.

The check is a single read of PyPI's JSON, at most once a day, and it never installs
anything: it only remembers what it saw so the window and the tray can say so. It can be
turned off, and when it is, nothing leaves the machine.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from powerclock.config import Paths, atomic_write
from powerclock.install.program import newer

EVERY = timedelta(days=1)  # a new version is not news that needs the hour


@dataclass(frozen=True)
class State:
    """What `updates.json` remembers between runs."""

    enabled: bool = True
    checked_at: datetime | None = None
    seen: str | None = None  # the newest version PyPI reported on the last check

    @property
    def available(self) -> str | None:
        """The version to tell the user about, if it is newer than the one running."""
        return self.seen if self.seen and newer(self.seen) else None

    def due(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if self.checked_at is None:
            return True
        return (now or datetime.now(UTC)) - self.checked_at >= EVERY


def _file(paths: Paths | None = None) -> Path:
    return (paths or Paths.default()).data / "updates.json"


def read(paths: Paths | None = None) -> State:
    try:
        data = json.loads(_file(paths).read_text())
    except (OSError, ValueError):
        return State()
    if not isinstance(data, dict):
        return State()
    return State(
        enabled=bool(data.get("enabled", True)),
        checked_at=_moment(data.get("checked_at")),
        seen=str(data["seen"]) if data.get("seen") else None,
    )


def write(state: State, paths: Paths | None = None) -> None:
    data: dict[str, Any] = {"enabled": state.enabled}
    if state.checked_at is not None:
        data["checked_at"] = state.checked_at.isoformat()
    if state.seen is not None:
        data["seen"] = state.seen
    atomic_write(_file(paths), json.dumps(data, indent=2) + "\n")


def remember(latest: str, *, now: datetime | None = None, paths: Paths | None = None) -> State:
    """Store what PyPI answered, with the moment it answered."""
    state = State(enabled=read(paths).enabled, checked_at=now or datetime.now(UTC), seen=latest)
    write(state, paths)
    return state


def set_enabled(enabled: bool, paths: Paths | None = None) -> State:
    current = read(paths)
    state = State(enabled=enabled, checked_at=current.checked_at, seen=current.seen)
    write(state, paths)
    return state


def _moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
