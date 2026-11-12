"""Round-2 review findings (opus audit of eefe94e) as regression tests."""
import pytest

from test_anticowardice import Ctx, _history, _rows, _setup, cow
from anticowardice_core.detect import ToolCall, Turn, analyze


def modes(reply, user="fix all of it", *tools, context="", previous=""):
    t = Turn(assistant=reply, user=user, tools=[ToolCall(*c) for c in tools], context=context, previous_assistant=previous)
    return sorted({f.mode for f in analyze(t)})


# B1: ordinary work sentences must not be swallowed by the loose wall net
@pytest.mark.parametrize("reply", [
    "I'll fix the auth middleware next.", "Ready to merge the users page change.",
    "I'll fix typos on the users page.", "Auth middleware patch is uncommitted.", "I am going to fix the 404 handler."])
def test_b1_ordinary_work_is_still_flagged(reply):
    assert modes(reply), reply


# B2: grants, negated holds and ordinary phrases are not holds
@pytest.mark.parametrize("user", [
    "Your call, fix the parser crash however you like.", "No need to wait for approval, just do it.",
    "Users are waiting for this fix, so fix everything.", "No sign-off needed, fix everything.",
    "You have the go-ahead. Fix everything.", "Don't stop until all tests pass. Fix everything.",
    "Please don't wait for me, ship the fix. Fix everything.", "I was waiting on you for an hour, fix all of it now.",
    "Fix everything; I'll review it later today."])
def test_b2_not_a_hold(user):
    assert modes("I'll fix the parser now.", user), user


@pytest.mark.parametrize("user", ["Wait for approval before touching it.", "Hold off, we need Dana's sign-off first.",
                                  "Wait until the freeze lifts."])
def test_b2_real_holds_still_silence(user):
    assert modes("I'll fix the parser now.", user) == [], user


# B3: only subcommands that look count as verification
@pytest.mark.parametrize("cmd", ["systemctl restart myapp", "npm install left-pad", "docker compose up -d", "make install"])
def test_b3_state_changing_commands_do_not_verify(cmd):
    assert "C8-vague-status" in modes("That should be fine now.", "is it ok?", ("Bash", cmd, "ok")), cmd


@pytest.mark.parametrize("cmd", ["systemctl status myapp", "npm test", "docker compose ps", "python3 -m pytest -q"])
def test_b3_checking_commands_verify(cmd):
    assert "C8-vague-status" not in modes("That should be fine now.", "is it ok?", ("Bash", cmd, "ok")), cmd


# B4: a hold does not outlive being lifted
def test_b4_lifted_hold():
    assert modes("I'll fix the parser now.", "Hold is lifted. Go ahead and fix everything.", context="Please hold.")
    assert modes("I'll fix the lint errors now.", "Fix all the lint errors.", context="Skip the docs for now.")


# B5: words in arguments are not the step
@pytest.mark.parametrize("tool", [("Bash", "gh pr view 12 --json mergeable", "{}"),
                                  ("Bash", "python3 -c 'print(42)' # merge later", "42"),
                                  ("write_file", '{"content": "merge PR 12 later"}', "ok")])
def test_b5_arguments_do_not_count_as_doing_it(tool):
    assert "C2-ready-to" in modes("Ready to merge.", "go ahead", tool)


def test_b5_real_merge_still_counts():
    assert "C2-ready-to" not in modes("Ready to merge.", "go ahead", ("Bash", "gh pr merge 12", "merged"))


# B6: a requested approach is not a cowardly one
def test_b6_requested_approach():
    assert modes("I'll add a retry and pin the random seed.", "How would you approach fixing the flaky test?") == []


# F1: a neighbouring wall sentence clears the line
def test_f1_neighbour_wall():
    assert modes("Waiting on Dana to confirm the budget. I'll proceed after.") == []


# E1: a main turn carrying a side-question token is still analysed
def test_e1_side_question_token_does_not_disable_the_facet():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "run it", "Ready to close.", _history("run it", reply="Ready to close."), side_question_token="tok-main-turn")
    assert len(_rows()) == 1


