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

from conftest import HOME, REPO, cleanse, evolve, ledger, mine, plugin


def test_selenite_skills_are_clean():
    assert cleanse.needs_no_cleansing() == []


def test_a_dirty_facet_is_caught(monkeypatch, tmp_path):
    bad = tmp_path / "antipedantry"; bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter")
    monkeypatch.setattr(cleanse, "SELF_SKILL", tmp_path / "frictionless")
    for name in ("frictionless", "antibeaurocracy"):
        (tmp_path / name).symlink_to(REPO / "skills" / name)
    assert [f["check"] for f in cleanse.needs_no_cleansing()] == ["no-frontmatter"]


def test_selenite_is_never_a_finding():
    (HOME / ".claude/skills").mkdir(parents=True)
    for name in cleanse.SELF_SKILLS:
        (HOME / ".claude/skills" / name).symlink_to(cleanse.SELF_SKILL.parent / name)
    report = cleanse.run()
    assert not any(any(n in f["where"] for n in cleanse.SELF_SKILLS) or f["stone"] == "selenite"
                   for f in report["findings"])


def test_fake_gate_ledger_stays_bounded(tmp_path, monkeypatch):
    fg = plugin.fake_gates
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(fg, "LEDGER_ROTATE_BYTES", 2000)
    for i in range(400):
        fg._ledger("blocked_observed", task=f"t_{i}", verdict="F1-ack", conf=0.8)
    d = tmp_path / "plugin-data/antibeaurocracy"
    files = sorted(p.name for p in d.glob("ledger*.jsonl"))
    assert files == ["ledger.1.jsonl", "ledger.jsonl"]
    assert all((d / n).stat().st_size < 2200 for n in files)


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
            plugin.post_approval_response(pattern_key=f"k{i}", surface="cli", choice="once", decided_by="user")
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
