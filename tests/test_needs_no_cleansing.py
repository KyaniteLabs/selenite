"""Requirement: Selenite needs no cleansing.

The real stone clears others and is never cleared itself. So Selenite must
never add upkeep: its own skill is always clean, it never lists itself as a
finding, and its state stays bounded however long it runs, with no human
pruning.
"""
import itertools
import json
import sys
import time

from conftest import HOME, cleanse, evolve, ledger, mine, plugin


def test_selenite_skill_is_clean():
    assert cleanse.needs_no_cleansing() == []


def test_selenite_is_never_a_finding():
    (HOME / ".claude/skills").mkdir(parents=True)
    (HOME / ".claude/skills/frictionless").symlink_to(cleanse.SELF_SKILL)
    report = cleanse.run()
    assert not any("frictionless" in f["where"] or f["stone"] == "selenite" for f in report["findings"])


def test_state_stays_bounded_without_a_human(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "ROTATE_BYTES", 2000)
    tick = itertools.count()
    real = time.strftime
    monkeypatch.setattr(time, "strftime", lambda fmt, *a: real(fmt, *a) + f"{next(tick):06d}")
    src = tmp_path / "a.jsonl"
    src.write_text(json.dumps({"role": "user", "content": "wtf just do it"}))
    for i in range(40):
        for _ in range(20):
            plugin.pre_llm_call(session_id=f"s{i}", user_message="wtf why did you stop")
            plugin.pre_approval_request(pattern_key=f"k{i}", surface="cli")
        cleanse.write(cleanse.run())
        evolve.build(30)
        monkeypatch.setattr(sys, "argv", ["mine", "--days", "1", "--path", str(src), "--out", str(ledger.STATE)])
        mine.main()
    assert next(tick) > 100  # distinct stamps, so the caps really were exercised
    names = [p.name for p in ledger.STATE.iterdir()]
    assert sum(n.startswith("cleanse-") for n in names) <= cleanse.KEEP
    assert sum(n.startswith("proposal-") for n in names) <= evolve.KEEP
    assert sum(n.startswith("report-") for n in names) <= mine.REPORT_KEEP
    assert sum(n.startswith("samples-") for n in names) <= mine.SAMPLE_KEEP
    assert sum(n.endswith(".jsonl") for n in names) <= 2
    assert sum(p.stat().st_size for p in ledger.STATE.iterdir()) < 3 * 2000 + 200_000
