import json
import os
import stat
import sys
import time

from conftest import HOME, cleanse, evolve, ledger, mine

GOOD = "---\nname: {n}\ndescription: Use when testing.\n---\n\n# {n}\n"


def _skill(root, name, text=None):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text if text is not None else GOOD.format(n=name))
    return d


def _checks(report):
    return {(f["stone"], f["check"]) for f in report["findings"]}


def test_empty_home_has_no_findings_and_selenite_is_clean():
    r = cleanse.run()
    assert r["findings"] == [] and r["errors"] == []


def test_skill_checks():
    root = HOME / ".claude/skills"
    _skill(root, "ok")
    _skill(root, "nofm", "> a note above the frontmatter\n---\nname: nofm\ndescription: x\n---\n")
    _skill(root, "folder", GOOD.format(n="other"))
    _skill(root, "longdesc", "---\nname: longdesc\ndescription: " + "x" * 1100 + "\n---\n")
    _skill(root, "refs", GOOD.format(n="refs") + "See `references/gone.md` and `scripts/here.py`.\n")
    (root / "refs/scripts").mkdir(); (root / "refs/scripts/here.py").write_text("")
    (root / "dangling").symlink_to(HOME / "nowhere")
    _skill(HOME / ".agents/skills", "ok")  # a second, separate copy of `ok`
    r = cleanse.run()
    got = {(f["check"], f["where"].split("/skills/")[-1].split("/")[0]) for f in r["findings"] if f["stone"] == "skill"}
    assert ("no-frontmatter", "nofm") in got
    assert ("name-mismatch", "folder") in got
    assert ("long-description", "longdesc") in got
    assert ("broken-reference", "refs") in got
    assert ("dangling-link", "dangling") in got
    assert any(f["check"] == "drift" and "ok" in f["where"] for f in r["findings"])
    assert not any(c == "broken-reference" and "here.py" in w for c, w in got)


def test_linked_copies_are_not_drift():
    src = _skill(HOME / "src", "shared")
    for agent in (".claude/skills", ".agents/skills"):
        (HOME / agent).mkdir(parents=True)
        (HOME / agent / "shared").symlink_to(src)
    assert ("skill", "drift") not in _checks(cleanse.run())


def test_plugin_checks():
    p = HOME / ".hermes/plugins"
    (p / "nomanifest").mkdir(parents=True); (p / "nomanifest/__init__.py").write_text("")
    (p / "otherformat").mkdir(); (p / "otherformat/plugin.json").write_text("{}")
    (p / "empty").mkdir()
    (p / "legacy").mkdir(); (p / "legacy/plugin.yaml").write_text("name: legacy\n")
    (p / "modern").mkdir(); (p / "modern/plugin.yaml").write_text("name: m\nmanifest_version: 2\n")
    where = {(f["check"], f["where"].rsplit("/", 2)[-2 if f["where"].endswith(".yaml") else -1])
             for f in cleanse.run()["findings"]}
    assert ("no-manifest", "nomanifest") in where
    assert ("empty-plugin", "empty") in where
    assert ("old-manifest", "legacy") in where
    assert not any(w in ("otherformat", "modern") for _, w in where)


def test_missing_hook_script_ranks_above_drift():
    (HOME / ".claude").mkdir()
    (HOME / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/gone.sh --x"},
                   {"type": "command", "command": "echo hi"}]}]}}))
    p = HOME / ".hermes/plugins/legacy"; p.mkdir(parents=True); (p / "plugin.yaml").write_text("name: l\n")
    fs = cleanse.run()["findings"]
    assert fs[0]["check"] == "missing-hook-script" and "~/.claude/hooks/gone.sh" in fs[0]["problem"]
    assert str(HOME) not in json.dumps(fs)


def test_ledger_findings_rank_first_and_respect_fixes():
    for _ in range(4):
        ledger.add("approval", "rm-rf-tmp")
    for _ in range(3):
        ledger.add("approval", "git-push")
    ledger.add("fix", "approval:git-push")
    for _ in range(2):
        ledger.add("gate", "gh-login")
    (HOME / ".claude/skills/x").mkdir(parents=True); (HOME / ".claude/skills/x/SKILL.md").write_text("no fm")
    fs = cleanse.run()["findings"]
    assert [f["where"] for f in fs[:2]] == ["rm-rf-tmp", "gh-login"]
    assert not any(f["where"] == "git-push" for f in fs)


