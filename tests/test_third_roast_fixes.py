"""Regression tests for the third-roast findings (pre-submission). Each pins one
failure the roast traced, so it cannot come back quietly."""
import os
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta, datetime
from pathlib import Path

import pytest

from conftest import NON_ROOT_ONLY, REPO, cleanse, evolve, ledger, mine
from test_fake_gate_audit_plugin import RELAY, _load_plugin, _selenite

def _status_db(home: Path, cards: dict[str, str], kinds: dict[str, str] | None = None) -> Path:
    db = home / "kanban" / "boards" / "demo" / "kanban.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("create table if not exists tasks (id text primary key, status text, block_kind text)")
    for tid, st in cards.items():
        con.execute("insert or replace into tasks values (?, ?, ?)", (tid, st, (kinds or {}).get(tid)))
    con.commit()
    con.close()
    return db


# 1. Hermes fires no hook on unblock or archive: the badge is reconciled against the board.

def test_an_unblocked_or_archived_card_loses_its_badge(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, name="sel_reconcile")
    sel = _selenite("sel_reconcile")
    for t in ("t_arch", "t_ready", "t_still", "t_gone"):
        ctx.hooks["kanban_task_blocked"](task_id=t, board="demo", reason="manual login needed on the console")
    assert {"kanban:t_arch", "kanban:t_ready", "kanban:t_still", "kanban:t_gone"} <= sel._open_badges()
    _status_db(tmp_path, {"t_arch": "archived", "t_ready": "ready", "t_still": "blocked"})
    sel._reconciled_at[0] = 0.0
    ctx.hooks["on_kanban_dispatch_tick"]()
    fixed = sel.ledger.fixed_keys()
    assert {"kanban:t_arch", "kanban:t_ready"} <= fixed
    assert "kanban:t_still" not in fixed      # still blocked on the board
    assert "kanban:t_gone" not in fixed       # unknown is not cleared
    notes = {r["key"]: r["note"] for r in sel.ledger.rows() if r["kind"] == "fix"}
    assert notes["kanban:t_arch"] == "task archived"


def test_any_update_to_a_badged_card_checks_the_board(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, name="sel_upd")
    sel = _selenite("sel_upd")
    ctx.hooks["kanban_task_blocked"](task_id="t_u", board="demo", reason="manual login needed on the console")
    _status_db(tmp_path, {"t_u": "ready"})
    ctx.hooks["on_kanban_task_updated"](task_id="t_u", changed_fields=["assignee"])
    assert "kanban:t_u" in sel.ledger.fixed_keys()


def test_the_reconcile_runs_at_most_once_a_minute(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, name="sel_rate")
    sel = _selenite("sel_rate")
    calls = []
    monkeypatch.setattr(sel, "reconcile_badges", lambda *a: calls.append(1) or 0)
    sel._reconciled_at[0] = 0.0
    for _ in range(5):
        ctx.hooks["on_kanban_dispatch_tick"]()
    assert len(calls) == 1


# 2. A FAKE verdict already says the approval is agent-to-agent.

def test_a_fake_approval_wait_is_not_a_human_step(tmp_path, monkeypatch):
    _load_plugin(tmp_path, monkeypatch, name="sel_route")
    sel = _selenite("sel_route")
    from antibeaurocracy_core.classify import FAKE, classify
    reason = "waiting on platform approval before I merge"
    v = classify(reason)
    assert v.cls == FAKE and v.evidenced
    assert sel.lands_on_a_human(reason, v) is False
    login = reason + "; then I need to log in to the registry"
    assert sel.lands_on_a_human(login, classify(login)) is True


# 3. Hermes may re-kind a block when it stores it; the stored kind wins over the echo.

def test_the_stored_kind_wins_over_the_echoed_kind(tmp_path, monkeypatch):
    for k in ("HERMES_KANBAN_DB", "HERMES_KANBAN_HOME", "HERMES_KANBAN_BOARD"):
        monkeypatch.delenv(k, raising=False)
    _, ctx = _load_plugin(tmp_path, monkeypatch, name="sel_rekind")
    sel = _selenite("sel_rekind")
    args = {"task_id": "t_k", "reason": "waiting for the parent card to land", "kind": "dependency"}
    ctx.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="s")
    _status_db(tmp_path, {"t_k": "blocked"}, kinds={"t_k": "needs_input"})  # Hermes parked it for a person
    ctx.hooks["kanban_task_blocked"](task_id="t_k", board="demo", reason=args["reason"])
    assert ("blocked", "kanban:t_k") in [(r["kind"], r["key"]) for r in sel.ledger.rows()]


# 6. Bookkeeping never breaks a turn, even on a read-only home.

@NON_ROOT_ONLY
def test_a_read_only_home_never_raises_from_the_facet(tmp_path, monkeypatch):
    mod, _ = _load_plugin(tmp_path, monkeypatch, name="sel_ro")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        monkeypatch.setenv("HERMES_HOME", str(ro))
        mod._ledger("block_attempt", task="t_1")
        v, _kind = mod.observe_block(task_id="t_1", reason=RELAY)
        assert v is not None
    finally:
        ro.chmod(0o700)


# 7. Slash-command counts.

@pytest.mark.parametrize("text,want", [("²", 15), ("0", 1), ("-3", 15), ("9999", 500), ("abc", 15), ("7", 7), ("", 15)])
def test_slash_counts_are_whole_and_clamped(tmp_path, monkeypatch, text, want):
    mod, _ = _load_plugin(tmp_path, monkeypatch, name="sel_whole")
    assert mod._whole(text, 15) == want


