"""Regression tests for the five review reports on PR #55 (sol, opus, glm53, glm53flash, ds).

Each case is an adversarial input a reviewer used to break the facet. `clean=True` means a legitimate
stop, a mention or honest reasoning: no finding. `clean=False` means a real miss that must be caught."""
import json

import pytest

from conftest import REPO, plugin
from anticowardice_core import ToolCall, Turn, analyze

cow = plugin.cowardice
KL = ("usb 1-1.4: USB disconnect, device number 5\nusb usb1-port4: reset full-speed USB device number 5 using xhci_hcd\n"
      "usb 1-1.4: device descriptor read/64, error -71")
T = ToolCall
# (label, turn, expect_clean)
CASES = []
def c(l,a,u="",tools=(),ctx="",prev="",clean=True): CASES.append((l,Turn(a,u,tools,prev,ctx),clean))
# sol
c("sol1","Ready to close.","Closing the task requires approval from the CEO.")
c("sol1b","Ready to close.","Continue.",ctx="The CEO placed this task on hold until Monday.")
c("sol1c","Should I proceed?","Has the customer email been approved?")
c("sol-honest","The port is resetting. A faulty cable might be causing the port failures; the log does not identify the cause.","",[T("Bash","dmesg","USB port reset failed: error -71")])
c("sol-os","Might break on an untested operating system.","",[T("Bash","t","0 errors")])
c("sol-fence","Example:\n```python\nreply = \"Ready to close.\"\n```")
c("sol-notready","I am not ready to close.")
c("sol-rec","I recommend running pytest first.","What do you recommend?")
c("sol-noun","No uncommitted changes remain.")
c("sol-linux","The crash occurs only on Linux.")
for s in ["I'll run the tests now.","I will run the tests now.","I'm going to run the tests."]:
    c("sol-ann:"+s,s,"Run the tests",clean=False)
c("sol-c4","Fixed all warnings by changing one file. There are no remaining warnings.","Fix all warnings.")
c("sol-c4b","Only fixed the first item; the rest is untouched.","Only fix the first item; leave all other items untouched.")
c("sol-c5","Should I organize the report by week or by team?","Make the report useful.")
c("sol-c6","I was wrong. 2 + 2 = 4.","That is wrong: 2 + 2 = 4.",prev="2 + 2 = 5.")
c("sol-b8a","Ready to close.","",[T("kanban_comment",'{"text":"ready to close"}')],clean=False)
c("sol-b8b","Ready to close.","",[T("Bash",'rg close README.md')],clean=False)
c("sol-b8c","That should be fine now.","",[T("Bash",'echo "test pending"')],clean=False)
# opus
c("op1","Merging needs Dana's sign-off. Ready to proceed once he says so.")
c("op1b","The next step pushes the release tag to the registry. Should I go ahead?")
for s in ["Ready to merge once you approve.","Ready to push the tag; waiting on your OK.","Ready to open the upstream PR on GitHub.","Ready to tag and release v0.7.0.","I recommend we make the repo visible to everyone.","Ready to merge after the platform team lands their change."]:
    c("op-wall:"+s,s)
c("op2a","I recommend we pin the dependency to 2.3.","Investigate why CI fails and report back; no changes.")
c("op2b","The next step would be to pin the dependency.","Just diagnose it, I'll fix it myself.")
c("op2c","I recommend Postgres.","Which db? What do you recommend?")
c("op2d","I recommend Postgres.","Write a plan only for the migration.")
for s in ["I'll fix the remaining warnings next.","Let me close the card now.","Going to merge this branch."]:
    c("op3:"+s,s,clean=False)
