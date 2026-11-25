"""A low-confidence FAKE once carried an action that told the caller to close the card.

Measured on the installed pin (factory card t_883b6175, premise 3): "which color should the icon
be? only Simon can say" returned FAKE F6-stale-wait, confidence 0.3, matched [], low_confidence
true, and the action "Name the next actor and action in one line, or close the card." The gate
never acts on such a verdict, but a caller that reads ``action`` and skips ``low_confidence`` would
close the card on the classifier's default. A low-confidence verdict now says to read the card."""
import argparse
import io
import json

import pytest

from antibeaurocracy_core import cli
from antibeaurocracy_core import plugin as fake_gates
from antibeaurocracy_core.classify import ACTIONS, FAKE, RELAY, STALE, classify

PREFERENCE = "which color should the icon be? only Simon can say"
RELAY_SENTENCE = "Await the release agent to open the PR from my patch"
# One sentence per FAKE subtype except F6, each evidenced by a matched phrase.
EVIDENCED = (
    RELAY_SENTENCE,
    "Product must record the ruling on the release format",
    "Contract says local-only, so cannot mark done",
    "HOLD: keep the old export until further notice",
    "Awaiting ACK from platform",
)
UNEVIDENCED = (  # the classifier's defaults: text, classify() keyword arguments
    ("", {}),
    ("", {"created_blocked": True}),
    ("Looking into it", {"age_hours": 72}),
    (PREFERENCE, {}),
)


class _Seat:
    """A plugin context that reports settings and nothing else."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def get_config(self, key, default=None):
        return self.config.get(key, default)


def _tool(text: str) -> dict:
    return json.loads(fake_gates.tool_classify({"text": text}))


def _says_read_the_card(action: str) -> bool:
    return "read the card" in action.lower() and "close" not in action.lower()


def test_the_measured_probe_reads_the_card() -> None:
    out = _tool(PREFERENCE)
    assert (out["cls"], out["label"], out["confidence"], out["matched"]) == (FAKE, STALE, 0.3, [])
    assert out["low_confidence"] is True
    assert _says_read_the_card(out["action"]), out["action"]


def test_the_relay_sentence_keeps_the_carry_step_advice() -> None:
    out = _tool(RELAY_SENTENCE)
    assert (out["cls"], out["label"], out["confidence"]) == (FAKE, RELAY, 0.7)
    assert out["low_confidence"] is False
    assert out["action"] == ACTIONS[RELAY] and "do the carry step yourself" in out["action"]


@pytest.mark.parametrize("text,kwargs", UNEVIDENCED)
def test_every_unevidenced_default_reads_the_card(text, kwargs) -> None:
    """The defaults are the classifier's shrug, and F6-stale-wait only ever comes from one of them."""
    v = classify(text, **kwargs)
    assert v.cls == FAKE and not v.evidenced and v.confidence < 0.6
    assert v.action == ACTIONS[STALE]
    assert _says_read_the_card(v.action), v.action


@pytest.mark.parametrize("text", EVIDENCED)
def test_a_raised_threshold_reads_the_card_for_an_evidenced_fake(monkeypatch, text) -> None:
    """Under the seat's own bar, a matched phrase is still not a finding to act on."""
    monkeypatch.setattr(fake_gates, "_ctx", _Seat({"min_confidence": 0.9}))
    v = classify(text)
    assert v.cls == FAKE and v.evidenced and 0.6 <= v.confidence < 0.9  # the branch this test is for
    out = _tool(text)
    assert out["low_confidence"] is True
    assert _says_read_the_card(out["action"]), out["action"]
    assert out["matched"] == v.matched  # the evidence is still reported; only the advice changes


def _cli_json(monkeypatch, capsys, text: str, settings: dict) -> dict:
    parser = argparse.ArgumentParser(prog="antibeaurocracy")
    cli.add_arguments(parser)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.handle(parser.parse_args(["classify", "--json", text]), settings=settings) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_json_agrees_with_the_tool(monkeypatch, capsys) -> None:
    out = _cli_json(monkeypatch, capsys, PREFERENCE, {})
    assert out == _tool(PREFERENCE)
    assert out["low_confidence"] is True and _says_read_the_card(out["action"]), out["action"]
    out = _cli_json(monkeypatch, capsys, RELAY_SENTENCE, {"min_confidence": 0.9})
    assert out["low_confidence"] is True and _says_read_the_card(out["action"]), out["action"]
    out = _cli_json(monkeypatch, capsys, RELAY_SENTENCE, {})
    assert out["low_confidence"] is False and "do the carry step yourself" in out["action"]


def test_the_hook_still_waves_a_low_confidence_block_through(monkeypatch) -> None:
    """The hook is not part of this fix: in ask mode it still neither asks nor nudges on this verdict."""
    args = {"task_id": "t_1", "reason": PREFERENCE}
    for mode in ("ask", "nudge"):
        monkeypatch.setattr(fake_gates, "_ctx", _Seat({"fake_gate_mode": mode}))
        assert fake_gates.on_pre_tool_call(tool_name="kanban_block", args=args, session_id="s") is None
        assert len(fake_gates._nudges) == 0