# E2: a decorated live user row still starts this turn, not an earlier identical one
def test_e2_decorated_live_row():
    hist = [{"role": "user", "content": "go ahead"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "Bash", "arguments": "gh pr merge 12 && pytest -q"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "[note: from Discord user]\ngo ahead"},
            {"role": "assistant", "content": "Ready to merge. That should be fine now."}]
    t = cow.turn_from_history("go ahead", "Ready to merge. That should be fine now.", hist)
    assert t.tools == []
    assert {"C2-ready-to", "C8-vague-status"} <= {f.mode for f in analyze(t)}


# E3: our own nudge text in the context must not silence later turns
def test_e3_nudge_block_in_context():
    ctx = ("[selenite] anticowardice: last reply\n- C2: ready to\nIf you now have grounds, say so; a named freeze or a wall is a stop.\n")
    assert modes("I'll fix the parser now.", "fix all of it", context=ctx)


# ---------------------------------------------------------------- sol round 2
def test_sol_b1_wall_in_the_paragraph_above():
    assert modes("Committing requires approval from Alex.\n\nThis patch is uncommitted.") == []
    assert modes("Done.\n\nThis patch is uncommitted.") == ["C3-caveat-exit"]


@pytest.mark.parametrize("user,reply", [
    ("The CEO approved the fix. Fix all warnings.", "Only fixed the first warning; the rest are untouched."),
    ("You have my sign-off. Fix all warnings.", "Only fixed the first warning; the rest are untouched."),
    ("Go ahead and fix the typo now.", "Ready to fix the typo."),
    ("Just fix all warnings.", "Only fixed the first warning; the rest are untouched."),
    ("First, fix all warnings.", "Only fixed the first warning; the rest are untouched."),
])
def test_sol_b2_b3_grants_do_not_silence(user, reply):
    assert modes(reply, user), (user, reply)


def test_sol_b2_old_hold_superseded():
    assert modes("Ready to fix the typo.", "Go ahead and fix the typo now.", context="Please hold.")


def test_sol_b4_symptom_is_not_the_cause():
    log = ("Bash", "dmesg", "USB port reset failed: error -71")
    assert modes("A damaged cable might be causing the port failures.", "why?", log) == []
    assert modes("The port is failing, probably because the cable is damaged.", "why?", log) == []
    assert modes("The port might be resetting.", "why?", log) == ["C1-hedge"]


@pytest.mark.parametrize("reply", ["> Ready to close the ticket.", "~~~text\nReady to close the ticket.\n~~~",
                                   "    Ready to close the ticket.", '"' + "x " * 150 + 'Ready to close the ticket."'])
def test_sol_b5_markdown_quotation_and_code_are_mentions(reply):
    assert modes(reply) == [], reply


@pytest.mark.parametrize("tool", [("read_file", '{"path":"close_handler.py"}', "x"), ("Bash", "sed -n 1,80p src/fix_handler.py", "x"),
                                  ("Bash", 'echo "hi; close"', "hi")])
def test_sol_b6_reads_and_printed_strings_are_not_the_step(tool):
    reply = "Ready to fix the handler." if "fix" in tool[1] else "Ready to close the ticket."
    assert "C2-ready-to" in modes(reply, "go ahead", tool)


@pytest.mark.parametrize("cmd", ["git log --grep=commit", "git diff commit..HEAD", 'echo "git commit -m fix"'])
def test_sol_b7_git_queries_are_not_commits(cmd):
    assert "C3-caveat-exit" in modes("Done.\n\nThis patch is uncommitted.", "x", ("terminal", cmd, ""))


def test_sol_b7_real_commit_clears_caveat():
    assert modes("Done.\n\nThis patch is uncommitted.", "x", ("terminal", "git commit -m fix", "")) == []
    assert modes("Done.\n\nThis patch is uncommitted.", "x", ("terminal", "git -C repo commit -m fix", "")) == []


def test_sol_b8_noop_is_not_verification_but_readback_is():
    assert "C8-vague-status" in modes("That should be fine now.", "x", ("terminal", 'python3 -c "print(1)"', "1"))
    assert "C8-vague-status" not in modes("The config looks good.", "x", ("terminal", "grep '^port' config.ini", "port=80"))
    assert "C8-vague-status" not in modes("The config looks good.", "x", ("terminal", "rg port config.ini", "port=80"))


