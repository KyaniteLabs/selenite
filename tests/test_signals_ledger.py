import json
import os
import stat
import subprocess
import sys
import time

import pytest

from conftest import ledger, signals


@pytest.mark.parametrize("text", [
    "I cannot take a screenshot of the robot here, it is not possible today",
    "keep going",
    "damn, works great",
    "Please add a dot and a lot of hot spots to the plot",
    "Run the build for 10000 iterations and report back please",
    "teh",
])
def test_ordinary_prose_is_not_overload(text):
    assert signals.overload(text) == []


@pytest.mark.parametrize("text,expected", [
    ("wtf why did you stop", {"curse", "stopping_short"}),
    ("just do it, stop asking", {"over_asking"}),
    ("teh thing adn the other jsut broke again for real now", {"typo_burst"}),
])
def test_real_overload(text, expected):
    assert set(signals.overload(text)) == expected


@pytest.mark.parametrize("text", [
    "fix teh buidl pls its broekn agian",
    "teh buidl is broekn agian",
    "fix the buidl pls its broekn agian",
])
def test_short_typo_bursts_are_detected(text):
    assert "typo_burst" in signals.overload(text)


@pytest.mark.parametrize("text", [
    "fix the build pls",
    "fix the build pls it is broken again",
    "fix teh build pls",
    "check teh_buidl and broekn_agian then run the build pls",
    "check teh-buidl-broekn-agian then run the build pls",
    "check https://example.test/teh/buidl/broekn/agian then run the build pls",
    "check /tmp/teh/buidl/broekn/agian then run the build pls",
    r"check C:\teh\buidl\broekn\agian then run the build pls",
    "check teh.py buidl.py broekn.py agian.py and run the build pls",
    "check `teh buidl broekn agian` then run the build pls",
])
def test_terse_prose_and_technical_tokens_are_not_typo_bursts(text):
    assert "typo_burst" not in signals.overload(text)


def test_harness_text_is_ignored():
    assert signals.overload("<system-reminder>wtf just do it</system-reminder>") == []


def test_quoted_line_does_not_hide_following_own_words():
    text = "> A previous neutral message\nwtf this is frustrating, stop asking"
    assert set(signals.overload(text)) == {"over_asking", "curse", "frustration"}


def test_two_signal_rule():
    assert signals.calm_due(["curse"], previous_had_reason=False) is False
    assert signals.calm_due(["curse", "over_asking"], previous_had_reason=False) is True
    assert signals.calm_due(["curse", "curse"], previous_had_reason=False) is False
    assert signals.calm_due(["curse"], previous_had_reason=True) is True
    assert signals.calm_due([], previous_had_reason=True) is False


def test_ledger_permissions_and_no_host():
    ledger.add("gate", "gh-login", "n")
    assert stat.S_IMODE(os.stat(ledger.STATE).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(ledger.LEDGER).st_mode) == 0o600
    row = json.loads(ledger.LEDGER.read_text(encoding="utf-8").splitlines()[0])
    assert set(row) == {"ts", "kind", "key", "note", "agent"}


def test_ledger_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ledger.add("nope", "x")


def test_malformed_lines_skipped():
    ledger.add("gate", "k")
    with ledger.LEDGER.open("a") as f:
        f.write('not json\n5\n[]\n{"kind":1,"key":"x","ts":1}\n{"kind":"gate","key":"k"}\n'
                '{"kind":"gate","key":"k","ts":"soon"}\n{"kind":"gate","key":"k","ts":true}\n\x00garbage\n')
    assert [r["key"] for r in ledger.rows()] == ["k"]


def test_fix_order():
    ledger.add("gate", "a"); time.sleep(0.01)
    ledger.add("fix", "a")
    assert "a" in ledger.fixed_keys()
    time.sleep(0.01); ledger.add("gate", "a")
    assert "a" not in ledger.fixed_keys()
    time.sleep(0.01); ledger.add("fix", "a"); time.sleep(0.01); ledger.add("reopen", "a")
    assert "a" not in ledger.fixed_keys()


@pytest.mark.parametrize("text", [
    "authorization: ApiKey abcdef0123456789",
    "authorization: Digest username=private, realm=internal",
    "oauth: Bearer abc.def.ghi",
    "authorization: scheme-with-arbitrary-format secret-value",
])
def test_authorization_headers_redact_the_complete_value(text):
    redacted = ledger.redact(text)
    assert "abcdef0123456789" not in redacted
    assert "username=private" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "secret-value" not in redacted