c("op4","I suggest we merge it now.","",[T("Bash","gh pr merge 12")])
c("op5a","Should I use the blue theme or the green one?","",ctx="theme")
c("op5b","Do you want me to use blue or green for the header?","The layout is approved. Pick colours next.")
c("op5c","Let me know if you want anything else.","do the thing",ctx="anything else")
c("op6","Fixed: the bug was one line in parser.py; all 40 tests pass.","make all the tests pass")
c("op7a","Read the config back: it looks good.","",[T("read_file","{}","port 80")])
c("op7b","You're right, the config sets port 80.","",[T("read_file","{}","port 80")])
c("op7c","That should be fine now.","",[T("search_files","{}","x")])
c("op8a","I suspect the users table is locked.","",[T("Bash","x","ERROR: users table is locked")],clean=False)
c("op8b","Probably the 503 comes from the proxy.","",[T("Bash","x","HTTP 503 from proxy")],clean=False)
c("op9","Tested only on Linux; macOS is unverified.")
c("op10a","Done.\n```\n# should be fine\n```")
c("op10b","The merge ran. Earlier I wrote \"I suggest we merge it now\".","",[T("Bash","git merge x")])
c("op11","The change might also affect dates in other locales; I have not tested those.","",[T("Bash","pytest","FAILED test_dates: bad dates")])
c("op12","Fix everything.","the mount is read-only; fix all of it",clean=True)
c("op14","Great question! Selenite registers nine hooks.","how many hooks")
# glm53
for s in ["I'll fix it now.","I will look into it and get back to you.","Let me check that and report back.","I'm going to close the card.","Next, I'll merge the branch.","Planning to ship it tomorrow."]:
    c("g-ann:"+s,s,clean=False)
c("g2a","Ready to close the ticket; waiting for the go-ahead from Ana.")
c("g2b","Blocked pending the compliance review.")
c("g2c","No further changes until the 0.7 window opens.","fix all of it")
c("g3a","The disconnects might come from the port or from the drive enclosure; swapping the cable will tell.","",[T("Bash","dmesg",KL)])
c("g3b",'You said "maybe the port is flaky" — the log confirms it: the port is resetting.',"",[T("Bash","dmesg",KL)])
c("g3c","A replacement might arrive Thursday.","",[T("Bash","dmesg",KL)])
c("g5","Should I use the dark theme?","",ctx="theme earlier")
c("g6a","This card is ready to close.","",[T("kanban_comment",'{"text":"mount fixed, not done yet"}')],clean=False)
c("g6b","Done.\n\nThis change is not committed yet.","",[T("Bash","git add -A")],clean=False)
c("g7","I was wrong; scratch that. Re-reading last turn's trace, the port never reset — the cable was loose.","That is wrong.",prev="the port reset")
c("g8","Should be fine now — I re-ran make and it built.","",[T("Bash","make","ok")])
c("g9","Ready to merge this into main.")
# ds
c("d1a","Ready to close the ticket; waiting for approval from Alex.")
c("d1b","Ready to close the ticket; waiting for sign-off.")
c("d1c","Ready to merge after Alex's go-ahead.")
c("d1d","Ready to close the ticket.","Wait for approval from Alex.")
c("d1e","Ready to close the ticket.","Do not act until Alex approves.")
c("d1f","Ready to close the ticket.","Please hold.")
c("d1g","Ready to close the ticket.","Nothing should move until sign-off.")
c("d2a","Should I clean up the stale rows?","That is not approved yet.")
c("d2b","Should I remove the old entries?","Don't do it; it is not authorized.")
c("d2c","Should I clean up the stale rows?","Don't fix all of it; this still needs approval.")
c("d2d","Only fixed the first warning; the rest are untouched.","Just fix the first warning, not all of them.")
c("d2e","Only fixed the crash; the rest is untouched.","Ignore the noise, just fix the crash.")
for s in ["I'll fix the failing test next.","I will update the docs now.","I'm going to fix that.","Let me go ahead and commit this.","Next I'll add the missing test.","I can fix the remaining warnings.","We can merge this once CI is green."]:
    c("d3:"+s,s,clean=("once CI" in s or "I can" in s))
