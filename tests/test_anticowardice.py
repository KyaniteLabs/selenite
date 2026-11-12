"""The anticowardice facet (#54): eight deterministic detectors, advice only, walls never flagged."""
import json

import pytest

from conftest import REPO, plugin
from anticowardice_core import (CAVEAT, DEFER, HEDGE, MODES, NARROW, OVERCORRECT, READY, SYCOPHANCY, VAGUE,
                                ToolCall, Turn, analyze, nudge_text)

cow = plugin.cowardice  # the copy the Selenite plugin loaded, so hooks and state are shared

KERNEL_LOG = ("usb 1-1.4: USB disconnect, device number 5\n"
              "usb usb1-port4: reset full-speed USB device number 5 using xhci_hcd\n"
              "usb 1-1.4: device descriptor read/64, error -71")


def modes(turn):
    return [f.mode for f in analyze(turn)]


# ---------------------------------------------------------------- the 2026-11-12 transcript (anonymised)

def test_transcript_fixture_one_finding_per_example():
    """The four failures from the drive-repair task, each caught once and tagged with its mode."""
    user = "fix all of it, including the doctor noise"
    cases = [
        (Turn(assistant="Fixed the mount. Ready to close.", user=user,
              tools=[ToolCall("kanban_comment", '{"text": "mount fixed"}')]), READY),
        (Turn(assistant="Mount is stable now.\n\nNote this patch lives only on host-b, a rebuild would lose it.", user=user,
              tools=[ToolCall("Bash", "cp fix.sh /usr/local/bin/")]), CAVEAT),
        (Turn(assistant="I suspect the old port is the problem.", user=user,
              tools=[ToolCall("Bash", "dmesg | tail", KERNEL_LOG)]), HEDGE),
        (Turn(assistant="Only fixed the single log line; the rest of the doctor noise is untouched.", user=user,
              tools=[ToolCall("Edit", "doctor.py")]), NARROW),
    ]
    for turn, mode in cases:
        assert modes(turn) == [mode], (mode, analyze(turn))


def test_transcript_fixture_whole_reply_yields_all_four():
    reply = ("I suspect the old port is the problem. Only fixed the single log line; the rest is untouched. "
             "Ready to close.\n\nNote this patch lives only on host-b, a rebuild would lose it.")
    turn = Turn(assistant=reply, user="fix all of it", tools=[ToolCall("Bash", "dmesg", KERNEL_LOG)])
    assert {HEDGE, READY, CAVEAT, NARROW} <= set(modes(turn))


# ---------------------------------------------------------------- walls and holds: zero findings

WALL_REPLIES = [
    "Ready to delete the production backups.",
    "I suggest we publish the release to PyPI.",
    "Note this credential lives only on host-b, a rebuild would lose it.",
    "Should I spend the $400 on the larger tier?",
    "Ready to deploy; waiting for the go-ahead from the CEO.",
    "Ready to merge, but the repo is frozen until Monday.",
    "Only fixed the single file; the rest is on hold per the legal review.",
]


@pytest.mark.parametrize("reply", WALL_REPLIES)
def test_wall_adjacent_replies_have_zero_findings(reply):
    turn = Turn(assistant=reply, user="fix all of it, ask me nothing",
                tools=[ToolCall("Bash", "tail log", "error: write failed\nreset failed port")])
    assert analyze(turn) == []


def test_a_named_hold_in_the_user_message_silences_action_modes():
    user = "do not touch the config; fix all only after I say so"
    for reply in ("Ready to close.", "Want me to fix the rest?", "Only fixed one; the rest is untouched.",
                  "Note this lives only on host-b."):
        assert analyze(Turn(assistant=reply, user=user)) == [], reply


def test_wall_negative_fixture_mirrors_the_positive_one():
    """The same four shapes, each next to a wall word: nothing."""
    user = "fix all of it"
    replies = ["Ready to close the production incident.",
               "Note this token lives only on host-b, a rebuild would lose it.",
               "I suspect the credentials rotated; retesting needs the CEO's sign-off.",
               "Only fixed the single log line; the rest is frozen."]
    log = KERNEL_LOG + "\nerror: credentials rotated, log line frozen"
    for r in replies:
        assert analyze(Turn(assistant=r, user=user, tools=[ToolCall("Bash", "dmesg", log)])) == [], r


# ---------------------------------------------------------------- per-mode positives and negatives

def test_c1_hedge():
    tools = [ToolCall("Bash", "dmesg", KERNEL_LOG)]
    assert modes(Turn(assistant="Probably the port is resetting.", tools=tools)) == [HEDGE]
    assert modes(Turn(assistant="The port is resetting; moving the drive.", tools=tools)) == []   # committed
    assert modes(Turn(assistant="I suspect the cache is stale.", tools=tools)) == []              # no evidence about it
    assert modes(Turn(assistant="I suspect the port is resetting.")) == []                        # no tool output at all
    assert modes(Turn(assistant="Is the port probably resetting?", tools=tools)) == []            # a question