def test_authorization_redaction_stops_at_the_end_of_the_header_line():
    redacted = ledger.redact("authorization: scheme-with-arbitrary-format secret-value\nDeployment proceeds")
    assert "secret-value" not in redacted
    assert "Deployment proceeds" in redacted


@pytest.mark.parametrize("text,suffix", [
    ("oauth: fails on login. Then the deploy step broke", "Then the deploy step broke"),
    ("Authorization: header missing in request; retry later",
     "in request; retry later"),
    ("OAuth = broken since Monday, see card t_12", "since Monday, see card t_12"),
])
def test_authorization_redaction_only_consumes_the_scheme_and_one_value(text, suffix):
    redacted = ledger.redact(text)
    assert "<secret>" in redacted
    assert suffix in redacted


@pytest.mark.parametrize("text,secret", [
    ("private_key=short-secret", "short-secret"),
    ("credential: short-secret", "short-secret"),
    ("cookie=session-value", "session-value"),
    ("sessionid=short-secret", "short-secret"),
    ("curl -u user:pass https://example.test", "user:pass"),
])
def test_common_secret_fields_and_curl_credentials_are_redacted(text, secret):
    assert secret not in ledger.redact(text)


@pytest.mark.parametrize("text,secret", [
    ("curl --user bob:hunter2 https://x", "bob:hunter2"),
    ("curl -ubob:hunter2 https://x", "bob:hunter2"),
    ("mysql -u root -phunter2 db", "hunter2"),
])
def test_attached_and_mysql_command_credentials_are_redacted(text, secret):
    assert secret not in ledger.redact(text)


def test_curl_cookie_header_redaction_preserves_shell_quotes():
    redacted = ledger.redact("curl -H 'Cookie: sid=abc123' https://x")
    assert "abc123" not in redacted
    assert redacted.count("'") == 2


def test_digest_fields_without_spaces_are_redacted_as_one_authorization_value():
    raw = 'Authorization: Digest username="bob",realm="r",nonce="n",uri="/",response="R8_SYNTHETIC"'
    redacted = ledger.redact(raw)
    assert "R8_SYNTHETIC" not in redacted
    assert "response=" not in redacted


def test_curl_cookie_jar_path_is_not_redacted_as_cookie_data():
    text = "curl -b cookiejar.txt https://example.test"
    assert ledger.redact(text) == text


@pytest.mark.parametrize("text", [
    "ran curl" + " " * 24 + "x",
    "ran curl" + " " * 26 + "x",
    "curl https://example.com/api \\\n" + " " * 24 + "--data @body.json",
    "curl \\\n"
    "    --silent \\\n"
    "    --show-error \\\n"
    "    --location \\\n"
    "    --request POST \\\n"
    "    --header 'Accept: application/json' \\\n"
    "    --data @body.json https://example.com/api?q=" + "x" * 100,
])
def test_curl_redaction_finishes_quickly_on_noncredential_commands(text):
    script = ("import sys; sys.path.insert(0, 'skills/frictionless/scripts'); "
              "import ledger; ledger.redact(sys.argv[1])")
    started = time.monotonic()
    try:
        subprocess.run([sys.executable, "-c", script, text], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=0.45)
    except subprocess.TimeoutExpired:
        pytest.fail("redaction exceeded 0.45 seconds")
    assert time.monotonic() - started < 0.5


def test_rotation_keeps_history_readable(monkeypatch):
    monkeypatch.setattr(ledger, "ROTATE_BYTES", 200)
    for i in range(10):
        ledger.add("gate", f"k{i}")
    assert ledger.ROTATED.exists()
    assert ledger.LEDGER.stat().st_size < 400
    keys = {r["key"] for r in ledger.rows()}
    assert "k9" in keys and len(keys) >= 2


@pytest.mark.parametrize("text", [
    "curl -H 'x' " * 8000,
    "curl 'curl " * 8000,
    "mysql -x " * 8000,
])
def test_redaction_stays_linear_when_text_repeats_command_words(text):
    started = time.monotonic()
    ledger.redact(text)
    assert time.monotonic() - started < 2.0


def test_curl_credential_scan_stops_at_the_end_of_the_command():
    redacted = ledger.redact("curl https://x \\\n  -u bob:hunter2")
    assert "hunter2" not in redacted
    assert ledger.redact("curl https://x\nnext -u keep-me") .endswith("-u keep-me")
