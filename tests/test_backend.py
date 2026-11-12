import importlib.util
import json
import os
import stat
import sys
import time

import pytest

pytest.importorskip("fastapi", reason="backend tests need FastAPI: pip install -r requirements-test.txt")
pytest.importorskip("httpx", reason="backend tests need httpx: pip install -r requirements-test.txt")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from conftest import HOME, REPO, ledger  # noqa: E402

_spec = importlib.util.spec_from_file_location("selenite_api", REPO / "dashboard" / "plugin_api.py")
api = importlib.util.module_from_spec(_spec)
sys.modules["selenite_api"] = api
_spec.loader.exec_module(api)  # the way Hermes imports a plugin's dashboard API

U = "/api/plugins/selenite"


@pytest.fixture
def http():
    app = FastAPI()
    app.include_router(api.router, prefix=U)
    return TestClient(app)


def test_empty_state():
    o = api.overview(30)
    assert o["has_ledger"] is False and o["load"] == "clear" and "tide" not in o


def test_fix_regression_and_reopen():
    ledger.add("gate", "gh-login"); ledger.add("gate", "gh-login")  # recurring = asked twice or more
    time.sleep(0.01)
    ledger.add("fix", "gh-login")
    assert api.overview(30)["gates"][0]["fixed"] is True
    time.sleep(0.01); ledger.add("gate", "gh-login")
    assert api.overview(30)["gates"][0]["fixed"] is False


@pytest.mark.parametrize("kind,code", [("reopen", 200), ("fix", 200), ("fp", 200), ("miss", 200),
                                       ("gate", 422), ("calm", 422), ("'; drop", 422)])
def test_ui_may_post_only_some_kinds(http, kind, code):
    assert http.post(U + "/events", json={"kind": kind, "key": "x"}).status_code == code


@pytest.mark.parametrize("key,code", [("x" * 81, 422), ("../../etc/passwd", 422), ("-leading", 422), ("", 422),
                                      ("a\x00b", 422), ("a\nb", 422), ("/etc/passwd", 422), ("a/../b", 422),
                                          ("a b", 200), ("<token>", 200), ("café ⌘ login", 200), ("kanban:t_1", 200)])
def test_key_validation(http, key, code):
    assert http.post(U + "/events", json={"kind": "fix", "key": key}).status_code == code


@pytest.mark.parametrize("q", ["days=-5", "days=0", "days=366", "days=abc"])
def test_out_of_range_days_rejected(http, q):
    assert http.get(f"{U}/overview?{q}").status_code == 422


def test_load_thresholds():
    assert (api._load(0, False), api._load(1, False), api._load(3, False), api._load(2, True)) == \
        ("clear", "rising", "high", "high")


def test_blocked_task_cleared_by_fix():
    ledger.add("blocked", "kanban:t_9")
    assert "t_9" in api.overview(30)["blocked_tasks"]
    time.sleep(0.01); ledger.add("fix", "kanban:t_9")
    assert "t_9" not in api.overview(30)["blocked_tasks"]


def test_status_shape_and_cache(http):
    st = http.get(U + "/status").json()
    assert set(st) == {"load", "calm_24h", "open_today", "blocked_tasks", "state_dir"}
    assert str(HOME) not in st["state_dir"] or not str(ledger.STATE).startswith(str(HOME))
    ledger.add("gate", "p1")
    n = http.get(U + "/status").json()["open_today"]
    time.sleep(0.01); ledger.add("gate", "p2")
    assert http.get(U + "/status").json()["open_today"] == n + 1


def test_no_generic_module_names_leak():
    assert not {"ledger", "signals", "evolve", "cleanse", "mine"} & set(sys.modules)
    assert str(api.SCRIPTS) not in sys.path


def test_proposal_private_reused_and_capped(http):
    p = api.draft(30)
    assert stat.S_IMODE(os.stat(ledger.STATE / p["proposal"]["name"]).st_mode) == 0o600
    assert http.post(U + "/proposal?days=30").json()["reused"] is True
    (ledger.STATE / "proposal-zbig.md").write_text("y" * 50000)
    assert len(http.get(U + "/proposal").json()["proposal"]["text"]) <= 20000


def test_cleanse_routes(http):
    assert http.get(U + "/cleanse").json() == {"cleanse": None}
    for _ in range(3):
        ledger.add("approval", "deploy")
    first = http.post(U + "/cleanse").json()
    assert first["reused"] is False and first["cleanse"]["findings"][0]["where"] == "deploy"
    assert http.post(U + "/cleanse").json()["reused"] is True  # cooldown: no repeated sweeps
    latest = http.get(U + "/cleanse").json()["cleanse"]
    assert latest["total"] == first["cleanse"]["total"] and len(latest["findings"]) <= 25
    assert str(HOME) not in json.dumps(latest)


def test_rows_in_a_fallback_state_folder_reach_the_pane(tmp_path, monkeypatch):
    """A skill-only agent with no HERMES_HOME writes to a fallback folder; the pane must still see it,
    even before the preferred ledger file exists and after the fallback changes."""
    led = api.ledger
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    monkeypatch.setattr(led, "state_dirs", lambda: [led.STATE, fallback])
    for p in (led.LEDGER, led.ROTATED):
        p.unlink(missing_ok=True)
    row = {"ts": time.time(), "kind": "gate", "key": "fallback-only", "note": "", "agent": "x"}
    (fallback / "ledger.jsonl").write_text((json.dumps(row) + "\n") * 2)  # recurring = asked twice or more
    o = api.overview(30)
    assert o["has_ledger"] is True and [g["key"] for g in o["gates"]] == ["fallback-only"]
    time.sleep(0.01)
    with (fallback / "ledger.jsonl").open("a") as fh:
        fh.write((json.dumps({**row, "ts": time.time(), "key": "fallback-two"}) + "\n") * 2)
    assert {g["key"] for g in api.overview(30)["gates"]} == {"fallback-only", "fallback-two"}


# Third roast: badges follow the board, share the plugin's window, and a read-only home never 500s.

def _board(cards: dict[str, str]):
    import sqlite3
    db = HOME / ".hermes" / "kanban" / "boards" / "demo" / "kanban.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("create table if not exists tasks (id text primary key, status text)")
    con.executemany("insert or replace into tasks values (?, ?)", cards.items())
    con.commit(); con.close()


def test_status_drops_badges_for_cards_unblocked_or_archived_on_the_board(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(HOME / ".hermes"))
    api._status_cache.update(ts=0.0, ids=())
    for t in ("t_arch", "t_ready", "t_still", "t_gone"):
        ledger.add("blocked", f"kanban:{t}")
    _board({"t_arch": "archived", "t_ready": "ready", "t_still": "blocked"})
    # t_gone is on no board that read cleanly, so it was deleted: its badge goes too.
    assert api.status()["blocked_tasks"] == ["t_still"]


def test_a_45_day_old_block_still_badges_in_status():
    api._status_cache.update(ts=0.0, ids=())
    STATE = ledger.writable_state()
    row = {"ts": time.time() - 45 * 86400, "kind": "blocked", "key": "kanban:t_old", "note": "", "agent": ""}
    with open(STATE / "ledger.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    assert "t_old" in api.status()["blocked_tasks"]


def test_draft_on_a_read_only_home_says_so_instead_of_500(http, monkeypatch, tmp_path):
    monkeypatch.setattr(api.evolve, "build", lambda days: None)
    monkeypatch.setattr(api, "_latest_proposal", lambda: None)
    r = http.post(U + "/proposal")
    assert r.status_code == 200 and r.json()["proposal"] is None and "SELENITE_STATE" in r.json()["error"]