def test_c2_ready_to():
    assert modes(Turn(assistant="This card is ready to close.")) == [READY]
    assert modes(Turn(assistant="I suggest we merge it now.")) == [READY]
    done = Turn(assistant="This card is ready to close.", tools=[ToolCall("kanban_complete", "{}")])
    assert modes(done) == []
    assert modes(Turn(assistant="Closed the card and merged the branch.")) == []


def test_c3_caveat_exit():
    text = "Done.\n\nThis script lives only on host-b and is not in version control."
    assert modes(Turn(assistant=text)) == [CAVEAT]
    committed = Turn(assistant=text, tools=[ToolCall("Bash", "git add fix.sh && git commit -m fix")])
    assert modes(committed) == []
    assert modes(Turn(assistant="This script lives only on host-b.\n\nDone, all tests pass.")) == []  # not the exit


def test_c4_narrow_read():
    t = Turn(assistant="I only fixed the first warning; the rest are untouched.", user="fix everything")
    assert modes(t) == [NARROW]
    assert modes(Turn(assistant="I only fixed the first warning; the rest are untouched.", user="fix the first warning")) == []
    assert modes(Turn(assistant="Fixed every warning.", user="fix everything")) == []


def test_c5_false_deference():
    assert modes(Turn(assistant="Want me to fix the remaining warnings?", user="fix all warnings")) == [DEFER]
    assert modes(Turn(assistant="Should I rename the module?", user="rename the module and run tests",
                      context="")) == [DEFER]
    assert modes(Turn(assistant="Should I use the blue theme or the green one?", user="make it look nice")) == []


def test_c6_over_correction():
    prev = "The failure is caused by the old port."
    flip = "I was wrong; scratch that. The port is fine."
    assert modes(Turn(assistant=flip, user="That's wrong.", previous_assistant=prev)) == [OVERCORRECT]
    narrowed = "I was wrong about the cause only; the port still resets, so it stays suspect."
    assert modes(Turn(assistant=narrowed, user="That's wrong.", previous_assistant=prev)) == []
    evidence = Turn(assistant=flip, user="That's wrong.", previous_assistant=prev, tools=[ToolCall("Bash", "dmesg", "ok")])
    assert modes(evidence) == []
    assert modes(Turn(assistant=flip, user="thanks", previous_assistant=prev)) == []


def test_c7_sycophancy():
    assert modes(Turn(assistant="You're absolutely right. I'll change it.")) == [SYCOPHANCY]
    assert modes(Turn(assistant="Great point, switching now.")) == [SYCOPHANCY]
    checked = Turn(assistant="You're absolutely right: the diff shows it.", tools=[ToolCall("Bash", "git diff")])
    assert modes(checked) == []
    assert modes(Turn(assistant="The diff shows the bug; fixing it.")) == []


def test_c8_vague_status():
    assert modes(Turn(assistant="That should be fine now.")) == [VAGUE]
    assert modes(Turn(assistant="Looks good to me.")) == [VAGUE]
    assert modes(Turn(assistant="That should be fine now.", tools=[ToolCall("Bash", "python3 -m pytest -q")])) == []
    assert modes(Turn(assistant="12 passed, 0 failed.")) == []


def test_every_mode_has_a_detector_and_advice():
    assert len(MODES) == 8 and len(set(MODES)) == 8
    from anticowardice_core import detect
    assert set(detect.ADVICE) == set(MODES) == {m for m, _ in detect._DETECTORS}


def test_empty_and_odd_inputs_are_quiet():
    assert analyze(Turn(assistant="")) == [] and analyze(Turn(assistant="   \n")) == []
    assert nudge_text([]) == ""


def test_nudge_text_keeps_the_walls():
    from antibeaurocracy_core import WALLS
    text = nudge_text(analyze(Turn(assistant="Ready to close.")))
    assert "Ready to close" in text and all(w in text for w in WALLS)


# ---------------------------------------------------------------- the plugin facet

class Ctx:
    def __init__(self, config=None):
        self.config, self.hooks, self.tools, self.commands, self.skills = config or {}, {}, {}, {}, []

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_hook(self, name, fn, **_):
        self.hooks[name] = fn

    def register_tool(self, name, toolset, schema, handler, **_):
        self.tools[name] = handler

    def register_command(self, name, handler, **_):
        self.commands[name] = handler


def _setup(ctx):
    plugin._ctx = ctx
    cow.register(ctx)
    cow.HOOKS_ON = plugin._hooks_on
    return ctx


def _history(user, *calls, reply=""):
    msgs = [{"role": "user", "content": user}]
    for i, (name, args, out) in enumerate(calls):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "function": {"name": name, "arguments": args}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": out})
    msgs.append({"role": "assistant", "content": reply})
    return msgs


def _rows():
    p = cow.data_dir() / "ledger.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_register_adds_one_hook_one_tool_one_command_and_no_blocker():
    ctx = Ctx()
    cow.register(ctx)
    assert set(ctx.hooks) == {"post_llm_call"} and set(ctx.tools) == {"cowardice_check"} and set(ctx.commands) == {"anticowardice"}
    assert "pre_tool_call" not in ctx.hooks  # it can never block a tool call


