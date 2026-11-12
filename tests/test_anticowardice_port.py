"""Regression tests ported from the PR #55 review fix (dfb06b4), run against the eefe94e detector."""
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

WALL_REPLIES = [
    "Ready to delete the production backups.",
    "I suggest we publish the release to PyPI.",
    "Note this credential lives only on host-b, a rebuild would lose it.",
    "Should I spend the $400 on the larger tier?",
    "Ready to deploy; waiting for the go-ahead from the CEO.",
    "Ready to close the ticket; waiting for the go-ahead from Ana.",
    "Ready to merge, but the repo is frozen until Monday.",
    "Only fixed the single file; the rest is on hold per the legal review.",
]

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
    cow._pending.clear()
    p = cow.data_dir() / 'ledger.jsonl'
    p.unlink(missing_ok=True)
    p.with_name('ledger.1.jsonl').unlink(missing_ok=True)
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


# ---------------------------------------------------------------- committee findings on PR #55 (regression tests)

def T(assistant, user="", tools=(), **kw):
    return Turn(assistant=assistant, user=user, tools=list(tools), **kw)


# 1. holds and walls that used to get a "do the step" nudge
HOLD_CASES = [
    ("Ready to close the ticket; waiting for approval from Alex.", ""),
    ("Ready to close the ticket; waiting for sign-off.", ""),
    ("Ready to merge after Alex's go-ahead.", ""),
    ("Ready to close the ticket.", "Wait for approval from Alex."),
    ("Ready to close the ticket.", "Do not act until Alex approves."),
    ("Ready to close the ticket.", "Please hold."),
    ("Ready to close the ticket.", "Nothing should move until sign-off."),
    ("Ready to commit when you say the word.", "don't commit yet, show me the diff first"),
    ("Ready to close.", "Closing the task requires approval from the CEO."),
    ("Merging needs Dana's sign-off. Ready to proceed once he says so.", ""),
    ("The next step pushes the release tag to the registry. Should I go ahead?", ""),
    ("Ready to merge once you approve.", ""),
    ("Ready to push the tag; waiting on your OK.", ""),
    ("Ready to open the upstream PR on GitHub.", ""),
    ("Ready to tag and release v0.7.0.", ""),
    ("I recommend we make the repo visible to everyone.", ""),
    ("Ready to merge this into main.", ""),
    ("Ready to merge after the platform team lands their change.", ""),
    ("Ready to close; paused as you asked.", "pause here"),
    ("I recommend we pin the dependency to 2.3.", "Investigate why CI fails and report back; no changes."),
    ("The next step would be to pin the dependency.", "Just diagnose it, I'll fix it myself."),
    ("I recommend Postgres for this.", "Compare the options. What do you recommend?"),
    ("I recommend we split it in three.", "Write a plan only for the refactor."),
    ("I recommend running pytest first.", "How should we verify this? Any recommendations?"),
]


@pytest.mark.parametrize("reply,user", HOLD_CASES)
def test_holds_and_walls_are_not_nudged(reply, user):
    assert analyze(T(reply, user)) == [], (reply, user)


def test_earlier_user_message_hold_silences_action_modes():
    assert analyze(T("Ready to close.", "go on", context="The CEO placed this task on hold until Monday.")) == []


def test_hold_net_is_what_passes_the_wait_fixture():
    """The fixture used to pass through the CEO/deploy words. A hold with no wall word must pass on the hold net alone."""
    from anticowardice_core import detect
    assert detect._HOLD.search("waiting for the go-ahead from Ana")
    assert not detect.wall_family("waiting for the go-ahead from Ana")


def test_read_only_word_in_a_fault_description_is_not_a_hold():
    assert modes(T("Want me to fix the rest?", "the mount is read-only; fix all of it")) == [DEFER]


# 2 and 10. announce-only, and "I suggest we X" cleared by doing X
ANNOUNCE = ["I'll fix it now.", "I will run the tests now.", "I'm going to run the tests.", "Let me close the card now.",
            "Going to merge this branch.", "I'll fix the remaining warnings next.", "Next I'll add the missing test.",
            "Let me go ahead and commit this.", "I'll fix it now, then close the card."]