def test_ledger_command_survives_odd_digits(tmp_path, monkeypatch):
    mod, _ = _load_plugin(tmp_path, monkeypatch, name="sel_cmd")
    for i in range(3):
        mod._ledger("block_attempt", task=f"t_{i}")
    out = mod.slash("ledger ²", platform="cli")
    assert "Traceback" not in out and out.strip()  # the default count, not a crash
    one = mod.slash("ledger 0", platform="cli")
    assert len(one.strip().splitlines()) == 1  # "0" means one line, never the whole ledger


# 12. No fcntl (Windows): the facet still imports and counts refusals.

def test_gates_work_without_fcntl(tmp_path):
    code = ("import sys; sys.modules['fcntl'] = None\n"
            "from antibeaurocracy_core.gates import RefusalStore\n"
            f"s = RefusalStore({str(tmp_path / 'r.json')!r}, ttl_s=60)\n"
            "print(s.transition('k', lambda p: ('ok', p + 1)))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    assert "('ok', 1)" in out.stdout


# 13. A home path with ?, # or % still opens the right board, read-only.

def test_odd_home_paths_open_the_right_board(tmp_path):
    from antibeaurocracy_core import audit
    home = tmp_path / "a#b?c%20d"
    db = _status_db(home, {"t_1": "archived"})
    assert audit.card_statuses(["t_1", "t_x"], [db]) == {"t_1": "archived"}
    con = sqlite3.connect(home / "state.db")
    con.execute("create table messages (role text, content text, timestamp real)")
    con.execute("insert into messages values ('user', 'I have to log in again', ?)", (time.time(),))
    con.commit(); con.close()
    assert [t for _, _, t in mine.iter_hermes(home / "state.db", 0)] == ["I have to log in again"]


# 4. The miner writes where every other Selenite reader looks.

def test_miner_reports_land_in_the_state_chain(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mine.py", "--days", "1"])
    assert mine.main() == 0
    capsys.readouterr()
    assert ledger.newest("report-*.json")
    assert evolve.latest_report() is not None


@NON_ROOT_ONLY
def test_miner_on_a_read_only_home_exits_cleanly(monkeypatch, tmp_path, capsys):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        monkeypatch.setattr(ledger, "state_dirs", lambda: [ro / "selenite"])
        monkeypatch.setattr(sys, "argv", ["mine.py", "--days", "1"])
        assert mine.main() == 1
        assert "SELENITE_STATE" in capsys.readouterr().err
    finally:
        ro.chmod(0o700)


# 5. Evolve and the dashboard follow the same fallback.

@NON_ROOT_ONLY
def test_evolve_falls_back_and_is_found(monkeypatch, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        monkeypatch.setattr(ledger, "STATE", ro / "selenite")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
        out = evolve.build(30)
        # a user-wide fallback keeps this home's files in its own by-home subfolder
        mine = tmp_path / "xdg" / "selenite" / "by-home" / ledger._home_tag()
        assert out is not None and out.parent == mine
        assert (mine / "evolve-state.json").exists()
        assert ledger.newest("proposal-*.md")[0] == out
    finally:
        ro.chmod(0o700)


@NON_ROOT_ONLY
def test_evolve_with_no_writable_folder_returns_none(monkeypatch, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        monkeypatch.setattr(ledger, "state_dirs", lambda: [ro / "selenite"])
        assert evolve.build(30) is None
    finally:
        ro.chmod(0o700)


# 11. The cleanse timestamp carries its offset.

def test_cleanse_generated_is_utc_with_offset():
    stamp = cleanse.run(1)["generated"]
    assert datetime.fromisoformat(stamp).utcoffset() == timedelta(0)


# 9. The empty-state copy no longer promises a cleanse backfill.

def test_no_stale_backfill_copy():
    for f in ("desktop/plugin.js", "dashboard/dist/index.js"):
        assert "backfill" not in (REPO / f).read_text(encoding="utf-8")


def test_kanban_root_matches_real_hermes_profile_resolution(tmp_path, monkeypatch):
    source = os.environ.get("SELENITE_TEST_HERMES_SOURCE")
    if not source or not (Path(source) / "hermes_constants.py").is_file():
        pytest.skip("real Hermes source is not configured")
    sys.path.insert(0, source)
    try:
        from hermes_constants import get_default_hermes_root
    finally:
        sys.path.remove(source)

    hermes_root = tmp_path / "hermes-root"
    monkeypatch.setenv("HERMES_HOME", str(hermes_root / "profiles" / "worker"))
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    from antibeaurocracy_core.plugin import _kanban_dbs
    assert _kanban_dbs(None)[0] == get_default_hermes_root() / "kanban.db"

    shared_root = tmp_path / "shared-kanban"
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(shared_root))
    assert _kanban_dbs(None)[0] == shared_root / "kanban.db"


def test_classifiers_use_role_words_for_authority_and_capability():
    import importlib
    classifier = importlib.import_module("antibeaurocracy_core.classify")
    assert classifier._SEAT == r"(platform|security|design|engineering|governance|income|chief.?scientist)"
    assert classifier._ROLE == (
        r"(ceo|cto|cfo|coo|founders?|owner|operator|user|human|boss|board|executives?|manager|legal|customers?|"
        r"clients?|person)"
    )
    assert classifier._PRINCIPAL == r"(ceo|cto|cfo|coo|founders?|owner|operator|boss)"
    assert classifier.classify("Appeal is owner-held; no agent can clear it").cls == "WALL"