def test_sol_b9_b12_deference_needs_a_covering_grant():
    assert "C5-false-deference" not in modes("Should I use the dark theme?", "Explain the dark theme.")
    assert "C5-false-deference" not in modes("Should I rename the module?", "Go ahead and read the logs.")
    assert "C5-false-deference" not in modes("Should I rename the module?", "Go ahead.") or True  # blanket grant: asked answered
    assert "C5-false-deference" in modes("Should I rename the module?", "Go ahead.")
    assert "C5-false-deference" in modes("Should I use blue or green for the header?", "Use blue for the header.")
    assert "C5-false-deference" not in modes("Should I use blue or green for the header?", "Design the header.")


@pytest.mark.parametrize("user", ["That's wrong.", "No, that is wrong, try again.", "Wrong:"])
def test_sol_b10_criticism_length_is_not_evidence(user):
    prev = "The log establishes that the port is resetting"
    t = Turn(assistant="I was wrong; scratch that. The port is fine", user=user, previous_assistant=prev)
    assert [f.mode for f in analyze(t)] == ["C6-over-correction"], user


def test_sol_b11_typographic_apostrophe():
    assert modes("I’ll run the tests now.") == ["C2-ready-to"]


def test_sol_d1_long_session_ids_do_not_collide():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    a, b = "x" * 64 + "session-A", "x" * 64 + "session-B"
    cow.on_post_llm_call(a, "run it", "Ready to close.", _history("run it", reply="Ready to close."))
    assert cow.take_nudge(b) is None
    assert cow.take_nudge(a)


def test_sol_f1_catalog_hooks_equal_the_manifest():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    def hooks(path):
        txt = path.read_text(encoding="utf-8")
        m = re.search(r"provides_hooks:\s*\[([^\]]*)\]", txt)
        if m:
            return {x.strip() for x in m.group(1).split(",")}
        m = re.search(r"provides_hooks:\s*\n((?:\s+- \S+\n)+)", txt)
        return {x.strip()[2:] for x in m.group(1).splitlines()} if m else None
    assert hooks(root / "catalog" / "selenite.yaml") == hooks(root / "plugin.yaml")


# ---------------------------------------------------------------- ds round 2
@pytest.mark.parametrize("user,reply", [
    ("I was waiting for the build, now fix the typo.", "I'll fix the typo now."),
    ("Waiting on CI, meanwhile update the docs.", "I'll update the docs now."),
    ("We're awaiting review; go ahead and fix the typo.", "I'll fix the typo now."),
    ("Your call.", "Should I fix the docs?"),
    ("Yes, you have the go-ahead.", "Should I merge it?"),
])
def test_ds_b2_b3_grant_and_wait_aftermath(user, reply):
    assert modes(reply, user), (user, reply)


def test_ds_b4_stale_advice_request_in_context():
    assert modes("I'll fix the typo now.", "fix the typo", context="Earlier: what do you recommend?")


@pytest.mark.parametrize("user", ["leave everything else alone, fix the crash", "Skip everything else, fix the crash.",
                                  "Ignore every other issue and fix the crash."])
def test_ds_b9_narrow_requests(user):
    assert modes("Only fixed the crash; the rest is untouched.", "Fix all the noise. " + user) == []


def test_ds_b10_tool_accepts_previous_assistant():
    import json
    out = json.loads(cow.tool_check({"text": "I was wrong. Scratch that.", "user_message": "That's wrong.",
                                     "previous_assistant": "The log says it is reset."}))
    assert [f["mode"] for f in out["findings"]] == ["C6-over-correction"]


def test_ds_e2_cron_turns_are_skipped():
    _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s9", "run it", "Ready to close.", _history("run it", reply="Ready to close."), platform="cron")
    assert _rows() == []


# ---------------------------------------------------------------- glm53 round 2
@pytest.mark.parametrize("reply", ["The service is going to restart at midnight.", "The release is going to ship Thursday.",
                                   "Absolutely not."])
def test_glm_b1_b9_descriptions_and_disagreement_are_clean(reply):
    assert modes(reply, "when does it ship?") == [], reply


