"""Regression tests for the second-roast findings: each one pins a failure
the roast reproduced, so it cannot come back quietly."""
import json
import subprocess
import sys
import time

import pytest
from conftest import HOME, REPO, cleanse, evolve, ledger


def _fake_ledger(rows):
    d = HOME / ".hermes/plugin-data/antibeaurocracy"
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def _fake_count():
    fs = [f for f in cleanse.run()["findings"] if f["stone"] == "fake-gate"]
    return fs[0]["interruptions"] if fs else 0


def test_a_card_counts_by_its_latest_event():
    now = time.time()
    _fake_ledger([
        {"ts": now, "event": "block_attempt", "task": "t_1", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "asked", "task": "t_1", "verdict": "F1-ack"},          # Selenite asked: cleared
        {"ts": now, "event": "block_attempt", "task": "t_2", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "fail_open", "task": "t_2", "verdict": "F1-ack"},      # fail-open keeps it
        {"ts": now, "event": "block_attempt", "task": "t_3", "verdict": "F1-ack", "conf": 0.8},
        {"ts": now + 1, "event": "declared", "task": "t_3", "declared": "needs_input"},  # Hermes's own kind
        {"ts": now, "event": "blocked_observed", "task": "t_4", "verdict": "F2-relay", "conf": 0.9,
         "declared": "capability"},                                                      # declared: never fake
        {"ts": now, "event": "block_attempt", "task": "t_5", "verdict": "F1-ack", "conf": True},  # bool is not a score
    ])
    assert _fake_count() == 1  # only t_2


def test_a_later_fake_block_reopens_a_cleared_card():
    now = time.time()
    _fake_ledger([
        {"ts": now, "event": "asked", "task": "t_1", "verdict": "F1-ack"},
        {"ts": now + 1, "event": "blocked_observed", "task": "t_1", "verdict": "F1-ack", "conf": 0.8},
    ])
    assert _fake_count() == 1


def test_runbooks_flag_steps_not_mentions(tmp_path):
    rb = tmp_path / "RUNBOOK.md"
    rb.write_text("This flow is friction-free.\nThe app supports 2FA and OTP codes.\nFrictionless setup.\n")
    assert not [f for f in cleanse.run(paths=[rb])["findings"] if f["stone"] == "runbook"]
    rb.write_text("Manual step: you need to paste the token.\n")
    assert [f for f in cleanse.run(paths=[rb])["findings"] if f["stone"] == "runbook"]


@pytest.mark.parametrize("bad", ["not json", "[]", '{"silent": []}', '{"last": "x", "silent": {}}',
                                 '{"last": 0, "silent": {"curse": "lots"}}', '{"last": 0, "silent": {"curse": null}}'])
def test_a_damaged_evolve_state_resets_instead_of_crashing(bad):
    ledger.STATE.mkdir(mode=0o700)
    (ledger.STATE / "evolve-state.json").write_text(bad)
    assert evolve.build(30).exists()
    st = json.loads((ledger.STATE / "evolve-state.json").read_text(encoding="utf-8"))
    assert isinstance(st["silent"], dict)


