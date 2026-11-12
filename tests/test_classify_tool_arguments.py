"""bureaucracy_classify must refuse malformed arguments by name, never answer them with a verdict.

An LFM3 eval found that a model passing the wrong types got a silent FAKE verdict back, which the
agent then trusted. The schema also has to say what is required and which kinds exist.
"""
import json

import pytest

from antibeaurocracy_core import plugin

GOOD = "Awaiting approval from Product before I run the tests"


def _call(args):
    return json.loads(plugin.tool_classify(args))


def test_schema_declares_required_text_and_the_kind_enum():
    params = plugin.CLASSIFY_SCHEMA["parameters"]
    assert params["required"] == ["text"]
    assert params["properties"]["kind"]["enum"] == ["dependency", "needs_input", "capability", "transient"]
    assert params["properties"]["text"]["type"] == "string"
    assert params["properties"]["age_hours"]["type"] == "number"


def test_valid_arguments_still_classify():
    out = _call({"text": GOOD, "kind": "needs_input", "age_hours": 3.5})
    assert out["cls"] == "FAKE" and "error" not in out
    assert "cls" in _call({"text": GOOD})


@pytest.mark.parametrize("args", [
    {},
    {"text": None},
    {"text": ""},
    {"text": "   "},
    {"text": 42},
    {"text": ["a", "b"]},
    {"text": {"reason": GOOD}},
])
def test_bad_text_is_a_named_error_not_a_verdict(args):
    out = _call(args)
    assert out["error"] == "bad_arguments" and "text" in out["detail"]
    assert "cls" not in out


@pytest.mark.parametrize("kind", ["blocked", "Dependency ", 7, ["dependency"], {"k": 1}])
def test_unknown_kind_is_a_named_error(kind):
    out = _call({"text": GOOD, "kind": kind})
    assert out["error"] == "bad_arguments" and "kind" in out["detail"]
    assert "cls" not in out


@pytest.mark.parametrize("age", ["soon", "", True, float("nan"), float("inf"), -1, [1], {"h": 1}])
def test_non_number_age_is_a_named_error(age):
    out = _call({"text": GOOD, "age_hours": age})
    assert out["error"] == "bad_arguments" and "age_hours" in out["detail"]
    assert "cls" not in out


def test_a_numeric_string_age_is_still_accepted():
    assert "error" not in _call({"text": GOOD, "age_hours": "3"})


def test_null_optional_arguments_are_accepted():
    out = _call({"text": GOOD, "kind": None, "age_hours": None})
    assert "error" not in out and out["cls"]
