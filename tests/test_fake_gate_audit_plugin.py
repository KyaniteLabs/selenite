import importlib.util
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from antibeaurocracy_core import audit
from antibeaurocracy_core.gates import GateState, NudgeBox, RefusalStore, decide

ROOT = Path(__file__).resolve().parents[1]
RELAY = "Await the release agent to open the PR from my patch"


def _board(home: Path) -> Path:
    db = home / "kanban" / "boards" / "demo" / "kanban.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        create table tasks (id text primary key, title text, assignee text, status text, created_at real,
                            block_kind text, last_failure_error text);
        create table task_events (id integer primary key autoincrement, task_id text, kind text, payload text, created_at real);
    """)
    old = time.time() - 72 * 3600
    rows = [
        ("t_a", "FIX: thing", "eng", "blocked", None, "blocked", {"reason": "initial_status"}),
        ("t_b", "Ship patch", "eng", "blocked", None, "blocked", {"reason": "push denied HTTP 403; push=false"}),
        ("t_c", "Ship other", "eng", "blocked", None, "blocked", {"reason": "push=false on second repo"}),
        ("t_d", "Ruling", "product", "blocked", None, "blocked", {"reason": "Product must record the ruling"}),
        ("t_f", "Crashy", "eng", "blocked", "worker exited 1", "gave_up",
         {"failures": 3, "error": "worker exited 1", "trigger_outcome": "crashed", "retry_status": "exhausted"}),
        ("t_g", "Vague", "eng", "blocked", None, "blocked", {"reason": "Looking into it"}),
        ("t_e", "Run", "eng", "running", None, None, None),
    ]
    for tid, title, who, st, err, ev, payload in rows:
        con.execute("insert into tasks values (?,?,?,?,?,?,?)", (tid, title, who, st, old, None, err))
        if payload:
            con.execute("insert into task_events (task_id, kind, payload, created_at) values (?,?,?,?)",
                        (tid, ev, json.dumps(payload), old))
    con.commit()
    con.close()
    return db


def test_audit_board(tmp_path):
    db = _board(tmp_path)
    before = db.stat().st_mtime
    res = audit.run(roots=[tmp_path], rule_paths=[])
    s = res["summary"]
    assert s["blocked"] == 6 and s["running"] == 1
    assert s["by_label"]["WALL"] == 2
    assert s["auto_blocked"] == 1 and s["created_blocked"] == 1
    assert s["fake"] == 1  # only the evidenced F3; the vague, created and crashed cards are not counted
    assert s["unclear"] == 1
    assert len(s["shared_causes"]["repo-write-permission"]) == 2
    assert "auto-blocked" in res["markdown"]
    assert db.stat().st_mtime == before  # read-only


def test_board_errors_are_reported(tmp_path):
    bad = tmp_path / "kanban.db"
    sqlite3.connect(bad).execute("create table other (x)").connection.close()
    s = audit.run(roots=[tmp_path], rule_paths=[])["summary"]
    assert s["errors"] and "could not be read" in audit.headline(s)


def test_single_card_causes_hidden(tmp_path):
    _board(tmp_path)
    s = audit.run(roots=[tmp_path], rule_paths=[])["summary"]
    assert all(len(v) >= 2 for v in s["shared_causes"].values())


def test_counts_only_has_no_names(tmp_path):
    _board(tmp_path)
    c = json.dumps(audit.counts_only(audit.run(roots=[tmp_path], rule_paths=[])["summary"]))
    for leak in ("t_b", "Ship patch", "product", "eng", "Ruling"):
        assert leak not in c


def test_audit_rules(tmp_path):
    f = tmp_path / "AGENTS.md"
    f.write_text("No seat is an approval gate.\nWait for platform sign-off.\nEscalate to ops.\nShip it.\n" * 3)
    r = audit.audit_rules([f])[0]
    assert r["gate_lines"] >= 6 and r["has_anti_gate_clause"]


def test_audit_rules_skips_selenite_and_reports_unreadable(tmp_path):
    own = ROOT / "skills/antibeaurocracy/SKILL.md"
    locked = tmp_path / "CLAUDE.md"
    locked.mkdir()  # a directory is not a file: skipped quietly, as before
    f = tmp_path / "AGENTS.md"
    f.write_text("Wait for platform sign-off.\n")
    f.chmod(0)
    try:
        rows = audit.audit_rules([own, locked, f])
    finally:
        f.chmod(0o600)
    import os
    if os.geteuid() == 0:
        pytest.skip("root reads unreadable files")
    assert [(r["path"], r.get("error")) for r in rows] == [(str(f), "PermissionError")]


# ---------------------------------------------------------------- gate state machine

@pytest.mark.parametrize("mode,over,prior,expect", [
    ("observe", True, 0, (GateState.PASS, 0)),
    ("nudge", False, 0, (GateState.PASS, 0)),
    ("nudge", True, 5, (GateState.NUDGE, 5)),
    ("ask", True, 0, (GateState.ASK, 1)),
    ("ask", True, 1, (GateState.ASK, 2)),
    ("ask", True, 2, (GateState.FAIL_OPEN, 2)),
    ("ask", False, 0, (GateState.PASS, 0)),
    ("enforce", True, 0, (GateState.ASK, 1)),
    ("bogus", True, 0, (GateState.PASS, 0)),
])
def test_decide_table(mode, over, prior, expect):
    assert decide(mode, over, prior, 2) == expect


def test_refusal_store_ttl_and_threads(tmp_path):
    st = RefusalStore(tmp_path / "r.json", ttl_s=100)
    st.transition("k", lambda p: (None, p + 1), now=1000)
    assert st.get("k", now=1050) == 1
    assert st.get("k", now=1200) == 0  # expired
    st2 = RefusalStore(tmp_path / "r2.json")
    ts = [threading.Thread(target=lambda: st2.transition("k", lambda p: (None, p + 1))) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert st2.get("k") == 20


def test_refusal_store_across_processes(tmp_path):
    path = tmp_path / "r.json"
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); from antibeaurocracy_core.gates import RefusalStore;"
            f"RefusalStore({str(path)!r}).transition('k', lambda p: (None, p + 1))")
    procs = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(6)]
    assert all(p.wait() == 0 for p in procs)
    assert RefusalStore(path).get("k") == 6


def test_nudgebox_ttl_and_cap():
    nb = NudgeBox(ttl_s=10, max_entries=3)
    nb.put("a", "x", now=0)
    assert nb.pop("a", now=20) is None  # stale
    for i in range(5):
        nb.put(str(i), "n", now=100)
    assert len(nb) == 3 and nb.pop("0", now=100) is None and nb.pop("4", now=100) == "n"


# ---------------------------------------------------------------- plugin

class FakeCtx:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.hooks, self.tools, self.commands, self.cli, self.sections, self.skills, self.blueprints = {}, {}, {}, {}, {}, {}, {}
        self.events = []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, cb, **_):
        self.hooks[name] = cb

    def register_tool(self, name, toolset, schema, handler, **_):
        assert schema["name"] == name
        self.tools[name] = handler

    def register_command(self, name, handler, description="", args_hint="", **_):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = (setup_fn, handler_fn)

    def register_system_prompt_section(self, id, content, **_):
        self.sections[id] = content

    def register_skill(self, name, path, description=""):
        assert Path(path).exists()
        self.skills[name] = path

    def register_automation_blueprint(self, key, **kw):
        self.blueprints[key] = kw

    def emit(self, event, payload=None):
        self.events.append((event, payload))
        return 0


def _load_plugin(home, monkeypatch, settings=None, name="selenite_fg_plugin"):
    """Load the whole Selenite plugin: the fake-gate facet registers through it, as in Hermes."""
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    ctx = FakeCtx(settings)
    mod.register(ctx)
    return mod.fake_gates, ctx  # the facet module, whose internals these tests probe


def _ledger(home):
    p = home / "plugin-data" / "antibeaurocracy" / "ledger.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_register_surface(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    assert {"pre_tool_call", "transform_tool_result", "on_kanban_dispatch_tick", "kanban_task_blocked"} <= set(ctx.hooks)
    assert {"bureaucracy_classify", "bureaucracy_audit"} <= set(ctx.tools)
    assert {"antibeaurocracy", "antipedantry", "frictionless"} == set(ctx.skills)
    assert {"antibeaurocracy", "fake-gate"} <= set(ctx.commands)
    assert "antibeaurocracy" in ctx.cli and ctx.skills and "weekly-audit" in ctx.blueprints
    assert not ctx.sections  # doctrine is off by default


def test_doctrine_opt_in_is_conditional(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"doctrine_section": True})
    text = next(iter(ctx.sections.values()))
    assert "Still stop for" in text and "Everything else is bureaucracy" not in text


def test_ask_asks_then_fails_open(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask", "max_refusals": 2})
    hook = ctx.hooks["pre_tool_call"]
    args = {"task_id": "t_x", "reason": RELAY}
    assert hook(tool_name="kanban_block", args=args, session_id="s")["action"] == "block"
    assert hook(tool_name="kanban_block", args=args, session_id="s")["action"] == "block"
    assert hook(tool_name="kanban_block", args=args, session_id="s") is None
    wall = {"task_id": "t_y", "reason": "npm publish fails: ENEEDAUTH"}
    assert hook(tool_name="kanban_block", args=wall, session_id="s") is None
    assert hook(tool_name="terminal", args={"command": "ls"}, session_id="s") is None
    events = [r["event"] for r in _ledger(tmp_path)]
    assert "asked" in events and "fail_open" in events


def test_old_enforce_setting_means_ask(tmp_path, monkeypatch):
    mod, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "enforce"})
    assert mod._mode() == "ask"
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY}, session_id="s")


def test_default_asks_once_per_card(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    call = lambda: ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY}, session_id="s")
    assert call() and call() is None


def test_question_offers_every_legitimate_kind_and_never_says_safe(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    msg = ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY}, session_id="s")["message"]
    for kind in ("kind=needs_input", "kind=dependency", "kind=capability"):
        assert kind in msg
    assert "credentials" in msg and "deletion" in msg and "safe" not in msg.lower()


@pytest.mark.parametrize("kind", ["needs_input", "dependency", "capability", "transient", "NEEDS_INPUT"])
def test_declared_kind_is_trusted_and_ledgered(tmp_path, monkeypatch, kind):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    args = {"task_id": "t_d", "reason": RELAY, "kind": kind}
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="s") is None
    rows = [r for r in _ledger(tmp_path) if r["event"] == "declared"]
    assert rows and rows[0]["declared"] == kind.lower() and rows[0]["verdict"]
    assert "reason" not in rows[0]


def test_unknown_kind_is_not_a_declaration(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    args = {"task_id": "t", "reason": RELAY, "kind": "wall"}
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="s")["action"] == "block"


def test_refusals_survive_a_respawned_worker(tmp_path, monkeypatch):
    settings = {"fake_gate_mode": "ask", "max_refusals": 2}
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_w")
    _, ctx = _load_plugin(tmp_path, monkeypatch, settings, name="p1")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_w")
    args = {"reason": RELAY}  # no task_id: the worker's env names the card
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="a")["action"] == "block"
    _, ctx2 = _load_plugin(tmp_path, monkeypatch, settings, name="p2")  # fresh module = respawned worker
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_w")
    assert ctx2.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="b")["action"] == "block"
    assert ctx2.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="c") is None


def test_kanban_create_is_not_gated(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_create", args={"title": "x", "initial_status": "blocked"}, session_id="s") is None


def test_unevidenced_fake_is_not_refused(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask", "min_confidence": 0.0})
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": "Looking into it"}, session_id="s") is None


def test_nudge_keyed_by_tool_call(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "nudge"})
    pre, post = ctx.hooks["pre_tool_call"], ctx.hooks["transform_tool_result"]
    a1 = {"task_id": "t_1", "reason": "Product must record the ruling"}
    a2 = {"task_id": "t_2", "reason": RELAY}
    assert pre(tool_name="kanban_block", args=a1, session_id="s", tool_call_id="c1") is None
    assert pre(tool_name="kanban_block", args=a2, session_id="s", tool_call_id="c2") is None
    out2 = json.loads(post(tool_name="kanban_block", args=a2, result='{"ok": true}', session_id="s", tool_call_id="c2"))
    assert out2["ok"] is True and "F2-relay" in out2["antibeaurocracy"]
    out1 = post(tool_name="kanban_block", args=a1, result="blocked t_1", session_id="s", tool_call_id="c1")
    assert out1.startswith("blocked t_1") and "F3-ownership-limbo" in out1
    assert post(tool_name="kanban_block", args=a1, result="again", session_id="s", tool_call_id="c1") is None


def test_lifecycle_observer_records_verdict_not_text(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    ctx.hooks["kanban_task_blocked"](task_id="t_9", board="demo", assignee="eng", run_id=1, reason=RELAY, profile_name="x")
    rec = _ledger(tmp_path)[-1]
    assert rec["event"] == "blocked_observed" and rec["verdict"] == "F2-relay"
    assert "release agent" not in json.dumps(rec)


def test_snapshot_per_home_with_inflight_guard(tmp_path, monkeypatch):
    _board(tmp_path)
    mod, ctx = _load_plugin(tmp_path, monkeypatch, {"snapshot_minutes": 60})
    tick = ctx.hooks["on_kanban_dispatch_tick"]
    tick()
    tick()  # throttled
    for _ in range(100):
        if (tmp_path / "plugin-data" / "antibeaurocracy" / "snapshot.json").exists() and not mod._snapshot_running:
            break
        time.sleep(0.02)
    snap = json.loads((tmp_path / "plugin-data" / "antibeaurocracy" / "snapshot.json").read_text())
    assert snap["summary"]["blocked"] == 6
    assert len([e for e in ctx.events if e[0] == "snapshot"]) == 1
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    tick()  # a different home is not throttled by the first
    for _ in range(100):
        if (other / "plugin-data" / "antibeaurocracy" / "snapshot.json").exists():
            break
        time.sleep(0.02)
    assert (other / "plugin-data" / "antibeaurocracy" / "snapshot.json").exists()


def test_slash_remote_is_count_only(tmp_path, monkeypatch):
    _board(tmp_path)
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    remote = ctx.commands["antibeaurocracy"]("audit", platform="discord")
    assert "t_d" not in remote and "blocked" in remote
    assert "t_d" not in ctx.commands["antibeaurocracy"]("audit", platform="tui")
    local = ctx.commands["antibeaurocracy"]("audit", platform="cli")
    assert "t_d" in local
    assert "F2-relay" in ctx.commands["fake-gate"](RELAY, platform="discord")


def test_tools(tmp_path, monkeypatch):
    _board(tmp_path)
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    v = json.loads(ctx.tools["bureaucracy_classify"]({"text": "Product must record the ruling", "age_hours": "3"}))
    assert v["cls"] == "FAKE"
    counts = json.loads(ctx.tools["bureaucracy_audit"]({}))
    assert counts["blocked"] == 6 and "t_d" not in json.dumps(counts)


def test_blueprint_is_counts_only(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    bp = ctx.blueprints["weekly-audit"]
    assert "counts only" in bp["prompt_template"].lower()
    deliver = next(s for s in bp["slots"] if s["name"] == "deliver")
    assert set(deliver["options"]) <= {"local", "origin"}


def test_extra_seats_from_config(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"extra_seats": "quartermaster"})
    v = json.loads(ctx.tools["bureaucracy_classify"]({"text": "Awaiting approval from quartermaster"}))
    assert v["subtype"] == "F1-ack"
    from antibeaurocracy_core import configure
    configure()


def test_needs_input_is_never_refused(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    args = {"task_id": "t", "reason": "Product must record the ruling", "kind": "needs_input"}
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args=args, session_id="s", tool_call_id="c") is None
    assert "F3" in ctx.hooks["transform_tool_result"](tool_name="kanban_block", args=args, result="ok", session_id="s", tool_call_id="c")


# ---------------------------------------------------------------- round-2 hardening

def test_hook_fails_open_on_any_error(tmp_path, monkeypatch):
    mod, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})

    def boom(*a, **k):
        raise PermissionError("read-only data dir")

    monkeypatch.setattr(mod, "_refusal_store", boom)
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY}, session_id="s") is None
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args="not a dict", session_id="s") is None


def test_refusal_store_survives_bad_entries(tmp_path):
    p = tmp_path / "refusals.json"
    p.write_text(json.dumps({"a": {"n": 1, "ts": None}, "b": {"n": "x", "ts": "nan"}, "c": 7, "d": {"n": 1, "ts": time.time()}}))
    rs = RefusalStore(p)
    assert rs.get("a") == 0 and rs.get("b") == 0 and rs.get("c") == 0 and rs.get("d") == 1
    state, n = rs.transition("a", lambda prior: decide("enforce", True, prior, 2))
    assert state is GateState.ASK and n == 1


def test_refusal_store_lock_times_out(tmp_path):
    import fcntl
    p = tmp_path / "refusals.json"
    rs = RefusalStore(p, lock_timeout_s=0.1)
    with open(p.with_suffix(".lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        out = subprocess.run([sys.executable, "-c", (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from antibeaurocracy_core.gates import RefusalStore, LockTimeout, decide;"
            "rs = RefusalStore(Path(sys.argv[2]), lock_timeout_s=0.1)\n"
            "try:\n rs.transition('k', lambda p: decide('enforce', True, p, 2)); print('no')\n"
            "except LockTimeout: print('timeout')"), str(ROOT), str(p)], capture_output=True, text=True, timeout=10)
    assert out.stdout.strip() == "timeout", out.stderr
    assert rs.lock_timeout_s == 0.1


@pytest.mark.parametrize("reason,asked", [
    ("Awaiting approval from Platform before I run the tests", True),     # F1: asked
    ("Platform must record the ruling on the export format", True),       # F3: asked
    ("HOLD: keep the old export until further notice", True),             # F5: asked
    ("Awaiting approval from Product before I run the tests", False),     # "Product" is in the wall net: nudge only
    ("Awaiting ACK from the CEO", False),                                 # HUMAN
    ("Awaiting ACK from Platform to run terraform apply", False),         # WALL
])
def test_ask_covers_every_evidenced_fake_outside_the_wall_net(tmp_path, monkeypatch, reason, asked):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    out = ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": reason}, session_id="s")
    assert bool(out) is asked, reason


def test_ask_covers_ceremony(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    r = ctx.hooks["pre_tool_call"](tool_name="kanban_block",
                                   args={"task_id": "t", "reason": "Contract says local-only, so cannot mark done"}, session_id="s")
    assert r and r["action"] == "block"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", float("nan"), float("inf"), "junk", -5, 10**9])
def test_numeric_settings_are_clamped(tmp_path, monkeypatch, bad):
    mod, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask", "max_refusals": bad, "refusal_ttl_hours": bad})
    assert 0 <= mod._count("max_refusals", 2) <= 1000
    ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY}, session_id="s")


@pytest.mark.parametrize("ttl", [0, -1, "0", -100.0])
def test_zero_or_negative_ttl_still_fails_open(tmp_path, monkeypatch, ttl):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask", "max_refusals": 2, "refusal_ttl_hours": ttl})
    call = lambda: ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY},
                                              session_id="s")
    assert call() and call()  # refused twice
    assert call() is None     # then the block goes through


def test_refusal_key_prefers_args_board(tmp_path, monkeypatch):
    mod, _ = _load_plugin(tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "envboard")
    assert mod._refusal_key({"task_id": "t", "board": "argboard"}, "s") == "argboard:t"
    assert mod._refusal_key({"task_id": "t"}, "s") == "envboard:t"


def test_snapshot_is_counts_only(tmp_path, monkeypatch):
    _board(tmp_path)
    mod, _ = _load_plugin(tmp_path, monkeypatch)
    snap = mod._snapshot(tmp_path)
    text = json.dumps(snap)
    assert "by_seat" not in text and "t_b" not in text and "eng" not in text and str(tmp_path) not in text


def test_lifecycle_echo_of_a_gated_block_is_not_double_ledgered(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch)
    ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t_5", "board": "demo", "reason": RELAY}, session_id="s")
    ctx.hooks["kanban_task_blocked"](task_id="t_5", board="demo", reason=RELAY)
    events = [r["event"] for r in _ledger(tmp_path) if r.get("task") == "t_5"]
    assert events == ["block_attempt"]
    ctx.hooks["kanban_task_blocked"](task_id="t_6", board="demo", reason=RELAY)  # a CLI block still counts
    assert [r["event"] for r in _ledger(tmp_path) if r.get("task") == "t_6"] == ["blocked_observed"]


@pytest.mark.parametrize("reason", [
    # Each of these once reached a refusal. Any wall-family word in the text means nudge, never refuse.
    "Reversible: no \nDeploy to prod pending; awaiting relay to create the PR",
    "kubectl delete failed for the prod namespace; need platform to run the command",
    "The CEO must countersign this before I continue",
    "The new instance is 3000 per month; awaiting relay to create the PR",
    "Await the release agent to open the PR from my patch. " + "x " * 2150 + "This step will drop table users in prod.",
    "estop engaged; awaiting relay to create the PR",
    "Awaiting relay to create the PR; the token rotation is pending",
])
def test_ask_never_questions_text_with_a_wall_family_word(tmp_path, monkeypatch, reason):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    assert ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": reason},
                                      session_id="s") is None


def test_tiny_ttl_is_raised_so_ask_still_fails_open(tmp_path, monkeypatch):
    mod, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask", "max_refusals": 2, "refusal_ttl_hours": 0.001})
    assert mod._refusal_store().ttl_s >= 3600
    call = lambda: ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t", "reason": RELAY},
                                              session_id="s")
    assert call() and call() and call() is None


def test_echo_dedupe_ignores_board_name_and_refused_calls(tmp_path, monkeypatch):
    _, ctx = _load_plugin(tmp_path, monkeypatch, {"fake_gate_mode": "ask"})
    # The tool call names no board but the lifecycle hook does: still the same block.
    ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t_7", "reason": "Tests pass; PR ready"},
                               session_id="s")
    ctx.hooks["kanban_task_blocked"](task_id="t_7", board="demo", reason="x")
    assert [r["event"] for r in _ledger(tmp_path) if r.get("task") == "t_7"] == ["block_attempt"]
    # A refused call never lands, so a later CLI block of the same card is a new event.
    ctx.hooks["pre_tool_call"](tool_name="kanban_block", args={"task_id": "t_8", "reason": RELAY}, session_id="s")
    ctx.hooks["kanban_task_blocked"](task_id="t_8", board="demo", reason=RELAY)
    assert "blocked_observed" in [r["event"] for r in _ledger(tmp_path) if r.get("task") == "t_8"]


def test_dashboard_ledger_counts_survive_junk_lines(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    d = tmp_path / "plugin-data" / "antibeaurocracy"
    d.mkdir(parents=True)
    import time as _t
    now = _t.time()
    (d / "ledger.jsonl").write_bytes(
        b'[1,2]\n"x"\nnull\n{"ts": "bad"}\n\xff\xfe junk\n'
        + (b'{"ts": %f, "event": ["a"]}\n' % now) + (b'{"ts": %f, "event": "refused"}\n' % now))
    spec = importlib.util.spec_from_file_location("ab_dash2", ROOT / "dashboard" / "fake_gates_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._ledger_counts(7) == {"refused": 1, "['a']": 1}


def test_dashboard_overview_has_no_people_or_paths(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    _board(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ab_dash", ROOT / "dashboard" / "fake_gates_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = json.dumps(mod.overview(top=15, days=7), default=str)
    assert "assignee" not in text and "by_seat" not in text and '"eng"' not in text and str(tmp_path) not in text


# ---------------------------------------------------------------- docs stay tied to the code

@pytest.mark.parametrize("skill", ["antibeaurocracy", "antipedantry"])
def test_files_the_skill_references_are_tracked(skill):
    import re
    try:
        tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                                     check=True).stdout.split())
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout (e.g. an sdist)")
    if not tracked:
        pytest.skip("not a git checkout (e.g. an sdist)")
    skill_dir = Path("skills") / skill
    text = (ROOT / skill_dir / "SKILL.md").read_text()
    for ref in set(re.findall(r"\((references/[\w./-]+)\)|`(references/[\w./-]+)`", text)):
        path = (skill_dir / (ref[0] or ref[1])).as_posix()
        assert path in tracked, f"{path} is referenced by SKILL.md but not tracked"


def test_docs_match_code():
    import antibeaurocracy_core  # noqa: F401
    C = sys.modules["antibeaurocracy_core.classify"]
    skill = (ROOT / "skills/antibeaurocracy/SKILL.md").read_text()
    tax = (ROOT / "skills/antibeaurocracy/references/taxonomy.md").read_text()
    readme = (ROOT / "README.md").read_text()
    head = skill.split("---")[1]
    assert "HUMAN" in head  # the description names all the legitimate classes
    for phrase in ("Want me to", "OK to proceed", "awaiting go-ahead"):
        row = [l for l in skill.splitlines() if l.startswith("| F1")]
        looks_like = row[0].split("|")[2]
        assert phrase not in looks_like, f"{phrase!r} is HUMAN in code, not an F1 example"
        assert C.classify(phrase + " run the tests?").subtype != "F1-ack"
    assert "Walls, questions for a person, dependencies" not in readme
    # The taxonomy lists the rules in the same order as the code.
    import re
    code_order = [line.split(" ", 2)[1].rstrip(":") for line in C.RULES]
    doc_order = re.findall(r"^\d+\. \*\*(\w+)", tax, re.M)
    assert [c.split()[0] for c in code_order] == doc_order[:len(code_order)], (code_order, doc_order)
    # The SKILL.md mental check runs the classes in the order the code first reaches them.
    first_seen = list(dict.fromkeys(c for c in code_order if c in ("WALL", "HUMAN", "DEPENDENCY", "MACHINERY")))
    steps = re.findall(r"^\d+\. .*?Then it is (?:a |an )?\*?\*?(WALL|HUMAN|MACHINERY|DEPENDENCY)", skill, re.M)
    assert steps == first_seen, (steps, first_seen)
    assert "0.3" in tax and "F6" in tax


# ---------------------------------------------------------------- optional --judge second opinion

def test_judge_parses_one_class_word():
    from antibeaurocracy_core import judge
    assert judge.parse("I think this is a WALL.") == "WALL"
    assert judge.parse("fake") == "FAKE"
    assert judge.parse("no idea") == ""


def test_judge_lists_disagreements_only(tmp_path):
    from antibeaurocracy_core import judge
    _board(tmp_path)
    boards = [audit.audit_board(db) for db in audit.find_boards([tmp_path])]
    seen = []
    op = judge.second_opinion(boards, lambda p: (seen.append(p), "WALL")[1])
    # Only FAKE verdicts with a reason are sent: the F3 card and the vague one, not walls, crashes or created-blocked.
    assert op["asked"] == 2 and len(seen) == 2 and all("Block reason" in p for p in seen)
    assert {d["id"] for d in op["disagree"]} == {"t_d", "t_g"}
    assert "t_b" not in "".join(seen)
    assert judge.second_opinion(boards, lambda p: "")["no_answer"] == 2


def test_judge_cli_runs_a_command_without_a_shell(tmp_path):
    _board(tmp_path)
    script = tmp_path / "judge.py"
    script.write_text("import sys; sys.stdin.read(); print('DEPENDENCY')\n")
    out = subprocess.run([sys.executable, "-m", "antibeaurocracy_core.cli", "audit", "--root", str(tmp_path), "--no-rules",
                          "--judge", f"{sys.executable} {script}"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "Second opinion" in out.stdout and "judge **DEPENDENCY**" in out.stdout


def test_judge_refuses_counts_mode(tmp_path):
    _board(tmp_path)
    out = subprocess.run([sys.executable, "-m", "antibeaurocracy_core.cli", "audit", "--root", str(tmp_path), "--counts",
                          "--judge", "cat"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 2 and "--counts" in out.stderr


def test_judge_failures_are_no_answer(tmp_path):
    from antibeaurocracy_core import judge
    assert judge.runner("/nonexistent/judge-bin")("x") == ""
    assert judge.runner(f"{sys.executable} -c 'import sys; sys.exit(3)'")("x") == ""
    with pytest.raises(ValueError):
        judge.runner("   ")
