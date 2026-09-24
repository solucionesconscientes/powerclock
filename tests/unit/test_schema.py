import json
import re
from typing import Any

import pytest

from powerclock.models import DURATION_PATTERN, parse_duration, rule_json_schema


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return rule_json_schema()


def test_schema_is_plain_json(schema: dict[str, Any]) -> None:
    assert json.loads(json.dumps(schema)) == schema
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert {"id", "name", "trigger", "actions"} <= set(schema["required"])


def test_every_tagged_object_requires_its_type(schema: dict[str, Any]) -> None:
    tagged = {
        name: definition
        for name, definition in schema["$defs"].items()
        if "const" in definition.get("properties", {}).get("type", {})
    }
    assert len(tagged) >= 25
    for name, definition in tagged.items():
        assert "type" in definition["required"], name


def test_public_field_names(schema: dict[str, Any]) -> None:
    defs = schema["$defs"]
    assert "for" in defs["Idle"]["properties"]
    assert "is" in defs["PowerSource"]["properties"]
    assert "not" in defs["NotOf"]["properties"]
    assert not any("for_" in d.get("properties", {}) for d in defs.values())


def test_durations_are_text_with_readable_defaults(schema: dict[str, Any]) -> None:
    warning = schema["properties"]["warning"]
    assert warning["type"] == "string"
    assert warning["pattern"] == DURATION_PATTERN
    assert warning["default"] == "1m"
    assert schema["$defs"]["Guards"]["properties"]["retry"]["default"] == "5m"


def test_unions_are_discriminated_by_type(schema: dict[str, Any]) -> None:
    trigger = schema["properties"]["trigger"]
    assert trigger["discriminator"]["propertyName"] == "type"
    assert "cron" in trigger["discriminator"]["mapping"]


@pytest.mark.parametrize(
    "text", ["0s", "5m", "1h30m", "1d2h3m4s", "", "5", "5x", "1.5h", "30m1h", " 5m", "5M"]
)
def test_duration_pattern_agrees_with_parser(text: str) -> None:
    try:
        parse_duration(text)
        parses = True
    except ValueError:
        parses = False
    assert (re.search(DURATION_PATTERN, text) is not None) == parses
