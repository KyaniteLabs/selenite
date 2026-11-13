import pytest
import json

from conftest import REPO, ledger, plugin


class Ctx:
    def __init__(self, config=None):
        self.config = config or {}
        self.skills, self.commands, self.tools, self.hooks = [], [], [], {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_skill(self, name, path, description=""):
        self.skills.append((name, path))

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands.append(name)

    def register_tool(self, name, toolset, schema, handler, description="", emoji=""):
        self.tools.append((name, emoji))

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_cli_command(self, name, **_kw):
        self.cli = name

    def register_system_prompt_section(self, *a, **kw):
        pass

    def emit(self, *a, **kw):
        pass


def _kinds():
    return [(r["kind"], r["key"]) for r in ledger.rows()]


def test_register_matches_manifest():
    ctx = Ctx()
    plugin.register(ctx)
    manifest = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    assert [n for n, _ in ctx.skills] == ["frictionless", "antibeaurocracy", "antipedantry", "anticowardice"]
    assert all(path.exists() for _, path in ctx.skills)
    assert ctx.commands == ["frictionless", "antibeaurocracy", "fake-gate", "anticowardice"]
    assert [t for t, _ in ctx.tools] == ["selenite_ledger", "selenite_show", "bureaucracy_classify", "bureaucracy_audit",
                                         "cowardice_check"]
    assert all(f"  - {hook}\n" in manifest for hook in ctx.hooks)
    assert manifest.count("\n  - ") - manifest.split("optional_env:")[1].count("\n  - ") == len(ctx.hooks)
    for tool, _ in ctx.tools:
        assert tool in manifest.split("provides_tools:")[1].split("\n")[0]
    assert "manifest_version: 2" in manifest and "enabled:" not in manifest


def test_versions_agree():
    import re
    v_manifest = re.search(r'^version: "([\d.]+)"', (REPO / "plugin.yaml").read_text(encoding="utf-8"), re.M).group(1)
    v_skill = re.search(r"^  version: ([\d.]+)", (REPO / "skills/frictionless/SKILL.md").read_text(encoding="utf-8"), re.M).group(1)
    v_py = re.search(r'^version = "([\d.]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    v_skills = {re.search(r"^  version: ([\d.]+)", (REPO / f"skills/{n}/SKILL.md").read_text(encoding="utf-8"), re.M).group(1)
                for n in plugin.SKILLS}
    v_core = re.search(r'^__version__ = "([\d.]+)"', (REPO / "antibeaurocracy_core/__init__.py").read_text(encoding="utf-8"), re.M).group(1)
    v_dash = json.loads((REPO / "dashboard/manifest.json").read_text(encoding="utf-8"))["version"]
    v_cow = re.search(r'^__version__ = "([\d.]+)"', (REPO / "anticowardice_core/__init__.py").read_text(encoding="utf-8"), re.M).group(1)
    assert {v_manifest, v_skill, v_py, v_core, v_cow, v_dash} | v_skills == {v_manifest}


def test_one_signal_is_not_calm():
    assert plugin.pre_llm_call(session_id="s", user_message="damn it, again") is None
    assert plugin.pre_llm_call(session_id="s", user_message="all good, thanks") is None
    assert not any(k == "calm" for k, _ in _kinds())


def test_two_signals_bring_calm_with_the_wall_caveat():
    out = plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop")
    assert out and "Walls still stand" in out["context"]
    from antibeaurocracy_core import WALLS
    assert all(w in out["context"] for w in WALLS)
    assert ("calm", "curse+stopping_short") in _kinds()


def test_streak_across_messages_and_reset():
    assert plugin.pre_llm_call(session_id="s", user_message="just do it") is None
    assert plugin.pre_llm_call(session_id="s", user_message="just do it") is not None
    assert plugin.pre_llm_call(session_id="s", user_message="ok") is None
    assert plugin.pre_llm_call(session_id="s", user_message="just do it") is None


def test_subagents_and_other_senders_ignored():
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop", parent_session_id="p") is None
    plugin._ctx = Ctx({"calm_senders": "me, also-me"})
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop", sender_id="guest") is None
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop", sender_id="me") is not None


def test_streak_memory_is_bounded():
    for i in range(plugin.STREAK_MAX + 50):
        plugin.pre_llm_call(session_id=f"s{i}", user_message="hello")
    assert len(plugin._streak) == plugin.STREAK_MAX


def test_hooks_can_be_turned_off(monkeypatch):
    plugin._ctx = Ctx({"hooks": False})
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop") is None
    plugin._ctx = None
    monkeypatch.setenv("SELENITE_HOOKS", "0")
    plugin.post_approval_response(pattern_key="k", surface="cli", choice="once", decided_by="user")
    assert _kinds() == []


def test_calm_never_fires_inside_a_kanban_worker(monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_1")
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop") is None


@pytest.mark.parametrize("key,surface,choice,decided_by,row", [
    ("pip install from a lockfile", "cli", "once", "user", True),
    ("pip install from a lockfile", "gateway", "session", "user", True),
    ("pip install from a lockfile", "cli", "deny", "user", False),          # denied: never a candidate
    ("pip install from a lockfile", "cli", "timeout", None, False),         # never seen
    ("pip install from a lockfile", "cli", "cancelled", None, False),
    ("pip install from a lockfile", "cli", "notify_failed", None, False),
    ("pip install from a lockfile", "smart", "once", "aux_llm", False),     # the smart approver, not a person
    ("pay the invoice", "vault-payment", "accept", "user", False),
    ("pay the invoice", "vault-payment", "once", "user", False),
    ("trust server", "mcp-trust/docs", "once", "user", False),
    ("ask for input", "mcp-elicitation/docs", "session", "user", False),
    ("SQL DROP", "cli", "once", "user", False),                             # Hermes's own wall keys
    ("recursive delete", "cli", "once", "user", False),
    ("format filesystem", "cli", "session", "user", False),
    ("kill all processes", "cli", "once", "user", False),
    ("git push --force", "cli", "once", "user", False),
])
def test_only_a_persons_safe_approval_is_an_allowlist_candidate(key, surface, choice, decided_by, row):
    plugin.post_approval_response(pattern_key=key, surface=surface, choice=choice, decided_by=decided_by)
    assert _kinds() == ([("approval", key)] if row else [])


def test_an_approval_after_always_reopens_it():
    plugin.post_approval_response(pattern_key="pip install", choice="always", decided_by="user")
    assert "approval:pip install" in ledger.fixed_keys()
    plugin.post_approval_response(pattern_key="pip install", choice="once", decided_by="user", surface="cli")
    assert "approval:pip install" not in ledger.fixed_keys()


def test_long_approval_keys_truncate_to_one_length():
    long = "x" * 200
    plugin.post_approval_response(pattern_key=long, choice="once", decided_by="user", surface="cli")
    plugin.post_approval_response(pattern_key=long, choice="always", decided_by="user")
    keys = [k for _, k in _kinds()]
    assert keys == ["x" * ledger.APPROVAL_KEY, "approval:" + "x" * ledger.APPROVAL_KEY] and len(keys[1]) == 80


def test_human_always_is_a_fix_but_the_smart_approver_is_not():
    plugin.post_approval_response(pattern_key="rm", choice="smart_approve", decided_by="aux_llm")
    plugin.post_approval_response(pattern_key="rm", choice="always", decided_by="aux_llm")
    assert _kinds() == []
    plugin.post_approval_response(pattern_key="rm", choice="always", decided_by="human")
    assert _kinds() == [("fix", "approval:rm")]


def test_kanban_blocked_keeps_no_reason_text():
    plugin.kanban_task_blocked(task_id="t_1", reason="needs the owner to log in with token ABC123", assignee="w")
    plugin.kanban_task_blocked(task_id="t_2", reason="humanize copy step is slow")
    plugin.kanban_task_blocked(task_id="t_3", reason="waiting on t_9 to merge")
    rows = list(ledger.rows())
    assert [(r["kind"], r["key"]) for r in rows] == [("blocked", "kanban:t_1")]
    assert "ABC123" not in ledger.LEDGER.read_text(encoding="utf-8")


def test_kanban_completed_clears_only_known_blocks():
    plugin.kanban_task_completed(task_id="t_unknown")
    assert _kinds() == []
    plugin.kanban_task_blocked(task_id="t_1", reason="manual approval needed")
    plugin.kanban_task_completed(task_id="t_1")
    assert "kanban:t_1" in ledger.fixed_keys()


def test_command_modes_and_alias():
    prompt = lambda raw: plugin.frictionless_prompt(raw)[1]
    assert plugin.frictionless_prompt("audit")[0] == "cleanse"
    assert "Run Cleanse mode" in prompt("cleanse skills")
    assert "Run Cleanse mode" in prompt("audit")
    assert "Focus: skills" in prompt("cleanse skills")
    assert "Pick the mode" in prompt("why is this slow")
    assert "Context: why is this slow" in prompt("why is this slow")


class _InjectCtx:
    def __init__(self, accept):
        self.accept, self.sent = accept, []

    def inject_message(self, content, role="user", *, session_key=None, origin=None):
        self.sent.append((content, session_key))
        return self.accept


def test_command_starts_an_agent_turn_and_tells_the_human(monkeypatch):
    ctx = _InjectCtx(True)
    monkeypatch.setattr(plugin, "_ctx", ctx)
    out = plugin.frictionless_command("cleanse skills", session_key="k1")
    (sent, key), = ctx.sent
    assert key == "k1" and "Run Cleanse mode" in sent   # the agent gets the instructions
    assert "Load and follow" not in out and "Cleanse mode" in out   # the human gets a status line


def test_command_uses_the_gateway_session_key_fallback(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_KEY", "gateway-session")
    ctx = _InjectCtx(True)
    monkeypatch.setattr(plugin, "_ctx", ctx)
    out = plugin.frictionless_command("calm")
    assert ctx.sent[0][1] == "gateway-session"
    assert out.startswith("Selenite: handed")


def test_command_uses_real_hermes_session_accessor_when_available(monkeypatch):
    try:
        from gateway.session_context import get_session_env
    except ImportError:
        pytest.skip("Hermes gateway session context is not present in this source snapshot")
    from gateway.session_context import scoped_session_key
    assert plugin.get_session_env is get_session_env
    monkeypatch.setenv("HERMES_SESSION_KEY", "stale-process-env")
    ctx = _InjectCtx(True)
    monkeypatch.setattr(plugin, "_ctx", ctx)
    with scoped_session_key("task-local-session"):  # the gateway binds the key per task
        out = plugin.frictionless_command("calm")
    assert ctx.sent[0][1] == "task-local-session"
    assert out.startswith("Selenite: handed")


def test_ledger_follows_the_active_hermes_profile(monkeypatch, tmp_path):
    try:
        import hermes_constants
    except ImportError:
        pytest.skip("Hermes profile context is not present in this source snapshot")

    monkeypatch.delenv("SELENITE_STATE", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    profile_a, profile_b = tmp_path / "profiles" / "a", tmp_path / "profiles" / "b"

    token = hermes_constants.set_hermes_home_override(profile_a)
    try:
        assert hermes_constants.get_hermes_home() == profile_a
        fallback_a = ledger.state_dirs()[-1]
        ledger.add("gate", "profile-scoped-gate")
        assert (profile_a / "plugin-data/selenite/ledger.jsonl").exists()
    finally:
        hermes_constants.reset_hermes_home_override(token)

    token = hermes_constants.set_hermes_home_override(profile_b)
    try:
        assert hermes_constants.get_hermes_home() == profile_b
        fallback_b = ledger.state_dirs()[-1]
        assert fallback_b != fallback_a
        assert not list(ledger.rows())
        ledger.add("fix", "profile-scoped-gate")
        assert (profile_b / "plugin-data/selenite/ledger.jsonl").exists()
    finally:
        hermes_constants.reset_hermes_home_override(token)

    token = hermes_constants.set_hermes_home_override(profile_a)
    try:
        assert "profile-scoped-gate" not in ledger.fixed_keys()
    finally:
        hermes_constants.reset_hermes_home_override(token)


def test_command_falls_back_to_text_to_send_when_no_turn_can_start(monkeypatch):
    for ctx in (_InjectCtx(False), object(), None):
        monkeypatch.setattr(plugin, "_ctx", ctx)
        out = plugin.frictionless_command("calm")
        assert out.startswith("Selenite could not start an agent turn") and "Run Calm mode" in out


def test_ledger_tool_does_not_claim_an_unwritten_row(monkeypatch):
    monkeypatch.setattr(ledger, "state_dirs", lambda: [])
    out = json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "k"}))
    assert out["success"] is False and out["row"] is None and "not recorded" in out["error"]


def test_tool_actions():
    out = json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "k"}))
    assert out["success"]
    for _ in range(3):
        plugin.selenite_ledger({"action": "add", "kind": "approval", "key": "deploy"})
    out = json.loads(plugin.selenite_ledger({"action": "cleanse"}))
    assert out["success"] and out["findings"][0]["where"] == "deploy"
    assert not json.loads(plugin.selenite_ledger({"action": "add", "kind": "bad", "key": "k"}))["success"]


def test_ledger_tool_names_its_errors():
    def call(**a):
        return json.loads(plugin.selenite_ledger(a))
    assert call(action="add", key="k") == {"success": False, "error": "kind is required"}
    assert call(action="add", kind="gate") == {"success": False, "error": "key is required"}
    assert call(action="add", kind="gate", key="  ") == {"success": False, "error": "key is required"}
    assert call(action="add", kind="bad", key="k")["success"] is False
    assert call(action="nope") == {"success": False, "error": "unknown action: nope"}
    assert call() == {"success": False, "error": "action is required"}
    assert call(action="summary")["success"] is True
    assert plugin.LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"] == ["add", "summary", "cleanse"]


def test_a_failing_hook_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ledger, "add", boom)
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop") is None
