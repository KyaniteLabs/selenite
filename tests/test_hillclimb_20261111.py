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
