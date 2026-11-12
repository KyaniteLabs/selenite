"""Regressions from the 2026-11-11 dogfood on real board snapshots (M1, M2, L1, L3, L4)."""
import sqlite3

import pytest

from antibeaurocracy_core import HUMAN, WALL, classify
from antibeaurocracy_core import cli
from conftest import HOME, ledger
from test_dashboard_status import _load_api


@pytest.mark.parametrize("text", [
    "blocked: needs AWS credentials",
    "need new credentials",
    "needs credentials to deploy",
    "missing the owner's AWS credentials",
    "blocked on the owner's AWS credentials",
    "waiting for the npm token",
])
def test_needs_credentials_is_a_credentials_wall(text):
    v = classify(text)
    assert (v.cls, v.subtype) == (WALL, "credentials")


@pytest.mark.parametrize("text", ["no credentials needed", "need a credential-free desktop"])
def test_credential_mentions_that_deny_the_wall(text):
    assert classify(text).cls != WALL


@pytest.mark.parametrize("text", [
    "T014 needs the CEO's explicit word: GO-DATA vs HOLD",
    "CEO hands required: build host console access. CONSOLE / HOLD",
    "Owner adjudication needed on the merge order",
    "CEO words needed to ratify the plan",
    "CEO drain word: attest the receipt",
    "operator must pick: ship or HOLD",
])
def test_needs_input_asking_a_person_is_human(text):
    assert classify(text, kind="needs_input").cls == HUMAN


def test_hold_offered_as_an_answer_is_not_parking_but_a_bare_hold_still_is():
    assert classify("HOLD do not dispatch", kind="needs_input").label == "F5-parking-lot"
    assert classify("HOLD do not dispatch").label == "F5-parking-lot"
    assert classify("awaiting ACK from product agent").label == "F1-ack"


@pytest.mark.parametrize("argv", [["classify", ""], ["classify", "   "]])
def test_empty_classify_is_a_usage_error(argv, capsys):
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.strip()


def test_long_ledger_keys_are_marked_and_stay_distinct():
    a = ledger.add("gate", "x" * 90 + "a")
    b = ledger.add("gate", "x" * 90 + "b")
    assert a["truncated"] and b["truncated"]
    assert len(a["key"]) == len(b["key"]) == 80
    assert a["key"] != b["key"]
    assert "truncated" not in ledger.add("gate", "short-key")


def test_recurring_gates_name_cards_drop_deleted_ones_and_skip_one_offs(monkeypatch):
    api = _load_api(monkeypatch)
    hermes_home = HOME / ".hermes-l3"
    db = hermes_home / "kanban.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("create table tasks (id text primary key, status text, title text)")
    con.execute("insert into tasks values ('t_live', 'blocked', 'Rotate the deploy key')")
    con.commit()
    con.close()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    for _ in range(2):
        ledger.add("blocked", "kanban:t_live")
        ledger.add("blocked", "kanban:t_gone")
    ledger.add("gate", "asked-once")
    out = api.overview(days=30)
    keys = {g["key"]: g for g in out["gates"]}
    assert keys["kanban:t_live"]["title"] == "Rotate the deploy key"
    assert "kanban:t_gone" not in keys
    assert "asked-once" not in keys
    assert out["one_off_gates"] >= 1
