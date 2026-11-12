"""Gap regressions from the 2026-11-11 dogfood pass on 0.5.0 (on top of round two).

Credential walls were sorted as stale waits, real waits on the live board were
called fake gates (one with advice to dispatch a card marked "do not dispatch"),
and the CLI judged empty input. The board fixtures paraphrase real block
reasons; no card text is copied.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from antibeaurocracy_core import DEPENDENCY, FAKE, WALL, audit, classify
from antibeaurocracy_core.classify import ACTIONS, PARKING

ROOT = Path(__file__).resolve().parent.parent

CREDENTIAL_ASKS = [
    "Need the production database password",
    "Blocked on credentials for the staging server",
    "Need an API key for the OpenAI account",
    "Waiting for the GitHub token to be rotated",
    "Need the SSH key for the build host",
    "Need the secret for the webhook",
    "Need someone to log in to the AWS console",
    "Waiting for access to the private repo",
    "Need the passphrase for the signing key",
    "Need the OAuth client secret",
    "Needs 2FA code from the owner",
]


@pytest.mark.parametrize("text", CREDENTIAL_ASKS)
def test_credential_asks_are_walls(text):
    v = classify(text)
    assert (v.cls, v.subtype, v.confidence) == (WALL, "credentials", 0.9)


@pytest.mark.parametrize("text", [
    "No credentials required; awaiting relay to create the PR",
    "no secrets in the diff",
    "credential-free path works, waiting on review",
])
def test_negated_or_hyphenated_credentials_are_not_walls(text):
    assert classify(text).cls != WALL


def test_a_failing_login_test_is_not_a_credential_wall():
    assert classify("Users cannot log in to the app: test fails").cls != WALL


def test_work_running_outside_the_board_is_not_parked():
    v = classify("Executed by another harness outside the gateway in its own worktree. Do not dispatch.")
    assert (v.cls, v.confidence) == (DEPENDENCY, 0.7)
    assert v.action.startswith("Leave it.")


def test_a_supervisor_owning_the_repair_is_worked_elsewhere():
    v = classify("Owner note: the Claude Code supervisor owns this repair now; leave the card alone.")
    assert (v.cls, v.confidence) == (DEPENDENCY, 0.7)


@pytest.mark.parametrize("text", [
    "Created blocked so they do not auto-dispatch; throttled to max 2 in progress across a queue of 98",
    "Waits for queue capacity: max_in_progress is 2",
    "Throttled at 3 running",
])
def test_a_deliberate_throttle_is_capacity_not_ceremony(text):
    v = classify(text)
    assert (v.cls, v.confidence) == (DEPENDENCY, 0.7)
    assert v.action.startswith("Leave it.")


def test_owner_decisions_about_public_exposure_are_a_publish_wall():
    v = classify("Blocks on owner decisions it cannot make: NEVER merge as-is, public exposure risk")
    assert (v.cls, v.subtype) == (WALL, "publish")


def test_plain_parking_still_flags_and_never_says_dispatch_first():
    v = classify("PARKED. do not dispatch")
    assert (v.cls, v.label) == (FAKE, PARKING)
    assert not ACTIONS[PARKING].lower().startswith("dispatch")
    assert "owner" in ACTIONS[PARKING] and "expiry" in ACTIONS[PARKING]


def _cli(*args, stdin=""):
    # PYTHONUTF8 keeps argv/stdio UTF-8 in the child even under a C or non-UTF-8 locale.
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run([sys.executable, "-m", "antibeaurocracy_core.cli", *args], cwd=ROOT, env=env,
                          input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=60)


@pytest.mark.parametrize("args,stdin", [(("classify", ""), ""), (("classify", "   "), ""),
                                         (("classify", "👍"), ""), (("classify",), "")])
def test_cli_refuses_to_judge_no_reason(args, stdin):
    try:
        [a.encode(sys.getfilesystemencoding()) for a in args]
    except UnicodeEncodeError:
        pytest.skip("this host's filesystem encoding cannot pass the argument as argv")
    r = _cli(*args, stdin=stdin)
    assert r.returncode == 2
    assert r.stderr.startswith("antibeaurocracy: nothing to classify")
    assert r.stdout == ""


def test_cli_version():
    r = _cli("--version")
    from antibeaurocracy_core import __version__
    assert (r.returncode, r.stdout.strip()) == (0, f"antibeaurocracy {__version__}")


def test_headline_with_no_boards_says_so():
    s = audit.summarize([])
    assert s["boards"] == 0
    assert audit.headline(s).startswith("No boards found.")


def test_headline_with_nothing_blocked_skips_the_percentage():
    s = audit.summarize([{"board": "b", "statuses": {"running": 3}, "blocked": []}])
    assert audit.headline(s) == "Nothing blocked; 3 running."
    assert audit.counts_only(s)["boards"] == 1


def test_web_tab_has_cleanse_evolve_and_readable_gate_names():
    js = (ROOT / "dashboard" / "dist" / "index.js").read_text(encoding="utf-8")
    assert '"/cleanse"' in js and '"/proposal"' in js
    assert 'title: g.key' in js and 'overflowWrap: "anywhere"' in js
    assert '" Calm trigger"' in js


def test_ci_and_readme_install_the_same_test_requirements():
    reqs = (ROOT / "requirements-test.txt").read_text(encoding="utf-8").split()
    assert reqs == ["pytest==9.2.0", "fastapi==0.162.5", "starlette==1.7.0", "httpx==0.28.1"]
    for f in (".forgejo/workflows/ci.yml", ".github/workflows/validate.yml", "README.md"):
        assert "-r requirements-test.txt" in (ROOT / f).read_text(encoding="utf-8"), f
