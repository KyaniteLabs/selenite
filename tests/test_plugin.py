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


def _kinds():
    return [(r["kind"], r["key"]) for r in ledger.rows()]


def test_register_matches_manifest():
    ctx = Ctx()
    plugin.register(ctx)
    manifest = (REPO / "plugin.yaml").read_text()
    assert ctx.skills[0][0] == "frictionless" and ctx.skills[0][1].exists()
    assert ctx.commands == ["frictionless"] and ctx.tools[0][0] == "selenite_ledger"
    for hook in ctx.hooks:
        assert f"  - {hook}\n" in manifest
    assert "manifest_version: 2" in manifest and "enabled:" not in manifest


def test_versions_agree():
    import re
    v_manifest = re.search(r'^version: "([\d.]+)"', (REPO / "plugin.yaml").read_text(), re.M).group(1)
    v_skill = re.search(r"^  version: ([\d.]+)", (REPO / "skills/frictionless/SKILL.md").read_text(), re.M).group(1)
    v_py = re.search(r'^version = "([\d.]+)"', (REPO / "pyproject.toml").read_text(), re.M).group(1)
    assert v_manifest == v_skill == v_py


def test_one_signal_is_not_calm():
    assert plugin.pre_llm_call(session_id="s", user_message="damn it, again") is None
    assert plugin.pre_llm_call(session_id="s", user_message="all good, thanks") is None
    assert not any(k == "calm" for k, _ in _kinds())


def test_two_signals_bring_calm_with_the_wall_caveat():
    out = plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop")
    assert out and "Authority walls still stand" in out["context"]
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
    plugin.pre_approval_request(pattern_key="k", surface="cli")
    assert _kinds() == []


def test_approvals_count_only_prompts_a_human_saw():
    plugin.pre_approval_request(pattern_key="rm", surface="cli")
    plugin.pre_approval_request(pattern_key="rm", surface="smart")
    plugin.pre_approval_request(pattern_key="rm", surface="gateway", coalesced=True)
    plugin.post_approval_response(pattern_key="rm", choice="once")
    assert _kinds() == [("approval", "rm")]


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
    assert "ABC123" not in ledger.LEDGER.read_text()


def test_kanban_completed_clears_only_known_blocks():
    plugin.kanban_task_completed(task_id="t_unknown")
    assert _kinds() == []
    plugin.kanban_task_blocked(task_id="t_1", reason="manual approval needed")
    plugin.kanban_task_completed(task_id="t_1")
    assert "kanban:t_1" in ledger.fixed_keys()


def test_command_modes_and_alias():
    assert "Run Cleanse mode" in plugin.frictionless_command("cleanse skills")
    assert "Run Cleanse mode" in plugin.frictionless_command("audit")
    assert "Focus: skills" in plugin.frictionless_command("cleanse skills")
    assert "Pick the mode" in plugin.frictionless_command("why is this slow")
    assert "Context: why is this slow" in plugin.frictionless_command("why is this slow")


def test_tool_actions():
    out = json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "k"}))
    assert out["success"]
    for _ in range(3):
        plugin.selenite_ledger({"action": "add", "kind": "approval", "key": "deploy"})
    out = json.loads(plugin.selenite_ledger({"action": "cleanse"}))
    assert out["success"] and out["findings"][0]["where"] == "deploy"
    assert not json.loads(plugin.selenite_ledger({"action": "add", "kind": "bad", "key": "k"}))["success"]


def test_a_failing_hook_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ledger, "add", boom)
    assert plugin.pre_llm_call(session_id="s", user_message="wtf why did you stop") is None