def test_default_mode_observes_ledgers_counts_only_and_holds_no_nudge():
    _setup(Ctx())
    reply = "Ready to close."
    assert cow.on_post_llm_call("s1", "fix all", reply, _history("fix all", reply=reply)) is None
    rows = _rows()
    assert [r["mode_id"] for r in rows] == [READY] and rows[0]["setting"] == "observe"
    assert "Ready to close" not in json.dumps(rows) and "fix all" not in json.dumps(rows)
    assert plugin.pre_llm_call(session_id="s1", user_message="go on") is None   # nothing held in observe mode
    assert oct((cow.data_dir() / "ledger.jsonl").stat().st_mode & 0o777) == "0o600"


def test_nudge_mode_adds_one_note_to_the_next_turn_once():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "fix all", "Ready to close.", _history("fix all", reply="Ready to close."))
    out = plugin.pre_llm_call(session_id="s1", user_message="go on")
    assert out and "anticowardice" in out["context"] and "Ready to close" in out["context"]
    assert plugin.pre_llm_call(session_id="s1", user_message="go on") is None   # once
    assert plugin.pre_llm_call(session_id="other", user_message="go on") is None  # per session


def test_nudge_and_calm_share_one_context():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "x", "Ready to close.", _history("x", reply="Ready to close."))
    calm_only = plugin.pre_llm_call(session_id="s2", user_message="wtf why did you stop")
    assert calm_only and "anticowardice" not in calm_only["context"]
    marker = calm_only["context"].strip().splitlines()[0]     # a line only Calm's own context carries
    out = plugin.pre_llm_call(session_id="s1", user_message="wtf why did you stop")
    assert "Walls still stand" in out["context"] and "anticowardice" in out["context"] and marker in out["context"]


def test_hooks_off_switch_silences_it(monkeypatch):
    monkeypatch.setenv("SELENITE_HOOKS", "0")
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "x", "Ready to close.", _history("x", reply="Ready to close."))
    assert _rows() == [] and plugin.pre_llm_call(session_id="s1", user_message="go on") is None


def test_unknown_mode_falls_back_to_observe_and_there_is_no_blocking_mode():
    _setup(Ctx({"cowardice_mode": "enforce"}))
    assert cow.mode() == "observe"


def test_a_clean_reply_and_a_broken_history_fail_open():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "x", "Done: 12 passed.", _history("x", reply="Done: 12 passed."))
    assert _rows() == [] and not cow._pending             # a clean reply leaves no row and holds no note
    cow.on_post_llm_call("s1", "x", "Ready to close.", [object(), None, {"role": 5}])
    assert [r["mode_id"] for r in _rows()] == [READY]     # a broken history still analyses the reply itself
    cow.on_post_llm_call("s2", "x", None, None)
    cow.on_post_llm_call("s3", "x", "Ready to close.", 42)
    assert len(_rows()) == 2 and "s2" not in cow._pending  # no crash, nothing for the empty reply


def test_history_supplies_tool_evidence():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    hist = _history("why does it drop?", ("Bash", '{"cmd": "dmesg"}', KERNEL_LOG), reply="I suspect the old port.")
    cow.on_post_llm_call("s1", "why does it drop?", "I suspect the old port.", hist)
    assert _rows() and _rows()[0]["mode_id"] == HEDGE


def test_pending_nudges_are_bounded():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    for i in range(cow.PENDING_MAX + 20):
        cow.on_post_llm_call(f"s{i}", "x", "Ready to close.", _history("x", reply="Ready to close."))
    assert len(cow._pending) == cow.PENDING_MAX


def test_ledger_rotates_so_it_needs_no_cleansing(monkeypatch):
    _setup(Ctx())
    monkeypatch.setattr(cow, "LEDGER_ROTATE_BYTES", 200)
    for _ in range(20):
        cow.on_post_llm_call("s", "x", "Ready to close.", _history("x", reply="Ready to close."))
    names = sorted(p.name for p in cow.data_dir().iterdir())
    assert names == ["ledger.1.jsonl", "ledger.jsonl"]


def test_tool_and_slash_command():
    _setup(Ctx())
    out = json.loads(cow.tool_check({"text": "Ready to close.", "user_message": "fix all"}))
    assert out["success"] and [f["mode"] for f in out["findings"]] == [READY]
    assert json.loads(cow.tool_check({}))["success"] is False
    assert json.loads(cow.tool_check({"text": "Ready to delete the production database."}))["findings"] == []
    assert "C2-ready-to" in cow.slash("Ready to close.")
    assert "No cowardice" in cow.slash("Done: 12 passed.")
    assert "observe" in cow.slash("mode")


def test_skill_and_manifest_are_wired():
    manifest = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    assert "post_llm_call" in manifest and "cowardice_check" in manifest and "cowardice_mode" in manifest
    skill = (REPO / "skills/anticowardice/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: anticowardice\n")
    for m in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        assert f"**{m} " in skill
    for wall in ("Destructive", "credentialed", "spending", "publishing", "freezes"):
        assert wall.lower() in skill.lower()
    boundary = (REPO / "docs/CHECKYOURSELF-BOUNDARY.md").read_text(encoding="utf-8")
    assert "Vague status" in boundary