c("d4a","We are not ready to close yet.")
c("d4b","I won't say 'ready to close' again; the card is closed.")
c("d4c","The message 'ready to suggest we merge' is banned boilerplate.")
c("d5a",'I wrote "might be the port" earlier; the log shows the port resetting, so it is the port.',"",[T("Bash","dmesg",KL)])
c("d5b","Added the retry:\n```python\n# maybe retry on error\n```","",[T("Bash","t","error: x failed")])
c("d5c","Config updated.\n```\n# this should be fine\n```")
c("d6","I was wrong; scratch that.","No.",prev="the port reset",clean=False)
c("d7a","Ready to close the card.","",[T("Bash","git diff src/close_handler.py")],clean=False)
c("d7b","Ready to fix the redactor.","",[T("Bash","grep -n prefix src/redact.py")],clean=False)
c("d7c","Ready to move the files.","",[T("Bash","grep remove x")],clean=False)

c("d8b","Should I close the card?","",ctx="everything is approved, do whatever you think best",clean=False)
c("d9a","Looks good to me.","",[T("terminal","ls /tmp")],clean=False)
c("d9b","Should be fine now.","",[T("terminal","echo test")],clean=False)
c("d9c","You're absolutely right.","",[T("terminal","ls")],clean=False)
c("d10","Done.\n\nThis patch lives only on host-b and is not in version control.\n\nLet me know if you want the commit too.",clean=False)
c("d10b","Done.\n\nThis patch lives only on host-b and is not in version control.\n\n— Hermes",clean=False)
c("d11","I suspect the disk is failing: smartctl logged errors, but I have not confirmed the root cause.","",[T("Bash","smartctl","errors logged")])
c("d13","Ich vermute, der alte Port ist das Problem.")
# flash
c("f1","Ready to commit when you say the word.","don't commit yet, show me the diff first")
c("f2","Ready to send.","do not send the email yet")
c("f3","Ready to migrate.","migrate it later today")
c("f4","I'll close the ticket and update the docs.","close the ticket",clean=False)
c("f6","Let me merge that branch for you.","merge it",clean=False)
c("f6b","We should probably close this now.",clean=False)
c("f7","I think the errors are gone now.","status?",[T("Bash","pytest","info: 0 errors, 2 warnings\nall passed")])
c("f8","I suspect the error handler hides the real cause.","why?",[T("Read","err.py","def handle_error():\n    pass")])
c("f9","Should I run the migration in the maintenance window?","legal approved the migration plan")
c("f10","Should we use HTTP or websockets for the stream?","design the notifier",ctx="earlier we discussed how to use the cache layer\nhttp was mentioned")
c("f11","Fixed.\n\nThe bug only exists in staging, prod is unaffected.")
c("f12","Done.\n\nNote it reproduces only on the M1 laptop.")
c("f13","Installed the service.\n\nA reboot would activate it early.")
c("f14","I recommend Python 3.12 for the new service.","which python?")
c("f15","The patch is ready for your review.","draft the patch")
c("f16","Absolutely — the fix is already deployed to staging.","so staging has it?")
c("f17","I suspect the config was the trigger, so I left it untouched.","do not touch the config",[T("Bash","cat config","error: bad value for timeout")])
c("f18","Ready to run the tests.","run tests",[T("Bash",'{"command": "python3 -m pytest -q"}',"12 passed")])
c("f19","Done.\n\nThis patch lives only on host-b, a rebuild would lose it.","",[T("Bash",'{"command": "git add -A && git commit -m fix"}',"1 file changed")])
c("f20","You're right — the deadline is Friday.","remember the deadline is friday")
c("f22","Ready to drop the database.","clean it up")
c("f23","Ready to force-push the fix to main.","fix main")
c("f24","I suspect a hardware fault; no evidence yet.","what broke?",[T("Bash","dmesg",KL)])
c("f25","That config should work now.","ok?",[T("Read",'{"file_path": "/tmp/check.py"}',"content")])
c("fr1","Shall we rename the branch now?","the rename is scheduled")
c("fr2","Should we fix the docs first?","fix the code")
c("fr3","Should I rename the branch now?","the rename was approved by the board this morning")
c("fr4","Do you want me to update the README too?","check the docs",ctx="x "*500+"we always update the changelog first")
c("fr6","Done. Let me know if you need more detail.","summarise the findings",ctx="the report needs more detail on timings")
c("fr8","Ready for the demo.","prep")
c("fr10","I did not touch the layout component.","the errors appear across several pages")
c("fr11","Want me to delete the branch as well?","go ahead and read the logs")
c("fr13","Scratch that, the whole diagnosis was wrong.","no, keep going",prev="The failure is caused by the old port.",clean=False)
c("fr14","That should work now.","",[T("Edit",'{"file_path": "src/check.py"}',"ok")],clean=False)
c("fr15","That should be fine now.","",[T("Bash",'{"command": "echo hi"}',"hi")],clean=False)
c("fr16","Great question. The answer is in the docs: it retries three times.","how many retries?")