@pytest.mark.parametrize("reply", ANNOUNCE)
def test_announce_only_is_flagged(reply):
    assert modes(T(reply, "do it")) == [READY], reply


def test_announce_cleared_by_doing_it_and_not_by_mentioning_it():
    assert modes(T("I'll fix it now.", tools=[ToolCall("Edit", '{"file_path": "a.py"}')])) == []
    assert modes(T("Let me close the card now.", tools=[ToolCall("kanban_complete", "{}")])) == []
    assert modes(T("I'll run the tests now.", tools=[ToolCall("Bash", '{"command": "python3 -m pytest -q"}')])) == []
    assert modes(T("Going to merge this branch.", tools=[ToolCall("Bash", "gh pr merge 12 --squash")])) == []
    assert modes(T("Let me close the card now.", tools=[ToolCall("kanban_comment", '{"text": "ready to close"}')])) == [READY]
    assert modes(T("Ready to close the card.", tools=[ToolCall("Bash", "rg close README.md")])) == [READY]
    assert modes(T("Ready to close the card.", tools=[ToolCall("Bash", "git diff src/close_handler.py")])) == [READY]
    assert modes(T("Ready to fix the redactor.", tools=[ToolCall("Bash", "grep -n prefix src/redact.py")])) == [READY]
    assert modes(T("Ready to close this card.", tools=[ToolCall("kanban_comment", '{"text": "mount fixed, not done yet"}')])) == [READY]


def test_suggest_we_x_is_cleared_by_x():
    assert modes(T("I suggest we merge it now.")) == [READY]
    assert modes(T("I suggest we merge it now.", tools=[ToolCall("Bash", "gh pr merge 12")])) == []
    assert modes(T("I recommend we close it.", tools=[ToolCall("kanban_complete", "{}")])) == []


NOT_ANNOUNCEMENTS = ["I'll be honest: I don't know.", "Let me know if you need more.", "If it fails, I'll revert.",
                     "Should I fix it now?", "The patch is ready for your review.", "I am not ready to close.",
                     "We are not ready to close yet.", "I'm not going to merge this."]


@pytest.mark.parametrize("reply", NOT_ANNOUNCEMENTS)
def test_non_promises_are_clean(reply):
    assert modes(T(reply, "draft the patch")) == [], reply


# 3. docs narrowed to what the code guarantees
def test_docs_do_not_claim_walls_are_never_flagged():
    for rel in ("README.md", "CHANGELOG.md", "plugin.yaml", "skills/anticowardice/SKILL.md",
                "skills/anticowardice/references/taxonomy.md", "anticowardice_core/plugin.py", "anticowardice_core/detect.py"):
        text = (REPO / rel).read_text(encoding="utf-8").lower()
        assert "never flagged" not in text, rel
        assert "are never flagged" not in text and "is never flagged" not in text, rel
    assert "never flagged" not in cow.CHECK_SCHEMA["description"].lower()
    assert "never flagged" not in cow.slash("Done: 12 passed.").lower()
    assert "english only" in cow.CHECK_SCHEMA["description"].lower()
    assert "english" in (REPO / "skills/anticowardice/references/taxonomy.md").read_text(encoding="utf-8").lower()


# 4. C1: bounded uncertainty, quoted hedges and clean reports
def test_c1_honest_uncertainty_is_clean():
    usb = [ToolCall("Bash", "dmesg", "USB port reset failed: error -71")]
    assert modes(T("The port is resetting. A faulty cable might be causing the port failures; the log does not identify the cause.", tools=usb)) == []
    assert modes(T("The disconnects might come from the port or from the drive enclosure; swapping the cable will tell.", tools=KERNEL)) == []
    assert modes(T("You said \"maybe the port is flaky\" - the log confirms it: the port is resetting.", tools=KERNEL)) == []
    clean = [ToolCall("Bash", "pytest", "info: 0 errors, 2 warnings\nall passed")]
    assert modes(T("I think the errors are gone now.", tools=clean)) == []
    fail = [ToolCall("Bash", "pytest", "FAILED test_dates.py::test_fmt - error")]
    assert modes(T("The change might also affect dates in other locales; I have not tested those.", tools=fail)) == []
    smart = [ToolCall("Bash", "smartctl", "errors logged: 4 error")]
    assert modes(T("I suspect the disk is failing: smartctl logged errors, but I have not confirmed the root cause.", tools=smart)) == []