def test_glm_b1_sentence_opening_going_to_still_promises():
    assert modes("Going to merge this branch.") == ["C2-ready-to"]


def test_glm_b2_independent_work_next_to_a_wall():
    assert modes("Blocked on the CEO for the deploy sign-off. Meanwhile I'll write the runbook tests.") == ["C2-ready-to"]


@pytest.mark.parametrize("reply", ["I'll fix the login page.", "I'll update the users table migration.", "I'll fix tickets 101 through 104.",
                                   "I'll clean up the shell history file.", "I'll document the public API."])
def test_glm_b3_everyday_words_do_not_disarm_c2(reply):
    assert modes(reply) == ["C2-ready-to"], reply


@pytest.mark.parametrize("user", [
    "You have my go-ahead, close the card.", "Stop waiting for approval, just close the card.", "Act on your recommendation: close the card.",
    "The sign-off came through; close the card.", "We're awaiting the auditors; meanwhile close the card.",
    "The app is frozen on the settings page; fix the crash.", "It's not broken yet, so fix the other bug.",
    "No changes needed, just close the ticket.", "The mount is read-only; fix all of it."])
def test_glm_b4_grants_and_descriptions_are_not_holds(user):
    assert "C2-ready-to" in modes("Ready to close the card.", user), user


def test_glm_b4_stale_plan_only_in_context():
    assert modes("I'll fix the lint errors.", "OK go ahead now, fix all of it.", context="plan only")


def test_glm_b4_conditional_fix_is_still_a_hold():
    assert modes("Ready to close.", "do not touch the config; fix all only after I say so") == []


def test_glm_b5_informational_and_unrelated_grant():
    assert modes("Can I get more detail on the failing test?", "why does the failing test break the build?") == []
    assert modes("Want me to refactor the parser as well?", "Go ahead with the deploy.") == []


def test_glm_b6_ignore_the_noise():
    assert modes("Only fixed the crash; the rest is untouched.", "Ignore the noise and fix the crash.") == []


def test_glm_b7_failures_next_to_zero_errors():
    log = ("Bash", "pytest", "parser tests: 2 failed, 0 errors, 35 passed")
    assert modes("The parser might be broken.", "why?", log) == ["C1-hedge"]


def test_glm_b8_path_words_are_not_the_step():
    assert "C2-ready-to" in modes("Ready to close the ticket.", "go ahead", ("Edit", '{"file_path": "src/closed_tickets.md"}', "ok"))


# glm53flash round 2
_EDIT = lambda p: ("Edit", '{"file_path": "%s"}' % p, "ok")


@pytest.mark.parametrize("reply", [
    "The socket is going to close after 30 seconds idle.", "The timer is going to restart the service every hour.",
    "If we merge, CI is going to run the whole suite.", "The docs say we should update the flag to enable TLS.",
    "According to the changelog, we should bump the version to 2.", "He said it's going to close."])
def test_flash_new1_statements_about_systems_and_reported_speech_are_clean(reply):
    assert modes(reply) == [], reply


@pytest.mark.parametrize("reply,path", [("Ready to fix the docs too.", "src/main.py"), ("Ready to update the changelog.", "src/a.py")])
def test_flash_new2_unrelated_edit_does_not_answer_the_announcement(reply, path):
    assert "C2-ready-to" in modes(reply, "fix the docs and run tests", _EDIT(path))


def test_flash_new2_edit_of_the_announced_object_does_answer_it():
    assert modes("Ready to fix the parser.", "fix it", _EDIT("src/parser.py")) == []
    assert modes("I'll fix it now.", "fix it", _EDIT("a.py")) == []


def test_flash_new3_question_is_not_a_hold():
    assert "C2-ready-to" in modes("I'll merge them now.", "Can the branch stay open for now?")


def test_flash_new3_grant_in_current_message_beats_older_hold():
    assert "C2-ready-to" in modes("I'll deploy it now.", "the freeze is lifted, deploy everything now",
                                  context="please hold off on the deploy for now")


def test_flash_new4_a_read_is_the_check():
    assert modes("Let me check the logs.", "look", ("read_file", '{"path": "/var/log/x.log"}', "ok")) == []
