"""rules.json (validated, written atomically, reloaded when edited by hand) and the run
history in SQLite."""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from powerclock.config import atomic_write
from powerclock.engine.runs import Run
from powerclock.engine.savings import Period
from powerclock.models import Rule

log = logging.getLogger(__name__)

FILE_VERSION = 1


class RulesFileError(Exception):
    """rules.json has errors: nothing is written until it is fixed, so hand edits are
    never overwritten."""


class RuleStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.rules: dict[str, Rule] = {}
        self.errors: list[str] = []
        self._digest: str | None = None
        self._stat: tuple[int, int] | None = None

    def load(self) -> None:
        """Read the file; on errors, load the valid rules and report the rest."""
        text = self._read()
        self.rules, self.errors = parse_rules(text)
        self._remember(text)
        for error in self.errors:
            log.error("rules.json: %s", error)

    def reload_if_changed(self) -> tuple[list[Rule], list[str]] | None:
        """Pick up edits made by hand: (added or changed rules, removed ids), or None.

        If the new content has any error, the running rules stay as they were."""
        stat = self._current_stat()
        if stat == self._stat:
            return None
        text = self._read()
        if _digest(text) == self._digest:  # our own write, or a touch
            self._stat = stat
            return None
        rules, errors = parse_rules(text)
        self._remember(text)
        self.errors = errors
        if errors:
            for error in errors:
                log.error("rules.json: %s (the previous rules keep running)", error)
            return None
        changed = [rule for rule_id, rule in rules.items() if self.rules.get(rule_id) != rule]
        removed = [rule_id for rule_id in self.rules if rule_id not in rules]
        self.rules = rules
        return changed, removed

    def put(self, rule: Rule) -> None:
        self._check_writable()
        if self.rules.get(rule.id) == rule:
            return
        self.rules[rule.id] = rule
        self._save()

    def delete(self, rule_id: str) -> None:
        self._check_writable()
        if self.rules.pop(rule_id, None) is not None:
            self._save()

    def _check_writable(self) -> None:
        if self.errors:
            raise RulesFileError(
                f"{self.path} has errors, fix them first: " + "; ".join(self.errors)
            )

    def _save(self) -> None:
        data = {
            "version": FILE_VERSION,
            "rules": [rule.model_dump(mode="json") for rule in self.rules.values()],
        }
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        atomic_write(self.path, text)
        self._remember(text)

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _remember(self, text: str) -> None:
        self._digest = _digest(text)
        self._stat = self._current_stat()

    def _current_stat(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size


def parse_rules(text: str) -> tuple[dict[str, Rule], list[str]]:
    """Accepts {"version": 1, "rules": [...]} or a bare list of rules."""
    if not text.strip():
        return {}, []
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, [f"invalid JSON: {exc}"]
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        if data.get("version", FILE_VERSION) != FILE_VERSION:
            return {}, [f"unsupported version {data.get('version')!r}"]
        items = data["rules"]
    elif isinstance(data, list):
        items = data
    else:
        return {}, ['expected {"version": 1, "rules": [...]}']
    rules: dict[str, Rule] = {}
    errors: list[str] = []
    for index, item in enumerate(items, start=1):
        label = item.get("id", "?") if isinstance(item, dict) else "?"
        try:
            rule = Rule.model_validate(item)
        except ValidationError as exc:
            errors.append(f"rule #{index} ({label}): {_summary(exc)}")
            continue
        if rule.id in rules:
            errors.append(f"rule #{index}: duplicate id {rule.id!r}")
            continue
        rules[rule.id] = rule
    return rules, errors


def _summary(error: ValidationError) -> str:
    parts = []
    for item in error.errors(include_url=False):
        where = ".".join(str(part) for part in item["loc"])
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


Periods = list[Period]  # outside History, whose `list` method would hide the builtin


class History:
    """Every finished run (done, failed, cancelled, skipped…) with its reason."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # One thread at a time (the daemon's event loop), but maybe not the creating one.
        self._db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)  # run records may include command output
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS runs_by_rule ON runs (rule_id, finished_at);
            CREATE INDEX IF NOT EXISTS runs_by_time ON runs (finished_at);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS awake (
                since TEXT NOT NULL,
                until TEXT NOT NULL,
                ended TEXT
            );
            CREATE INDEX IF NOT EXISTS awake_by_time ON awake (until);
            """
        )

    def add(self, run: Run) -> None:
        finished = (run.finished_at or run.started_at).isoformat()
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO runs (id, rule_id, finished_at, data) VALUES (?, ?, ?, ?)",
                (run.id, run.rule_id, finished, run.model_dump_json()),
            )

    def list(self, limit: int = 50, offset: int = 0, rule_id: str | None = None) -> list[Run]:
        query = "SELECT data FROM runs"
        args: tuple[Any, ...] = ()
        if rule_id is not None:
            query += " WHERE rule_id = ?"
            args = (rule_id,)
        query += " ORDER BY finished_at DESC, rowid DESC LIMIT ? OFFSET ?"
        rows = self._db.execute(query, (*args, limit, offset)).fetchall()
        return [Run.model_validate_json(data) for (data,) in rows]

    def get(self, run_id: str) -> Run | None:
        row = self._db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def count(self, rule_id: str | None = None) -> int:
        if rule_id is None:
            (total,) = self._db.execute("SELECT COUNT(*) FROM runs").fetchone()
        else:
            (total,) = self._db.execute(
                "SELECT COUNT(*) FROM runs WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        return int(total)

    def last_alive(self) -> datetime | None:
        """When the daemon was last known to be running (to detect missed fires)."""
        row = self._db.execute("SELECT value FROM meta WHERE key = 'last_alive'").fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_last_alive(self, moment: datetime) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_alive', ?)",
                (moment.isoformat(),),
            )

    # ── Periods awake (for the savings statistics) ────────────────────────────

    def mark_awake(self, now: datetime, gap: timedelta) -> None:
        """Still awake: extend the current period, or start a new one after a gap (the
        computer was off or asleep) or after PowerClock ended the previous one."""
        row = self._db.execute(
            "SELECT rowid, until, ended FROM awake ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        with self._db:
            if row is not None:
                recent = timedelta(0) <= now - datetime.fromisoformat(row[1]) <= gap
                if recent and row[2] is not None:
                    return  # PowerClock is shutting it down: the last marks before it stops
                if recent:
                    self._db.execute(
                        "UPDATE awake SET until = ? WHERE rowid = ?", (now.isoformat(), row[0])
                    )
                    return
            self._db.execute(
                "INSERT INTO awake (since, until) VALUES (?, ?)", (now.isoformat(), now.isoformat())
            )

    def mark_ended(self, now: datetime, how: str) -> None:
        """PowerClock is about to shut down or suspend the computer."""
        with self._db:
            self._db.execute(
                "UPDATE awake SET until = ?, ended = ? "
                "WHERE rowid = (SELECT MAX(rowid) FROM awake) AND ended IS NULL",
                (now.isoformat(), how),
            )

    def awake(self, since: datetime) -> Periods:
        """The periods awake that end after `since`, plus the one before (its gap counts)."""
        rows = self._db.execute(
            "SELECT since, until, ended FROM awake WHERE rowid >= COALESCE("
            "(SELECT MAX(rowid) FROM awake WHERE until < ?), 0) ORDER BY rowid",
            (since.isoformat(),),
        ).fetchall()
        return [
            Period(datetime.fromisoformat(a), datetime.fromisoformat(b), ended)
            for a, b, ended in rows
        ]

    def close(self) -> None:
        self._db.close()
