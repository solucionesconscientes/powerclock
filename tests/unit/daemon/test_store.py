import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kse.daemon.events import EventHub
from kse.daemon.store import History, RulesFileError, RuleStore, parse_rules
from kse.engine.runs import Event, Run
from support import START, rule


def write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    stat = path.stat()  # make sure the change is visible even within the same tick
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def dump(*rules: object) -> dict[str, object]:
    return {"version": 1, "rules": [r.model_dump(mode="json") for r in rules]}  # type: ignore[attr-defined]


def test_missing_or_empty_file_means_no_rules(tmp_path: Path) -> None:
    store = RuleStore(tmp_path / "rules.json")
    store.load()
    assert (store.rules, store.errors) == ({}, [])


def test_put_and_delete_write_the_file_atomically(tmp_path: Path) -> None:
    store = RuleStore(tmp_path / "rules.json")
    store.load()
    store.put(rule(id="uno"))
    store.put(rule(id="dos"))
    saved = json.loads(store.path.read_text())
    assert saved["version"] == 1
    assert [r["id"] for r in saved["rules"]] == ["uno", "dos"]
    store.delete("uno")
    assert [r["id"] for r in json.loads(store.path.read_text())["rules"]] == ["dos"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rules.json"]


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("{not json", "invalid JSON"),
        ('{"version": 2, "rules": []}', "unsupported version"),
        ('"hola"', "expected"),
    ],
)
def test_unreadable_files(content: str, error: str) -> None:
    rules, errors = parse_rules(content)
    assert rules == {}
    assert error in errors[0]


def test_bare_list_and_partial_errors() -> None:
    good = rule(id="good").model_dump(mode="json")
    rules, errors = parse_rules(json.dumps([good, {"id": "bad", "name": "x"}, good]))
    assert list(rules) == ["good"]
    assert errors[0].startswith("rule #2 (bad): trigger: Field required")
    assert "duplicate id 'good'" in errors[1]


def test_errors_block_writes_so_hand_edits_are_never_lost(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    write(path, "{half-edited")
    store = RuleStore(path)
    store.load()
    assert store.errors
    with pytest.raises(RulesFileError, match="fix them first"):
        store.put(rule())
    assert path.read_text() == "{half-edited"


def test_reload_detects_hand_edits(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    store = RuleStore(path)
    store.load()
    store.put(rule(id="uno"))
    assert store.reload_if_changed() is None  # our own write

    write(path, dump(rule(id="uno", name="Renamed"), rule(id="dos")))
    changed, removed = store.reload_if_changed() or ([], [])
    assert sorted(r.id for r in changed) == ["dos", "uno"]
    assert removed == []
    assert store.reload_if_changed() is None

    write(path, dump(rule(id="dos")))
    changed, removed = store.reload_if_changed() or ([], [])
    assert (changed, removed) == ([], ["uno"])


def test_reload_with_errors_keeps_the_running_rules(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    store = RuleStore(path)
    store.load()
    store.put(rule(id="uno"))
    write(path, "{oops")
    assert store.reload_if_changed() is None
    assert list(store.rules) == ["uno"]
    assert store.errors
    write(path, dump(rule(id="uno"), rule(id="dos")))
    changed, _ = store.reload_if_changed() or ([], [])
    assert [r.id for r in changed] == ["dos"]
    assert store.errors == []


def run(run_id: str, rule_id: str, minutes: int, state: str = "done") -> Run:
    finished = START + timedelta(minutes=minutes)
    return Run(
        id=run_id,
        rule_id=rule_id,
        rule_name=rule_id,
        cause="schedule",
        state=state,  # type: ignore[arg-type]
        started_at=finished,
        finished_at=finished,
    )


def test_history(tmp_path: Path) -> None:
    history = History(tmp_path / "data" / "history.sqlite")
    for index in range(5):
        history.add(run(f"r{index}", "a" if index % 2 else "b", index))
    assert [r.id for r in history.list(limit=2)] == ["r4", "r3"]
    assert [r.id for r in history.list(limit=2, offset=2)] == ["r2", "r1"]
    assert [r.id for r in history.list(rule_id="a")] == ["r3", "r1"]
    assert (history.count(), history.count("a")) == (5, 2)
    assert history.get("r2") == run("r2", "b", 2)
    assert history.get("nope") is None
    assert history.last_alive() is None
    history.set_last_alive(datetime(2026, 9, 24, 9, 0, tzinfo=UTC))
    assert history.last_alive() == datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
    history.close()


async def test_event_hub_drops_the_oldest_for_slow_clients() -> None:
    hub = EventHub()
    with hub.subscribe() as queue:
        assert hub.subscribers == 1
        for second in range(300):
            hub.publish(Event(type="tick", at=START, data={"remaining": second}))
        assert queue.qsize() == 256
        assert queue.get_nowait().data["remaining"] == 44
    assert hub.subscribers == 0
