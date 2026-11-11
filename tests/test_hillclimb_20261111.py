"""Hill-climb 2026-11-11 regressions: credential walls missed by a double-space regex."""
import pytest
from antibeaurocracy_core.classify import classify, WALL

REAL_CREDENTIAL_WALLS = [
    "needs a password",
    "needs a new api key",
    "need new credentials for the registry",
    "needs Ada to enter the production database password",
    "needs Ada to paste the new staging api key here",
    "share the deploy token with the CI runner",
]


@pytest.mark.parametrize("text", REAL_CREDENTIAL_WALLS)
def test_credential_wall_is_recognised(text):
    v = classify(text)
    assert v.cls == WALL, (text, v)


def test_unrelated_need_is_not_a_credential_wall():
    assert classify("needs a rebase before review").cls != WALL


def test_hyphenated_credential_adjective_is_not_a_wall():
    assert classify("need a credential-free desktop").cls != WALL


# --- CLI: empty input and low-confidence verdicts ---------------------------------------------
import argparse, io, json as _json
from antibeaurocracy_core import cli as _cli


def _run(argv, stdin="", monkeypatch=None, capsys=None):
    p = argparse.ArgumentParser(); _cli.add_arguments(p)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    rc = _cli.handle(p.parse_args(argv), settings={})
    return rc, capsys.readouterr()


def test_empty_stdin_is_a_usage_error(monkeypatch, capsys):
    rc, out = _run(["classify"], stdin="  \n", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 2 and out.out == "" and "nothing to classify" in out.err


def test_low_confidence_fake_gives_no_action(monkeypatch, capsys):
    rc, out = _run(["classify", "needs Ada to look at it"], monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0
    if "low confidence" not in out.out:
        pytest.fail(out.out)
    rc, out = _run(["classify", "--json", "needs Ada to look at it"], monkeypatch=monkeypatch, capsys=capsys)
    d = _json.loads(out.out)
    assert d["low_confidence"] is True


def test_wall_is_never_downgraded(monkeypatch, capsys):
    rc, out = _run(["classify", "--json", "needs a password"], monkeypatch=monkeypatch, capsys=capsys)
    d = _json.loads(out.out)
    assert d["cls"] == "WALL" and d["low_confidence"] is False


def test_slash_and_tool_label_low_confidence():
    from antibeaurocracy_core import plugin as _p
    assert "low confidence" in _p.slash("check needs Ada to look at it")
    assert "low confidence" not in _p.slash("check needs a password")
    assert _json.loads(_p.tool_classify({"text": "needs Ada to look at it"}))["low_confidence"] is True
    assert _json.loads(_p.tool_classify({"text": "needs a password"}))["low_confidence"] is False


def test_docs_say_the_desktop_half_starts_off():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert "Capabilities ▸ Plugins" in (root / "README.md").read_text()
    assert "Capabilities > Plugins" in (root / "install.sh").read_text()


# --- Calm recall: common "I already said this" phrasings ------------------------------------
from conftest import signals as _signals  # noqa: E402  (loaded under its plugin name; no sys.path or sys.modules leak)


@pytest.mark.parametrize("text", [
    "why is this STILL broken?? i told you three times",
    "how many times do I have to say it",
    "I already told you, use the other port",
    "it's still broken",
])
def test_repeat_work_phrasings_count(text):
    assert "repeat_work" in _signals.overload(text)


@pytest.mark.parametrize("text", [
    "I told you about the meeting on Friday",
    "how many times should the job retry?",
    "the old build was broken, the new one works",
])
def test_neutral_phrasings_do_not_count(text):
    assert "repeat_work" not in _signals.overload(text)


# S-U1: with nothing blocked, the headline must not print "0 of the blocked (0%)".
def test_headline_zero_blocked_is_plain():
    from antibeaurocracy_core import audit
    s = {"blocked": 0, "running": 3, "fake": 0, "fake_share": 0.0}
    h = audit.headline(s)
    assert "0 of the blocked" not in h and "(0%)" not in h
    assert "Nothing blocked" in h and "3 running" in h


def test_headline_zero_blocked_still_reports_board_errors():
    from antibeaurocracy_core import audit
    s = {"blocked": 0, "running": 0, "fake": 0, "fake_share": 0.0, "errors": ["x"]}
    assert "could not be read" in audit.headline(s)


def test_headline_nonzero_unchanged():
    from antibeaurocracy_core import audit
    s = {"blocked": 4, "running": 2, "fake": 1, "fake_share": 0.25}
    assert audit.headline(s).startswith("4 blocked vs 2 running. 1 of the blocked (25%)")