def test_runbooks_and_peers(tmp_path):
    rb = tmp_path / "RUNBOOK.md"
    rb.write_text("Step 1: you need to log in to the console.\nStep 2: run gh auth login.\n")
    peer = HOME / ".hermes/plugin-data/antibeaurocracy"; peer.mkdir(parents=True)
    now = time.time()
    peer.joinpath("ledger.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": now, "event": "block", "verdict": "F1-ack"}, {"ts": now, "event": "block", "verdict": "WALL"},
        {"ts": now - 90 * 86400, "event": "block", "verdict": "FAKE"}, "junk"]))
    fs = cleanse.run(paths=[rb])["findings"]
    assert any(f["check"] == "manual-steps" and f["problem"].startswith("2 ") for f in fs)
    peer_f = [f for f in fs if f["stone"] == "peer"]
    assert len(peer_f) == 1 and peer_f[0]["interruptions"] == 1


def test_a_broken_adapter_does_not_hide_the_others(monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")
    monkeypatch.setattr(cleanse, "CHECKS", [boom, cleanse.check_ledger])
    for _ in range(3):
        ledger.add("approval", "k")
    r = cleanse.run()
    assert r["errors"] == ["boom: RuntimeError"] and r["findings"]


def test_report_private_and_capped():
    for i in range(12):
        f = ledger.STATE / f"cleanse-old{i:02d}.json"
        ledger.STATE.mkdir(mode=0o700, exist_ok=True)
        f.write_text("{}"); os.utime(f, (time.time() - 1000 - i,) * 2)
    path = cleanse.write(cleanse.run())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(list(ledger.STATE.glob("cleanse-*.json"))) == cleanse.KEEP
    assert cleanse.latest()["schema"] == "selenite.cleanse/1"


def test_evolve_uses_newest_report_only():
    ledger.STATE.mkdir(mode=0o700)
    for i, n in enumerate((5, 7)):
        f = ledger.STATE / f"report-{i}.json"
        f.write_text(json.dumps({"counts": {"curse": n}})); os.utime(f, (time.time() - 10 + i,) * 2)
    text = evolve.build(30).read_text()
    assert "- curse: 7" in text and "- curse: 12" not in text


def test_evolve_prune_needs_two_real_cycles(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(evolve.time, "time", lambda: clock[0])
    evolve.build(30)
    first = json.loads((ledger.STATE / "evolve-state.json").read_text())["silent"]
    assert first["curse"] == 1
    evolve.build(30)  # a re-draft the same day is not a new cycle
    assert json.loads((ledger.STATE / "evolve-state.json").read_text())["silent"]["curse"] == 1
    clock[0] += 2 * 86400
    text = evolve.build(30).read_text()
    assert "Category `curse` silent for 2 cycle(s): move it to references/compost.md" in text
    assert stat.S_IMODE((ledger.STATE / "evolve-state.json").stat().st_mode) == 0o600


def test_evolve_lists_cleanse_findings():
    for _ in range(3):
        ledger.add("approval", "npm-publish")
    cleanse.write(cleanse.run())
    assert "npm-publish" in evolve.build(30).read_text().split("## Recurring")[0]


def test_redact():
    s = mine.redact(f"a.b@x.io 203.0.113.7 https://u:p@h/x sk_abc123def456ghi789jkl012mno345pq {HOME}/x")
    assert s == "<email> <ip> https://<cred>@h/x <token> ~/x"


def test_mine_generic_reads_only_user_rows(tmp_path, monkeypatch):
    src = tmp_path / "logs"; src.mkdir()
    src.joinpath("a.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"role": "user", "content": "wtf just do it, mail me at a@b.co"},
        {"role": "assistant", "content": "wtf just do it"}, "junk"]))
    src.joinpath("notes.md").write_text("wtf just do it\n")  # inside a folder: ignored
    monkeypatch.setattr(sys, "argv", ["mine", "--days", "1", "--path", str(src), "--out", str(ledger.STATE)])
    assert mine.main() == 0
    report = json.loads(next(ledger.STATE.glob("report-*.json")).read_text())
    assert report["user_messages_scanned"] == 1 and "host" not in report
    samples = next(ledger.STATE.glob("samples-*.json")).read_text()
    assert "a@b.co" not in samples and "<email>" in samples
    assert stat.S_IMODE(next(ledger.STATE.glob("samples-*.json")).stat().st_mode) == 0o600
