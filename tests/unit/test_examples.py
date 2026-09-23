import json
from pathlib import Path
from typing import Any

import pytest

from kse.models import Rule

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((ROOT / "examples").glob("*.json"))


def test_there_are_at_least_five_examples() -> None:
    assert len(EXAMPLES) >= 5


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.name for path in EXAMPLES])
def test_example_is_a_valid_rule(path: Path) -> None:
    rule = Rule.model_validate_json(path.read_text(encoding="utf-8"))
    assert rule.id == path.stem
    assert Rule.model_validate_json(rule.model_dump_json()) == rule


def architecture_example() -> dict[str, Any]:
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    section = text.split("## 4.", 1)[1]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)


def test_architecture_example_matches_backup_example() -> None:
    documented = architecture_example()
    Rule.model_validate(documented)
    example = json.loads((ROOT / "examples" / "backup-nocturno.json").read_text(encoding="utf-8"))
    assert documented == example