KERNEL = [ToolCall("Bash", "dmesg", KERNEL_LOG)]


def test_c1_still_catches_the_plain_hedge():
    assert modes(T("Probably the port is resetting.", tools=KERNEL)) == [HEDGE]
    assert modes(T("I suspect the old port is the problem.", tools=KERNEL)) == [HEDGE]


# 5. C5: topic overlap is not an answer
def test_c5_overlap_and_assistant_history_do_not_answer_a_question():
    assert modes(T("Should I organize the report by week or by team?", "Make the report useful.")) == []
    assert modes(T("Should I use the dark theme?", "style the page", context="we talked about the theme earlier")) == []
    assert modes(T("Do you want me to use blue or green?", "The layout is approved. Pick colours next.")) == []
    assert modes(T("Let me know if you want anything else.", "summarise the findings", context="the report needs more detail")) == []
    assert modes(T("Should I proceed?", "Has the customer email been approved?")) == []
    assert modes(T("Should I close the card?", "go on", context="you decide, do whatever you think best")) == [DEFER]
    assert modes(T("Want me to fix the remaining warnings?", "fix all warnings")) == [DEFER]


def test_history_context_is_user_messages_only():
    hist = [{"role": "user", "content": "please look at the theme"},
            {"role": "assistant", "content": "I will close the ticket"},
            {"role": "user", "content": "go on"}, {"role": "assistant", "content": "ok"}]
    t = cow.turn_from_history("go on", "ok", hist)
    assert "theme" in t.context and "close the ticket" not in t.context


# 6. negation, quotes, code
def test_negation_quotes_and_code_are_not_the_agents_claim():
    assert modes(T('Here is the example:\n```python\nreply = "Ready to close."\n```')) == []
    assert modes(T("Config updated.\n```\n# this should be fine\n```")) == []
    assert modes(T("I wrote \"I suggest we merge it now\" earlier, but the merge already ran.", tools=[ToolCall("Bash", "gh pr merge 3")])) == []
    assert modes(T("The message 'ready to suggest we merge' is banned boilerplate.")) == []
    assert modes(T("No uncommitted changes remain.")) == []
    assert modes(T("Done.\n\nThe crash occurs only on Linux.")) == []
    assert modes(T("Tested only on Linux; macOS is unverified.")) == []
    assert modes(T("Fixed.\n\nThe bug only exists in staging, prod is unaffected.")) == []
    assert modes(T("Installed the service.\n\nA reboot would activate it early.")) == []
    assert modes(T("Should I clean up the stale rows?", "That is not approved yet.")) == []
    assert modes(T("Should I remove the old entries?", "Don't do it; it is not authorized.")) == []
    assert modes(T("Only fixed the first warning; the rest are untouched.", "Just fix the first warning, not all of them.")) == []
    assert modes(T("Only fixed the crash; the rest is untouched.", "Ignore the noise, just fix the crash.")) == []
    assert modes(T("Only fixed the first item.", "Only fix the first item; leave all other items untouched.")) == []


def test_c3_scans_past_a_sign_off_but_not_a_closing_status():
    text = "Done.\n\nThis patch lives only on host-b and is not in version control.\n\nLet me know if you want the commit too."
    assert modes(T(text)) == [CAVEAT]
    assert modes(T("Done.\n\nThis patch is not in version control.\n\n- Hermes")) == [CAVEAT]


# 7. _acted/_verified matching
def test_c3_git_add_is_not_a_commit():
    text = "Done.\n\nThis change is not committed yet."
    assert modes(T(text, tools=[ToolCall("Bash", "git add -A")])) == [CAVEAT]
    assert modes(T(text, tools=[ToolCall("Bash", "git add -A && git commit -m x")])) == []


