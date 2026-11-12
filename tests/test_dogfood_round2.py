"""Regressions from the 2026-11-11 dogfood (round 2).

The credentials wall missed "needs credentials" (it needed two spaces), deliberate holds read as
parking lots, a running CI check read as a stale wait, SELENITE_STATE leaked other seats' rows,
cleanse counted one symlinked skill once per agent, mine hid its own samples path, and counts-mode
audit said a board failed without saying which.
"""
import json
import sqlite3
import sys

import pytest

from antibeaurocracy_core import DEPENDENCY, FAKE, MACHINERY, WALL, classify
from antibeaurocracy_core import audit, cli
from conftest import HOME, cleanse, ledger, mine


@pytest.mark.parametrize("text", [
    "needs credentials", "need a token", "needs a new token", "requires credentials",
    "needs the API key", "Blocked: requires production deploy credentials from the operator",
])
def test_credentials_wall_takes_the_common_phrasings(text):
    v = classify(text)
    assert v.cls == WALL and "credentials" in v.subtype


def test_a_negated_credential_is_still_not_a_wall():
    assert classify("no credentials required").cls != WALL


def test_production_deploy_as_a_noun_is_a_publish_wall():
    v = classify("Blocked on the production deploy")
    assert v.cls == WALL and v.subtype == "publish"


def test_work_running_in_another_lane_is_a_declared_hold():
    v = classify("Executed by zcode outside the gateway (worktree ~/w); supervisor merges. Do not dispatch.")
    assert v.cls == DEPENDENCY


def test_a_queue_throttle_is_a_declared_hold():
    v = classify("Created blocked so they do not auto-dispatch into an engineering queue that already has "
                 "98 open tasks (ledger row 55). Engineering implements it when the queue has capacity.")
    assert v.cls == DEPENDENCY


def test_a_bare_hold_is_still_a_parking_lot():
    v = classify("HOLD. Do not dispatch.")
    assert v.cls == FAKE and v.subtype == "F5-parking-lot"


def test_an_agent_ack_with_a_lane_named_is_still_fake():
    assert classify("Waiting for platform approval, handled by security").cls == FAKE


def test_waiting_for_ci_is_a_running_check_not_a_stale_wait():
    v = classify("Waiting for CI to finish")
    assert v.cls == MACHINERY and v.evidenced


def test_cli_refuses_empty_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", type("E", (), {"read": staticmethod(lambda: "   ")})())
    assert cli.main(["classify"]) == 2
    assert "nothing to classify" in capsys.readouterr().err


def test_explicit_state_reads_only_its_own_folder(tmp_path, monkeypatch):
    other = tmp_path / "hermes"
    (other / "plugin-data/selenite").mkdir(parents=True)
    row = {"ts": 9e9, "kind": "gate", "key": "other-seat", "note": "", "agent": "x"}
    (other / "plugin-data/selenite/ledger.jsonl").write_text(json.dumps(row) + "\n")
    monkeypatch.setenv("HERMES_HOME", str(other))
    assert ledger.state_dirs() == [ledger.STATE]
    ledger.add("gate", "mine")
    assert [r["key"] for r in ledger.rows()] == ["mine"]
    assert ledger.write_target() == ledger.STATE


def test_without_explicit_state_the_fallbacks_still_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path / "preferred")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    assert tmp_path / "hermes/plugin-data/selenite" in ledger.state_dirs()


def test_cleanse_counts_a_symlinked_skill_once():
    src = HOME / ".hermes/skills/broken"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("> note above the frontmatter\n---\nname: broken\ndescription: x\n---\n")
    for agent in (".claude/skills", ".agents/skills"):
        (HOME / agent).mkdir(parents=True)
        (HOME / agent / "broken").symlink_to(src)
    hits = [f for f in cleanse.run()["findings"] if f["check"] == "no-frontmatter"]
    assert len(hits) == 1


def test_mine_prints_its_samples_path_readably(tmp_path, monkeypatch, capsys):
    src = tmp_path / "logs"
    src.mkdir()
    src.joinpath("a.jsonl").write_text(json.dumps({"role": "user", "content": "just do it"}) + "\n")
    monkeypatch.setattr(sys, "argv", ["mine", "--days", "1", "--path", str(src), "--out", str(ledger.STATE)])
    assert mine.main() == 0
    err = capsys.readouterr().err
    line = next(x for x in err.splitlines() if x.startswith("private samples:"))
    assert "<token>" not in line and "samples-" in line


def test_counts_mode_names_the_board_that_failed(tmp_path, capsys):
    bad = tmp_path / ".hermes/kanban.db"
    bad.parent.mkdir(parents=True)
    sqlite3.connect(bad).execute("create table other(x)").connection.commit()
    assert cli.main(["audit", "--counts", "--no-rules", "--root", str(tmp_path / ".hermes")]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["board_errors"] == 1
    assert "could not read" in err and "kanban.db" in err


def test_a_locked_board_gets_one_retry(monkeypatch, tmp_path):
    calls = []

    def flaky(db, now=None):
        calls.append(db)
        return {"board": str(db), "error": "database is locked"} if len(calls) == 1 else {"board": str(db), "blocked": []}

    monkeypatch.setattr(audit, "_audit_board", flaky)
    monkeypatch.setattr(audit.time, "sleep", lambda s: None)
    assert "error" not in audit.audit_board(tmp_path / "k.db") and len(calls) == 2
