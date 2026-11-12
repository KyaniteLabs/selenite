"""Fixes for the 2026-11-11 dogfood of main 1795573: seven findings, one test group each."""
import json
import os
import time
from pathlib import Path

import pytest

from conftest import REPO, ledger
from antibeaurocracy_core.classify import FAKE, HUMAN, WALL, classify

TAB = (REPO / "dashboard/dist/index.js").read_text(encoding="utf-8")


# 1 (High). Real credential walls were read as stale waits with "or close the card".

@pytest.mark.parametrize("text", [
    "needs credentials",
    "needs Ana's credentials to push to npm",
    "needs Ana’s token to publish",
    "requires the npm token, which only Ana has",
    "only Ana has the PyPI token",
    "waiting on Ana to log in to npm",
    "needs to authenticate with the registry",
    "missing npm token",
])
def test_credential_walls_stand(text):
    v = classify(text)
    assert v.cls == WALL and "credentials" in v.subtype.split(", "), (text, v)


@pytest.mark.parametrize("text", [
    "need a credential-free desktop",
    "Preserved the custody disposition for the credential handoff notes",
    "no credentials required",
])
def test_credential_words_alone_are_not_walls(text):
    assert classify(text).cls != WALL


# 6 (Low). Holds with a named next actor were read as stale waits.

def test_until_a_seat_reviews_is_an_agent_ack():
    v = classify("blocked until Security reviews")
    assert v.subtype == "F1-ack" and v.evidenced


def test_an_unknown_approver_is_a_persons_queue_not_stale():
    v = classify("waiting for approval from CoS")
    assert v.cls == HUMAN and v.confidence == 0.5 and v.evidenced
    assert "close the card" not in v.action and "seats" in v.action


def test_a_configured_seat_still_reads_as_fake():
    import sys
    C = sys.modules["antibeaurocracy_core.classify"]
    try:
        C.configure(seats=["CoS"])
        assert classify("waiting for approval from CoS").cls == FAKE
    finally:
        C.configure()


# 2 (Medium). Ledgers from other Hermes homes leaked in through the shared fallback.

def _row(path: Path, key: str, kind: str = "gate"):
    path.mkdir(parents=True, exist_ok=True)
    with (path / "ledger.jsonl").open("a") as fh:
        fh.write(json.dumps({"ts": time.time(), "kind": kind, "key": key, "note": "", "agent": ""}) + "\n")


def _as_home(monkeypatch, tmp_path, name):
    hermes = tmp_path / name
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(ledger, "STATE", hermes / "plugin-data/selenite")


def test_another_homes_rows_in_the_shared_folder_are_not_read(monkeypatch, tmp_path):
    _as_home(monkeypatch, tmp_path, "home-a")
    _row(tmp_path / "user/.local/state/selenite", "forgejo-org-repo-create")  # another home's legacy row
    _row(ledger.STATE, "mine")
    assert [r["key"] for r in ledger.rows()] == ["mine"]


def test_a_fallback_write_is_found_by_its_own_home_only(monkeypatch, tmp_path):
    _as_home(monkeypatch, tmp_path, "home-a")
    a_fallback = ledger.state_dirs()[-1]
    assert a_fallback.parent == tmp_path / "user/.local/state/selenite/by-home"
    _row(a_fallback, "a-gate")
    assert "a-gate" in {r["key"] for r in ledger.rows()}

    _as_home(monkeypatch, tmp_path, "home-b")
    assert ledger.state_dirs()[-1] != a_fallback
    assert "a-gate" not in {r["key"] for r in ledger.rows()}
    ledger.add("fix", "a-gate")  # "Mark fixed" in B ...
    _as_home(monkeypatch, tmp_path, "home-a")
    assert "a-gate" not in ledger.fixed_keys()  # ... never clears A's gate


def test_the_default_home_still_reads_its_own_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(ledger, "STATE", tmp_path / "user/.local/state/selenite")
    _row(ledger.STATE, "legacy")
    assert ledger.state_dirs() == [ledger.STATE]
    assert [r["key"] for r in ledger.rows()] == ["legacy"]


def test_the_home_tag_names_no_path():
    assert len(ledger._home_tag()) == 12 and "/" not in ledger._home_tag()


# 3 (Medium). "Mark fixed" had no undo in the dashboard tab.

def test_the_tab_can_undo_and_reopen_a_fix():
    assert 'mark("reopen", undo)' in TAB and '"Undo"' in TAB
    assert 'mark("reopen", g.key)' in TAB and '"Reopen"' in TAB


def test_reopen_after_fix_reopens(monkeypatch, tmp_path):
    _as_home(monkeypatch, tmp_path, "home-a")
    _row(ledger.STATE, "npm-otp")
    ledger.add("fix", "npm-otp")
    assert "npm-otp" in ledger.fixed_keys()
    time.sleep(0.01)
    ledger.add("reopen", "npm-otp")
    assert "npm-otp" not in ledger.fixed_keys()


# 4 (Medium). The 7d/30d/90d selector showed no visible selected state.

def test_the_selected_window_has_a_visible_cue_beyond_the_theme():
    assert '"aria-pressed": on' in TAB
    assert "style: on ? PICKED : TAP" in TAB and "✓ " in TAB
    # A dark inset ring vanished on the dark theme (verified in the browser); the pick inverts instead.
    assert 'border: "2px solid currentColor"' in TAB and 'color: "inherit"' in TAB


# 5 (Low). The tab promised "what to clear next" without Cleanse or Evolve.

def test_the_tab_shows_cleanse_and_evolve():
    assert 'API + "/cleanse"' in TAB and 'post("/cleanse?days="' in TAB and "Clear next" in TAB
    assert 'API + "/proposal"' in TAB and 'post("/proposal?days="' in TAB
    assert TAB.count("h(Cleanse, { days: days })") == 2  # with and without a ledger
    assert '"Drafted " + prop.name' in TAB and "open: fresh" in TAB  # a draft confirms itself


# 7 (Low). Tap targets were 26–28 px.

def test_every_tab_button_is_at_least_44px():
    buttons = TAB.count("h(Button, {")
    assert buttons and buttons == TAB.count("style: TAP") + TAB.count("style: on ? PICKED : TAP")
    assert "minHeight: 44, minWidth: 44" in TAB


# Self-application: the dogfooder's own open holds, read by Selenite, missed two real walls.

@pytest.mark.parametrize("text,wall", [
    ("upstream NousResearch catalog PR needs Ana's explicit yes before posting publicly", "publish"),
    ("open the upstream PR on the public repo", "publish"),
    ("waiting on Ana to fill the Typeform with his own login", "credentials"),
])
def test_my_own_holds_that_are_real_walls(text, wall):
    v = classify(text)
    assert v.cls == WALL and wall in v.subtype.split(", "), (text, v)


@pytest.mark.parametrize("text", [
    "gateway restart queued for 11:00 PT, waiting for it to run",
    "posted the notes in our own channel",
    "the PR upstream of this one in the stack merged",
])
def test_my_own_stale_waits_stay_fake(text):
    assert classify(text).cls != WALL