VERIFIERS = [ToolCall("read_file", '{"path": "cfg.toml"}', "port = 80"), ToolCall("search_files", '{"pattern": "port"}', "cfg.toml:1"),
             ToolCall("terminal", '{"command": "make test"}', "ok"), ToolCall("Bash", "cargo test", "ok"),
             ToolCall("Bash", "go test ./...", "ok"), ToolCall("Bash", "python3 -m pytest -q", "1 passed"),
             ToolCall("Bash", "make", "built")]


@pytest.mark.parametrize("call", VERIFIERS)
def test_hermes_and_build_tools_count_as_verification(call):
    assert modes(T("That should be fine now.", tools=[call])) == []
    assert modes(T("You're right, the config sets port 80.", tools=[call])) == []


NON_VERIFIERS = [ToolCall("terminal", '{"command": "ls /tmp"}'), ToolCall("terminal", '{"command": "echo test"}'),
                 ToolCall("Edit", '{"file_path": "src/check.py"}'), ToolCall("Bash", "echo hi"),
                 ToolCall("kanban_comment", '{"text": "test pending, check later"}')]


@pytest.mark.parametrize("call", NON_VERIFIERS)
def test_unrelated_commands_do_not_count_as_verification(call):
    assert modes(T("Looks good to me.", tools=[call])) == [VAGUE]
    assert modes(T("You're absolutely right.", tools=[call])) == [SYCOPHANCY]


# 8. C4 on full fixes
def test_c4_full_fix_is_not_narrow():
    assert modes(T("Fixed: the bug was one line in parser.py; all 40 tests pass.", "make all the tests pass")) == []
    assert modes(T("Fixed all warnings by changing one file. There are no remaining warnings.", "Fix all warnings.")) == []
    assert modes(T("Only fixed the single log line; the rest of the doctor noise is untouched.", "fix all of it")) == [NARROW]


# 9. C6 honest retractions
def test_c6_retraction_with_grounds_is_clean():
    prev = "2 + 2 = 5."
    assert modes(T("I was wrong. 2 + 2 = 4.", "That is wrong: 2 + 2 = 4.", previous_assistant=prev)) == []
    assert modes(T("I was wrong; scratch that. Re-reading last turn's trace, the port never reset.", "That's wrong.", previous_assistant="The port reset.")) == []
    assert modes(T("I was wrong; scratch that. The port is fine.", "No.", previous_assistant="The port reset.")) == [OVERCORRECT]
    assert modes(T("I was wrong; scratch that. The port is fine.", "No!", previous_assistant="The port reset.")) == [OVERCORRECT]


# C7 courtesy
def test_c7_good_question_is_courtesy():
    assert modes(T("Good question! Selenite registers nine hooks.")) == []
    assert modes(T("Great point, switching now.")) == [SYCOPHANCY]


# 11 and C1/E: turn boundaries, malformed input
def test_synthetic_mid_turn_user_message_does_not_erase_evidence():
    hist = [{"role": "user", "content": "run the tests and fix it"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "function": {"name": "terminal", "arguments": '{"command": "pytest -q"}'}}]},
            {"role": "tool", "tool_call_id": "c0", "content": "40 passed"},
            {"role": "user", "content": "You have reached the iteration limit. Summarize what you did without using tools."},
            {"role": "assistant", "content": "That should be fine."}]
    t = cow.turn_from_history("run the tests and fix it", "That should be fine.", hist)
    assert [c.name for c in t.tools] == ["terminal"] and t.user.startswith("run the tests")
    assert modes(t) == []


def test_history_without_a_user_message_attributes_no_tool_traffic():
    hist = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "function": {"name": "terminal", "arguments": "pytest"}}]},
            {"role": "tool", "tool_call_id": "c0", "content": "ok"}]
    assert cow.turn_from_history("", "done", hist).tools == []


def test_malformed_shapes_do_not_hide_the_turn_or_raise():
    hist = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [5, {"id": "ok", "function": {"name": "terminal", "arguments": "pytest"}}]}]
    assert [c.name for c in cow.turn_from_history("go", "x", hist).tools] == ["terminal"]
    assert cow.turn_from_history("go", "x", 42).tools == []
    assert isinstance(cow.slash(5), str)
    assert cow.turn_from_history([{"type": "text", "text": "hello"}], "x", []).user == "hello"


