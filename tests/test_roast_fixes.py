"""Regression tests for the second-roast findings: each one pins a failure
the roast reproduced, so it cannot come back quietly."""
import json
import os
import time

import pytest

from conftest import HOME, cleanse, evolve, ledger


def _fake_ledger(rows):
    d = HOME / ".hermes/plugin-data/antibeaurocracy"
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def _fake_count():
    fs = [f for f in cleanse.run()["findings"] if f["stone"] == "fake-gate"]
    return fs[0]["interruptions"] if fs else 0


def test_a_card_counts_by_its_latest_event():
    now = time.time()
    _fake_ledger([
        {"ts": now, "event": "block_attempt", "task": "t_1", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "asked", "task": "t_1", "verdict": "F1-ack"},          # Selenite asked: cleared
        {"ts": now, "event": "block_attempt", "task": "t_2", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "fail_open", "task": "t_2", "verdict": "F1-ack"},      # fail-open keeps it
        {"ts": now, "event": "block_attempt", "task": "t_3", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "declared", "task": "t_3", "declared": "needs_input"},  # Hermes's own kind
        {"ts": now, "event": "blocked_observed", "task": "t_4", "verdict": "F2-relay", "conf": 0.9,
         "declared": "capability"},                                                      # declared: never fake
        {"ts": now, "event": "block_attempt", "task": "t_5", "verdict": "F1-ack", "conf": True},  # bool is not a score
    ])
    assert _fake_count() == 1  # only t_2


def test_a_later_fake_block_reopens_a_cleared_card():
    now = time.time()
    _fake_ledger([
        {"ts": now, "event": "asked", "task": "t_1", "verdict": "F1-ack"},
        {"ts": now + 1, "event": "blocked_observed", "task": "t_1", "verdict": "F1-ack", "conf": 0.8},
    ])
    assert _fake_count() == 1


def test_runbooks_flag_steps_not_mentions(tmp_path):
    rb = tmp_path / "RUNBOOK.md"
    rb.write_text("This flow is friction-free.\nThe app supports 2FA and OTP codes.\nFrictionless setup.\n")
    assert not [f for f in cleanse.run(paths=[rb])["findings"] if f["stone"] == "runbook"]
    rb.write_text("Manual step: you need to paste the token.\n")
    assert [f for f in cleanse.run(paths=[rb])["findings"] if f["stone"] == "runbook"]


@pytest.mark.parametrize("bad", ["not json", "[]", '{"silent": []}', '{"last": "x", "silent": {}}',
                                 '{"last": 0, "silent": {"curse": "lots"}}', '{"last": 0, "silent": {"curse": null}}'])
def test_a_damaged_evolve_state_resets_instead_of_crashing(bad):
    ledger.STATE.mkdir(mode=0o700)
    (ledger.STATE / "evolve-state.json").write_text(bad)
    assert evolve.build(30).exists()
    st = json.loads((ledger.STATE / "evolve-state.json").read_text())
    assert isinstance(st["silent"], dict)


def test_silence_only_counts_what_was_measured(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(evolve.time, "time", lambda: clock[0])
    silent = lambda: json.loads((ledger.STATE / "evolve-state.json").read_text())["silent"]  # noqa: E731
    evolve.build(30)  # no report, no Calm rows: nothing measured
    assert not any(silent().values())
    ledger.add("calm", "curse")
    clock[0] += 2 * 86400
    evolve.build(30)  # Calm rows measure the Calm categories only
    s = silent()
    assert s["curse"] == 0 and s["over_asking"] == 1 and s["human_gate"] == 0
    f = ledger.STATE / "report-a.json"
    f.write_text(json.dumps({"counts": {"curse": 1}}))
    clock[0] += 2 * 86400
    evolve.build(30)  # a new miner report measures everything
    assert silent()["human_gate"] == 1
    clock[0] += 2 * 86400
    evolve.build(30)  # the same report again is not a new measurement
    assert silent()["human_gate"] == 1


def test_evolve_redacts_notes_and_leaves_the_pr_to_the_human():
    ledger.add("miss", "x", note="mail a.b@example.com about it")
    ledger.add("fp", "y", note="token ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    text = evolve.build(30).read_text()
    assert "@example.com" not in text and "ghp_" not in text
    assert "Opening a PR is the human's decision" in text and "one PR" not in text


@pytest.mark.parametrize("raw,gone", [
    ("mail me at a.b@example.com", "a.b@example.com"),
    ("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
    ("password=hunter2hunter2", "hunter2hunter2"),
    ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
    ("sk-proj-abc123def456ghi789", "sk-proj-abc123def456ghi789"),
    ("glpat-abcdefghij0123456789", "glpat-abcdefghij0123456789"),
    ("https://user:pass@host/x", "user:pass"),
    ("host 203.0.113.7", "203.0.113.7"),
    ("v6 2001:db8::1", "2001:db8::1"),
])
def test_ledger_redacts_secrets_before_writing(raw, gone):
    ledger.add("miss", "k", note=raw)
    row = [r for r in ledger.rows() if r["kind"] == "miss"][-1]
    assert gone not in row["note"]


def test_redaction_leaves_plain_words_alone():
    assert ledger.redact("pip install from a lockfile") == "pip install from a lockfile"
    assert ledger.redact("ratio 3:2 at 10:30") == "ratio 3:2 at 10:30"