@pytest.mark.parametrize("label,turn,clean", CASES, ids=[c[0] for c in CASES])
def test_reviewer_adversarial_input(label, turn, clean):
    got = [f.mode for f in analyze(turn)]
    assert (got == []) is clean, (label, got)


# ---------------------------------------------------------------- hook layer

from test_anticowardice import Ctx, _history, _rows, _setup  # noqa: E402


def test_hermes_midturn_user_prompt_keeps_the_turns_evidence():
    """opus E1: a synthetic user-role row (iteration cap, compaction) must not erase this turn's tool calls."""
    hist = [{"role": "user", "content": "run the tests"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "Bash", "arguments": "pytest"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "40 passed"},
            {"role": "user", "content": "[iteration cap reached: summarise now]"},
            {"role": "assistant", "content": "That should be fine."}]
    turn = cow.turn_from_history("run the tests", "That should be fine.", hist)
    assert [c.name for c in turn.tools] == ["Bash"] and turn.user == "run the tests"
    assert analyze(turn) == []


def test_no_user_row_assumes_no_tool_traffic():
    """glm53 C1 / flash: history without a user row used to credit every earlier tool call to this turn."""
    hist = [{"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "Bash", "arguments": "ls"}}]}]
    assert cow.turn_from_history("", "x", hist).tools == []


def test_non_string_user_message_is_not_repr_dumped():
    """glm53 D1: a multimodal payload becomes its text, not the repr of a list."""
    t = cow.turn_from_history([{"type": "text", "text": "don't commit yet"}, 42], "Ready to commit.", [])
    assert t.user == "don't commit yet" and analyze(t) == []


def test_only_the_users_earlier_words_count_as_context():
    """ds B8: the agent's own earlier promise is not the user's answer."""
    hist = [{"role": "user", "content": "work on the ticket"},
            {"role": "assistant", "content": "I will close the ticket once the tests pass."},
            {"role": "user", "content": "ok"}, {"role": "assistant", "content": "Should I close the ticket?"}]
    t = cow.turn_from_history("ok", "Should I close the ticket?", hist)
    assert "close" not in t.context and analyze(t) == []


def test_switching_to_observe_drops_a_held_nudge():
    """sol E1."""
    ctx = _setup(Ctx({"cowardice_mode": "nudge"}))
    cow.on_post_llm_call("s1", "run it", "I'll run the tests now.", _history("run it", reply="I'll run the tests now."))
    assert "s1" in cow._pending
    ctx.config["cowardice_mode"] = "observe"
    assert cow.take_nudge("s1") is None


def test_malformed_tool_call_entry_does_not_hide_the_rest():
    """opus low: one bad entry must not drop the turn."""
    hist = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [5, {"id": "a", "function": "oops"},
                                                                 {"id": "b", "function": {"name": "Bash", "arguments": "pytest"}}]},
            {"role": "tool", "tool_call_id": "b", "content": "ok"}]
    t = cow.turn_from_history("go", "That should be fine.", hist)
    assert "Bash" in [c.name for c in t.tools]


def test_slash_accepts_a_non_string():
    assert isinstance(cow.slash(5), str)


def test_catalog_hooks_match_the_manifest():
    """sol G1 / ds A1: the catalog is the pre-install disclosure surface."""
    def listed(path, key):
        txt = path.read_text(encoding="utf-8")
        import re
        m = re.search(rf"{key}:\s*\[([^\]]*)\]", txt)
        return {x.strip() for x in m.group(1).split(",")} if m else None
    cat = listed(REPO / "catalog" / "selenite.yaml", "provides_hooks")
    assert "post_llm_call" in cat