def test_silence_only_counts_what_was_measured(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(evolve.time, "time", lambda: clock[0])
    silent = lambda: json.loads((ledger.STATE / "evolve-state.json").read_text(encoding="utf-8"))["silent"]  # noqa: E731
    evolve.build(30)  # no report, no Calm rows: nothing measured
    assert not any(silent().values())
    ledger.add("calm", "curse")
    clock[0] += 2 * 86400
    evolve.build(30)  # Calm rows measure the Calm categories only
    s = silent()
    assert s["curse"] == 0 and s["over_asking"] == 1 and s["human_gate"] == 0
    f = ledger.STATE / "report-a.json"
    f.write_text(json.dumps({"counts": {"curse": 1}}))
    clock[0] += 2 * 86400
    evolve.build(30)  # a new miner report measures everything
    assert silent()["human_gate"] == 1
    clock[0] += 2 * 86400
    evolve.build(30)  # the same report again is not a new measurement
    assert silent()["human_gate"] == 1


def test_evolve_redacts_notes_and_leaves_the_pr_to_the_human():
    ledger.add("miss", "x", note="mail a.b@example.com about it")
    ledger.add("fp", "y", note="token ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    text = evolve.build(30).read_text(encoding="utf-8")
    assert "@example.com" not in text and "ghp_" not in text
    assert "Opening a PR is the human's decision" in text and "one PR" not in text


@pytest.mark.parametrize("raw,gone", [
    ("mail me at a.b@example.com", "a.b@example.com"),
    ("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
    ("password=hunter2hunter2", "hunter2hunter2"),
    ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
    ("sk-proj-abc123def456ghi789", "sk-proj-abc123def456ghi789"),
    ("glpat-abcdefghij0123456789", "glpat-abcdefghij0123456789"),
    ("https://user:pass@host/x", "user:pass"),
    ("host 203.0.113.7", "203.0.113.7"),
    ("v6 2001:db8::1", "2001:db8::1"),
    ("password hunter2secret", "hunter2secret"),
    ("passphrase: s3cretphrase", "s3cretphrase"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJB\n-----END RSA PRIVATE KEY-----", "MIIBOgIBAAJB"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "BEGIN OPENSSH PRIVATE KEY"),
    ("jwt eyJhbGc.eyJzdWI.sig", "eyJhbGc.eyJzdWI.sig"),
    ("card 4111 1111 1111 1111", "4111 1111 1111 1111"),
])
def test_ledger_redacts_secrets_before_writing(raw, gone):
    ledger.add("miss", "k", note=raw)
    row = [r for r in ledger.rows() if r["kind"] == "miss"][-1]
    assert gone not in row["note"]


def test_ledger_add_does_not_persist_nested_credential_leaves():
    ledger.add("miss", "nested-auth", note='{"auth": {"user": "bob", "bearer": "R8_NESTED_SECRET"}}')
    row = [r for r in ledger.rows() if r["key"] == "nested-auth"][-1]
    assert "R8_NESTED_SECRET" not in row["note"]


def test_redaction_leaves_plain_words_alone():
    assert ledger.redact("pip install from a lockfile") == "pip install from a lockfile"
    assert ledger.redact("ratio 3:2 at 10:30") == "ratio 3:2 at 10:30"
    assert ledger.redact("password reset flow") == "password reset flow"
    assert ledger.redact("order 12345 at 2026-11-11") == "order 12345 at 2026-11-11"


def test_redaction_keeps_the_auth_scheme_word():
    assert ledger.redact("Authorization: Bearer abcdef0123456789abcdef") == "Authorization: Bearer <token>"


@pytest.mark.parametrize("raw,secret", [
    ("api_key={SYNTH-0006}", "SYNTH-0006"),
    ("token: {SYNTH-0006}", "SYNTH-0006"),
    ("password={{SYNTH-0006}}", "SYNTH-0006"),
    ("password: required-SYNTH-0007", "SYNTH-0007"),
    ('password="required-SYNTH-0007"', "SYNTH-0007"),
    ("password='required SYNTH-0007'", "SYNTH-0007"),
])
def test_redaction_does_not_skip_brace_or_required_prefix_values(raw, secret):
    redacted = ledger.redact(raw)
    assert secret not in redacted
    assert "<secret>" in redacted


def test_redaction_leaves_the_whole_required_value_alone():
    assert ledger.redact("password: required") == "password: required"


def test_oauth_apikey_redaction_consumes_the_credential_and_keeps_following_prose():
    redacted = ledger.redact("oauth: ApiKey synthetic-secret-value remains readable")
    assert redacted == "oauth: <secret> remains readable"


@pytest.mark.parametrize("raw", [
    "oauth=synthetic-secret-value",
    "GITHUB_OAUTH=synthetic-secret-value",
    "authkey=synthetic-secret-value",
    "basicauth: user:synthetic-password",
    "authcode=synthetic-secret-value",
    "preauth_key: synthetic-secret-value",
])
def test_redaction_catches_auth_assignments(raw):
    redacted = ledger.redact(raw)
    assert "synthetic-secret-value" not in redacted
    assert "synthetic-password" not in redacted
    assert "<secret>" in redacted


def test_redaction_keeps_noncard_numbers_and_authority_words():
    text = "deploy at 1731326400000 failed; authority: ceo approved; t_1731326400123"
    assert ledger.redact(text) == text
    assert ledger.redact("card 4111 1111 1111 1111") == "card <card>"


@pytest.mark.parametrize("raw,expected", [
    ('{"password": "S"}', '{"password": "<secret>"}'),
    ('{"password": "don\'t log this"}', '{"password": "<secret>"}'),
    ('{"api_key": "S"}', '{"api_key": "<secret>"}'),
    ("{'password': 'hunter2'}", "{'password': '<secret>'}"),
    ('{"Authorization": "ApiKey S"}', '{"Authorization": "<secret>"}'),
    ('curl -H "Authorization: Digest username=bob, response=S"',
     'curl -H "Authorization: <secret>"'),
    ('curl -H "Authorization: ApiKey S" https://x',
     'curl -H "Authorization: <secret>" https://x'),
    ('sshpass -p S', 'sshpass -p <secret>'),
    ('sshpass -p hunter2', 'sshpass -p <secret>'),
    ('docker login -u bob -p hunter2', 'docker login -u bob -p <secret>'),
    ('mysqldump -u root -phunter2', 'mysqldump -u root -p<secret>'),
    ('curl -sSLu bob:hunter2', 'curl -sSLu <secret>'),
])
def test_redaction_catches_quoted_and_command_credentials(raw, expected):
    assert ledger.redact(raw) == expected


@pytest.mark.parametrize("text,secret", [
    ("mysql --password=FLAG_SECRET db", "FLAG_SECRET"),
    ("psql --password=FLAG_SECRET", "FLAG_SECRET"),
    ("tool --token=FLAG_SECRET", "FLAG_SECRET"),
    ("tool --api-key=FLAG_SECRET", "FLAG_SECRET"),
    ("tool --client-secret=FLAG_SECRET", "FLAG_SECRET"),
    ("gh auth login --with-token=FLAG_SECRET", "FLAG_SECRET"),
    ("java -Dpassword=FLAG_SECRET", "FLAG_SECRET"),
    ("gradle -Ptoken=FLAG_SECRET", "FLAG_SECRET"),
    ("args: [--token=FLAG_SECRET]", "FLAG_SECRET"),
    ("restic --password-command='echo FLAG_SECRET'", "FLAG_SECRET"),
    ("cli -password=FLAG_SECRET", "FLAG_SECRET"),
    ("wget --http-password=FLAG_SECRET", "FLAG_SECRET"),
    ("--secret: FLAG_SECRET", "FLAG_SECRET"),
    (r'{"password": "before \"FLAG_SECRET\" after"}', "FLAG_SECRET"),
    ('Authorization: Digest username="bob", realm="r", nonce="n", uri="/", response="FLAG_SECRET"',
     "FLAG_SECRET"),
    ("curl -sSLubob:FLAG_SECRET", "FLAG_SECRET"),
    ('{"auth": {"password": "FLAG_SECRET"}}', "FLAG_SECRET"),
    ("cookies = {'sid': 'FLAG_SECRET'}", "FLAG_SECRET"),
    ("curl --proxy-user bob:FLAG_SECRET", "FLAG_SECRET"),
    ("docker login -u bob -pFLAG_SECRET", "FLAG_SECRET"),
    ("sshpass -pFLAG_SECRET", "FLAG_SECRET"),
    ("mariadb -pFLAG_SECRET", "FLAG_SECRET"),
    ("redis-cli -a FLAG_SECRET", "FLAG_SECRET"),
    ("podman login -p FLAG_SECRET", "FLAG_SECRET"),
    ("SSHPASS=FLAG_SECRET", "FLAG_SECRET"),
    ("token: |\n  FLAG_SECRET", "FLAG_SECRET"),
    ("client_secret: |\n  FLAG_SECRET", "FLAG_SECRET"),
    ("db_password: >-\n  FLAG_SECRET", "FLAG_SECRET"),
    ("access_token: |\n    FLAG_SECRET", "FLAG_SECRET"),
    ("AWS4-HMAC-SHA256 Signature=FLAG_SECRET", "FLAG_SECRET"),
    ('Authorization: Digest username="bob",realm="r",nonce="n",uri="/",response="FLAG_SECRET"',
     "FLAG_SECRET"),
    ("cookies = {'site': {'sid': 'FLAG_SECRET'}}", "FLAG_SECRET"),
    ('{"credentials": {"user": "bob", "pw": "FLAG_SECRET"}}', "FLAG_SECRET"),
    ('{"auth": {"user": "bob", "bearer": "FLAG_SECRET"}}', "FLAG_SECRET"),
    ("curl -b sid=FLAG_SECRET", "FLAG_SECRET"),
    ("redis-cli --pass FLAG_SECRET", "FLAG_SECRET"),
    ("mysqladmin -pFLAG_SECRET", "FLAG_SECRET"),
    ("http -a bob:FLAG_SECRET", "FLAG_SECRET"),
    ("the password is FLAG_SECRET", "FLAG_SECRET"),
    ("pw=FLAG_SECRET", "FLAG_SECRET"),
])
def test_redaction_catches_round_seven_secret_shapes(text, secret):
    assert secret not in ledger.redact(text)


@pytest.mark.parametrize("text", [
    "tests passed: 12",
    "passed=40 failed=2",
    "bypass: true",
    "pass_rate: 98%",
    "compass: north",
    "encompass=all",
    "pass: ok",
    "pass=true",
    "smoke pass: yes",
    "first-pass: done",
    "2nd_pass=started",
    "signature: Ada",
    "signature: Ada Lovelace",
    "signature: please sign the contract",
])
def test_redaction_leaves_noncredential_pass_and_signature_words(text):
    assert ledger.redact(text) == text


def test_redaction_still_catches_a_long_signature_value():
    assert "abcdef0123456789" not in ledger.redact("signature: abcdef0123456789")


def test_redaction_consumes_a_quoted_secret_cut_by_its_safety_limit():
    text = 'password="first ' + "x " * 1940 + "R8_SYNTHETIC" + "z " * 100 + '"'
    assert "R8_SYNTHETIC" not in ledger.redact(text)


def test_redaction_keeps_mysql_ports_prompt_form_and_token_limits():
    port = "mysql -h db1 -P 3306 -u root mydb"
    prompt = "mysql -u root -p mydb"
    assert ledger.redact(port) == port
    assert ledger.redact(prompt) == prompt
    for command in ("Mysql -u root -pFLAG_SECRET", "MYSQL -u root -pFLAG_SECRET"):
        assert "FLAG_SECRET" not in ledger.redact(command)
    uppercase_port = "MYSQL -u root -P 3306 db"
    assert ledger.redact(uppercase_port) == uppercase_port
    assert ledger.redact("set max_tokens=4000") == "set max_tokens=4000"
    for text in (
        "num_tokens=4000", "total_tokens=4000", "min_tokens_in_prompt=4000",
        "max_tokens_to_sample=4000", "tokenizer=cl100k_base", "password: required",
        "--max_tokens_to_sample=4000",
    ):
        assert ledger.redact(text) == text


@pytest.mark.parametrize("payload", [
    pytest.param("auth" + "_x" * 200, id="auth-segments"),
    pytest.param("token-" * 600, id="repeated-token"),
    pytest.param("--" + "token" * 600 + "=S", id="flag-key"),
])
def test_redaction_handles_adversarial_key_names_promptly(payload):
    code = (
        "import sys; sys.path.insert(0, 'skills/frictionless/scripts'); "
        "import ledger; ledger.redact(sys.argv[1])"
    )
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, payload], cwd=REPO,
            capture_output=True, text=True, timeout=1.5, check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("redaction exceeded 1.5 seconds on an adversarial key name")
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 1.5


# Fable roast lows: S1 quoted text, S4 active home only, S5 deleted cards.

def test_calm_ignores_quoted_fenced_and_pasted_text():
    from conftest import signals
    assert signals.overload('the log said "wtf is this" and "ugh, annoying"') == []
    assert signals.overload("> wtf\n> this is annoying\nhere is the log") == []
    assert signals.overload("```\nshit happens, frustrating\n```\nsee above") == []
    assert set(signals.overload("wtf, this is annoying")) == {"curse", "frustration"}


def test_an_inch_mark_does_not_quote_the_following_complaint():
    from conftest import signals
    text = 'my 27" monitor is broken wtf, stop asking me, this "fix" is so frustrating'
    assert set(signals.overload(text)) == {"frustration", "curse", "over_asking"}


def test_audit_defaults_to_the_active_hermes_home(tmp_path, monkeypatch):
    from antibeaurocracy_core import audit
    for name in (".hermes", ".hermes-org", ".hermes-old"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(audit.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert audit.default_roots() == [tmp_path / ".hermes"]
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes-org"))
    assert audit.default_roots() == [tmp_path / ".hermes-org"]
    assert set(audit.default_roots(all_homes=True)) == {tmp_path / n for n in (".hermes", ".hermes-org", ".hermes-old")}


def test_deleted_cards_read_as_missing_only_when_every_board_read(tmp_path):
    import sqlite3
    from antibeaurocracy_core import audit
    db = tmp_path / "kanban.db"
    con = sqlite3.connect(db)
    con.execute("create table tasks (id text primary key, status text)")
    con.execute("insert into tasks values ('t_1', 'blocked')")
    con.commit(); con.close()
    assert audit.card_statuses(["t_1", "t_x"], [db], mark_missing=True) == {"t_1": "blocked", "t_x": audit.MISSING}
    assert audit.card_statuses(["t_1", "t_x"], [db]) == {"t_1": "blocked"}
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database at all, just bytes" * 10)
    assert audit.card_statuses(["t_1", "t_x"], [db, bad], mark_missing=True) == {"t_1": "blocked"}


@pytest.mark.parametrize("raw,secret", [
    ("dbpass=R9_SECRET", "R9_SECRET"),
    ("DBPASS=R9_SECRET", "R9_SECRET"),
    ("smtppass: R9_SECRET", "R9_SECRET"),
    ("adminpw=R9_SECRET", "R9_SECRET"),
    ("rootpw: R9_SECRET", "R9_SECRET"),
    ("rootpw --plaintext R9_SECRET", "R9_SECRET"),
    ("--pw R9_SECRET", "R9_SECRET"),
    ("-pw R9_SECRET", "R9_SECRET"),
    ("mypass=R9_SECRET", "R9_SECRET"),
    ("userpass=R9_SECRET", "R9_SECRET"),
    ("wifipass=R9_SECRET", "R9_SECRET"),
    ('{"token": {"access_token": "R9_SECRET"}}', "R9_SECRET"),
    ("db_secrets = {'password': 'R9_SECRET'}", "R9_SECRET"),
    ('export AWS_CREDENTIALS={"secret_access_key": "R9_SECRET"}', "R9_SECRET"),
    ('vault_token: {"client_token": "R9_SECRET"}', "R9_SECRET"),
    ('secrets: {"db": "R9_SECRET"}', "R9_SECRET"),
    ('tokens = {"gh": "R9_SECRET"}', "R9_SECRET"),
    ('auth=("bob", "R9_SECRET")', "R9_SECRET"),
    ('password: [ "R9_SECRET" ]', "R9_SECRET"),
    ('env:\n  - name: DB_PASSWORD\n    value: R9_SECRET', "R9_SECRET"),
])
def test_round_nine_secret_assignments_never_reach_ledger_rows(raw, secret):
    assert secret not in ledger.redact(raw)
    ledger.add("miss", "round-nine-secret", note=raw)
    row = [r for r in ledger.rows() if r["key"] == "round-nine-secret"][-1]
    assert secret not in row["note"]


@pytest.mark.parametrize("raw", [
    'client_secret: | # from the vault\n  R9_BLOCK_SECRET',
    'db_password: |2\n  R9_BLOCK_SECRET',
    'access_token: |\n  first line\n\n  R9_BLOCK_SECRET',
    'password: "first\n  R9_QUOTED_SECRET"',
    "password: 'first\n  R9_SINGLE_QUOTED_SECRET'",
])
def test_round_nine_multiline_yaml_values_are_removed_before_persistence(raw):
    for secret in ("R9_BLOCK_SECRET", "R9_QUOTED_SECRET", "R9_SINGLE_QUOTED_SECRET"):
        assert secret not in ledger.redact(raw)
    ledger.add("miss", "round-nine-multiline", note=raw)
    row = [r for r in ledger.rows() if r["key"] == "round-nine-multiline"][-1]
    assert not any(secret in row["note"] for secret in (
        "R9_BLOCK_SECRET", "R9_QUOTED_SECRET", "R9_SINGLE_QUOTED_SECRET"
    ))


@pytest.mark.parametrize("raw,secret", [
    ("X-Hub-Signature: sha256=R9_SIG", "R9_SIG"),
    ("x-signature: R9_SIG", "R9_SIG"),
    ("signature: v1,R9_SIG", "R9_SIG"),
    ("Authorization: Digest username=bob; realm=r;\nnonce=n;\nresponse=R9_DIGEST", "R9_DIGEST"),
    ('Authorization: Digest username="bob",\n  response="R9_DIGEST"', "R9_DIGEST"),
    ("Authorization: Digest username=bob\nrealm=r\nresponse=R9_DIGEST", "R9_DIGEST"),
    ("curl -sb sid=R9_COOKIE", "R9_COOKIE"),
    ("https -a bob:R9_HTTP_AUTH", "R9_HTTP_AUTH"),
    ("http --auth bob:R9_HTTP_AUTH", "R9_HTTP_AUTH"),
])
def test_round_nine_signature_digest_and_command_credentials_are_redacted(raw, secret):
    assert secret not in ledger.redact(raw)


@pytest.mark.parametrize("raw", [
    "signature=required",
    "signature: Ada",
    "password is required",
    "Password is required for SSO",
    "password is wrong",
    "the password is not set",
    "password is expired",
    "secret is required",
    "redis-cli --passive",
    "http check -a failed",
    "the http check -a failed",
    "Use auth: [the docs](url)",
])
def test_round_nine_benign_auth_words_and_prose_are_preserved(raw):
    assert ledger.redact(raw) == raw


@pytest.mark.parametrize("raw,expected_prefix", [
    ("the password is: R9_SECRET", "the password is: <secret>"),
    ("password is now R9_SECRET", "password is now <secret>"),
    ("password was R9_SECRET", "password was <secret>"),
    ("password is set to R9_SECRET", "password is set to <secret>"),
    ("secret is R9_SECRET", "secret is <secret>"),
    ("token is R9_SECRET", "token is <secret>"),
    ("pwd is R9_SECRET", "pwd is <secret>"),
    ("pw is R9_SECRET", "pw is <secret>"),
    ("api key is R9_SECRET", "api key is <secret>"),
    ("auth: [WIP} fix the login flow", 'auth: "<secret>" fix the login flow'),
    ("auth: { follow-up note", 'auth: "<secret>" follow-up note'),
])
def test_round_nine_auth_redaction_preserves_neighboring_prose(raw, expected_prefix):
    redacted = ledger.redact(raw)
    assert expected_prefix in redacted
    assert "R9_SECRET" not in redacted


@pytest.mark.parametrize("raw", [
    "bypass: true",
    "bypass=R9_SECRET",
    "compass: north",
    "surpass=the limit",
])
def test_run_together_pass_rule_does_not_redact_ordinary_words(raw):
    assert ledger.redact(raw) == raw


def test_rootpw_plaintext_redacts_only_the_password_value():
    assert ledger.redact("rootpw --plaintext R9_SECRET") == "rootpw --plaintext <secret>"