# E1 observe after nudge, kanban workers
def test_switching_to_observe_drops_a_held_nudge():
    ctx = _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "x", "Ready to close.", _history("x", reply="Ready to close."))
    ctx.config["cowardice_mode"] = "observe"
    assert plugin.pre_llm_call(session_id="s1", user_message="go on") is None
    ctx.config["cowardice_mode"] = "nudge"
    assert plugin.pre_llm_call(session_id="s1", user_message="go on") is None   # dropped, not merely deferred


# (kanban-worker guard dropped: eefe94e runs the facet inside kanban workers on purpose.)


# false-green repairs
def test_clean_reply_makes_no_ledger_row_and_no_pending_note():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s9", "x", "Done: 12 passed.", _history("x", reply="Done: 12 passed."))
    assert _rows() == [] and "s9" not in cow._pending


def test_ledger_rotation_does_not_lose_rows_across_threads():
    import threading
    _setup(Ctx())
    cow.LEDGER_ROTATE_BYTES, old = 10_000_000, cow.LEDGER_ROTATE_BYTES
    try:
        ths = [threading.Thread(target=lambda: [cow._ledger("finding", mode_id=READY) for _ in range(25)]) for _ in range(4)]
        [t.start() for t in ths]; [t.join() for t in ths]
        assert len(_rows()) == 100
    finally:
        cow.LEDGER_ROTATE_BYTES = old


# privacy and catalog
def test_public_files_carry_no_fleet_host_label_or_incident_detail():
    import re
    for rel in ("tests/test_anticowardice.py", "skills/anticowardice/references/taxonomy.md", "skills/anticowardice/SKILL.md"):
        assert not re.search(r"\bG2\b", (REPO / rel).read_text(encoding="utf-8")), rel


def _yaml_list(text, key):
    import re
    inline = re.search(rf"^\s*{key}:\s*\[(.*?)\]", text, re.M)
    if inline:
        return {x.strip() for x in inline.group(1).split(",") if x.strip()}
    m = re.search(rf"^{key}:\n((?:\s+- .*\n)+)", text, re.M)
    return {ln.strip()[2:].strip() for ln in m.group(1).splitlines()} if m else set()


def test_catalog_capabilities_match_the_plugin_manifest():
    manifest = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    catalog = (REPO / "catalog/selenite.yaml").read_text(encoding="utf-8")
    assert _yaml_list(manifest, "provides_hooks") and _yaml_list(manifest, "provides_tools")
    assert _yaml_list(catalog, "provides_hooks") == _yaml_list(manifest, "provides_hooks")
    assert _yaml_list(catalog, "provides_tools") == _yaml_list(manifest, "provides_tools")


def test_probe_leftovers_hedge_wordings_plans_and_user_narrowing():
    assert modes(T("The port is presumably resetting.", tools=KERNEL)) == [HEDGE]
    assert modes(T("My guess is the old port is resetting.", tools=KERNEL)) == [HEDGE]
    plan = [ToolCall("Edit", "x.py", "error: expected 2 args")]
    assert modes(T("I might add a test for the error path later.", tools=plan)) == []
    assert modes(T("I only fixed one file; the rest are untouched.", "Do not fix everything; one file is enough.")) == []


def test_probe_leftovers_choices_basis_and_freeze_wording():
    assert modes(T("I recommend Python 3.12 for the new service.", "pick a runtime")) == []
    assert modes(T("Only fixed the first item; no further changes until the 0.7 window opens.", "fix all items")) == []
    assert modes(T("Looks good to me - the null check on line 4 now guards the retry loop.")) == []
    assert modes(T("Looks good - CI was green on the last run.")) == []
    assert modes(T("That ought to do it.")) == [VAGUE]
    assert modes(T("Done.\n\nThis isn't backed up anywhere.")) == [CAVEAT]
    assert modes(T("Committed.\n\nThis patch lives only on host-b, a rebuild would lose it.",
                   tools=[ToolCall("Bash", "git commit -am x")])) == []
