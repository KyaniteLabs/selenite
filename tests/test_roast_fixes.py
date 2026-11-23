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
    "password is stored in 1Password",
    "token: 'required'",
    "auth: {}",
    "secret is required",
    "redis-cli --passive",
    "http check -a failed",
    "the http check -a failed",
])
def test_round_nine_benign_auth_words_and_prose_are_preserved(raw):
    assert ledger.redact(raw) == raw


def test_credential_markdown_links_are_not_exempted_from_redaction():
    assert ledger.redact("Use auth: [the docs](url)") == 'Use auth: "<secret>"'


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
    ("auth: [WIP} fix the login flow", 'auth: "<secret>"'),
    ("auth: { follow-up note", 'auth: "<secret>"'),
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


@pytest.mark.parametrize("raw,secret", [
    ("- password: |\n    R10_BLOCK_SECRET\n", "R10_BLOCK_SECRET"),
    ('"password": |\n  R10_QUOTED_BLOCK_SECRET\n', "R10_QUOTED_BLOCK_SECRET"),
    ("'db_password': >-\n    R10_SINGLE_BLOCK_SECRET\nnext: ok", "R10_SINGLE_BLOCK_SECRET"),
    ("  - password: >\n      first\n      R10_LIST_BLOCK_SECRET\n", "R10_LIST_BLOCK_SECRET"),
    ("token: [x](R10_LINK_SECRET)", "R10_LINK_SECRET"),
    ("password: [link](https://x.test/R10_URL_SECRET)", "R10_URL_SECRET"),
    ("secret: [R10_LABEL_SECRET](y)", "R10_LABEL_SECRET"),
    ('auth: {"k": "R10_UNCLOSED_SECRET"', "R10_UNCLOSED_SECRET"),
    ('credentials: {\n  "arbitrary": ["R10_MULTILINE_CONTAINER_SECRET"]\n}', "R10_MULTILINE_CONTAINER_SECRET"),
    ("credentials: {a: it's, b: R10_APOSTROPHE_SECRET}", "R10_APOSTROPHE_SECRET"),
    ('adminpw: {"arbitrary": "R10_ADMINPW_SECRET"}', "R10_ADMINPW_SECRET"),
    ("password2: R10_PASSWORD2_SECRET", "R10_PASSWORD2_SECRET"),
    ("client_secret_v2: |\n  R10_VERSIONED_SECRET", "R10_VERSIONED_SECRET"),
    ("cookies_list=[R10_COOKIE_LIST_SECRET]", "R10_COOKIE_LIST_SECRET"),
    ("password:\n  R10_NESTED_YAML_SECRET\nnext: ok", "R10_NESTED_YAML_SECRET"),
    ("creds:\n  password: |\n    R10_NESTED_BLOCK_SECRET\n  user: bob", "R10_NESTED_BLOCK_SECRET"),
    ("- token: |\n    R10_LIST_TOKEN_SECRET", "R10_LIST_TOKEN_SECRET"),
    ("redis-cli -aR10_REDIS_SECRET", "R10_REDIS_SECRET"),
    ("redis-cli -aS", "-aS"),
    ("redis-cli -a passphrase ping", "passphrase"),
    ("http -a R10_HTTP_SECRET x", "R10_HTTP_SECRET"),
    ("http -a S x", "-a S"),
    ("passwd not-R10_PASSWD_SECRET", "R10_PASSWD_SECRET"),
    ('pw: "is R10_QUOTED_PW_SECRET"', "R10_QUOTED_PW_SECRET"),
])
def test_round_ten_secret_shapes_are_removed_from_ledger_input(raw, secret):
    redacted = ledger.redact(raw)
    assert secret not in redacted
    assert "<secret>" in redacted


@pytest.mark.parametrize("raw,secret", [
    ("PASS=R10_PASS_SECRET", "R10_PASS_SECRET"),
    ("export DB_PASS=R10_EXPORT_PASS_SECRET", "R10_EXPORT_PASS_SECRET"),
    ("wifi_pass: R10_WIFI_SECRET", "R10_WIFI_SECRET"),
    ("--pass=R10_FLAG_SECRET", "R10_FLAG_SECRET"),
    ("bypass_token=R10_BYPASS_TOKEN_SECRET", "R10_BYPASS_TOKEN_SECRET"),
    ("passport_secret=R10_PASSPORT_SECRET", "R10_PASSPORT_SECRET"),
    ("compass_api_key=R10_COMPASS_KEY_SECRET", "R10_COMPASS_KEY_SECRET"),
    ("surpass_token=R10_SURPASS_SECRET", "R10_SURPASS_SECRET"),
    ("encompass_token=R10_ENCOMPASS_SECRET", "R10_ENCOMPASS_SECRET"),
    ("bypass-secret=R10_BYPASS_SECRET", "R10_BYPASS_SECRET"),
    ("trespass_password=R10_TRESPASS_SECRET", "R10_TRESPASS_SECRET"),
    ("upw_token=R10_UPW_SECRET", "R10_UPW_SECRET"),
    ("pass_secret_key: R10_PASS_KEY_SECRET", "R10_PASS_KEY_SECRET"),
    ("sshpass -p R10_SSHPASS_SECRET ssh host", "R10_SSHPASS_SECRET"),
    ("sshpass=R10_SSHPASS_ENV_SECRET", "R10_SSHPASS_ENV_SECRET"),
    ("password: |\nR10_ROOT_BLOCK_SECRET\nnext: ok", "R10_ROOT_BLOCK_SECRET"),
])
def test_opus_round_ten_redaction_cases(raw, secret):
    assert secret not in ledger.redact(raw)


@pytest.mark.parametrize("raw", [
    "The tests pass 12",
    "pass rate 98%",
    "pass through the proxy",
    "make pass && make deploy",
    "CI will pass once a reviewer approves",
    "first pass review",
    "one more pass needed",
    "should pass after the token refresh",
    "let it pass through the gateway",
    "Checks pass: 3 of 4, waiting on a reviewer.",
    "Ask a reviewer to sign off; the signature requirement is blocking.",
    "rootpw is set in the kickstart; ask a reviewer.",
    "mypw reset needed",
    "token is valid",
    "token was revoked",
    "the token is expired; waiting on a reviewer to rotate it.",
    "password is wrong for the staging db; waiting on a reviewer",
    "password was reset",
    "api key was rotated",
    "pwd is /srv/app",
    "signature: n/a",
    "e-signature: DocuSign",
    "type_signature: Callable",
    "rootpw --lock",
    "- name: TOKEN_TTL\n  value: 3600",
    "- name: AUTH_MODE\n  value: password",
    "- name: PASSWORD_MIN_LENGTH\n  value: 16",
    "- name: COOKIE_DOMAIN\n  value: example.test",
    "tokens: 1200",
    "bypass: true",
    "bypass=R9_SECRET",
    "auth: (see the runbook) blocked on a reviewer for the merge.",
    "token: (none yet) waiting on the vendor.",
    "password is case-sensitive",
    "api key is rate-limited",
    "signature: A",
    "signature: X",
    "signature: v2",
    'signature: "John Smith, CEO"',
    "method_signature: foo(a, b)",
    "redis-cli -audit",
    "redis-cli --pass-through",
    "redis-cli -a",
    "redis-cli --password-file f",
    "pass: 2",
    "pass=3",
    "pass: compile",
    "pass: second",
    "pass: all",
    "pass: 12/12",
    "pass: 100%",
    "pass: green",
    "pass: fail",
    "pass: skipped",
    "auth: [x] done",
    "token: [x] rotated",
    "password: [redacted]",
    "secret: (TBD)",
    "oauth: (not configured)",
])
def test_round_ten_ordinary_pass_words_and_settings_are_preserved(raw):
    assert ledger.redact(raw) == raw


@pytest.mark.parametrize("raw,secret", [
    ("- value: R10_VALUE_FIRST\n  name: DB_PASSWORD", "R10_VALUE_FIRST"),
    ("- name: DB_PASSWORD\n  # comment\n  value: R10_COMMENT_SECRET", "R10_COMMENT_SECRET"),
    ("env:\n- name: DB_PASSWORD\n  value: R10_ENV_SECRET\n- name: MODE\n  value: prod", "R10_ENV_SECRET"),
    ("- name: DB_PASSWORD\n  valueFrom: secretKeyRef\n  value: R10_VALUE_AFTER_FROM", "R10_VALUE_AFTER_FROM"),
    ("- name: DB_PASS\n  value: R10_DB_PASS", "R10_DB_PASS"),
    ("- name: DB_PW\n  value: R10_DB_PW", "R10_DB_PW"),
    ("- {name: DB_PASSWORD, value: R10_INLINE_SECRET}", "R10_INLINE_SECRET"),
    ('{"name": "DB_PASSWORD", "value": "R10_JSON_SECRET"}', "R10_JSON_SECRET"),
    ('- name: DB_PASSWORD\n  value: {key: R10_VALUE_CONTAINER_SECRET}', "R10_VALUE_CONTAINER_SECRET"),
    ('- name: DB_PASSWORD\n  value: "first\n    R10_MULTILINE_QUOTE_SECRET"', "R10_MULTILINE_QUOTE_SECRET"),
    ('- name: DB_PASSWORD\n  value: "first\n    R10_UNTERMINATED_PAIR_SECRET', "R10_UNTERMINATED_PAIR_SECRET"),
    ('- name: DB_PASSWORD\n  value: |\n    R10_BLOCK_VALUE_SECRET', "R10_BLOCK_VALUE_SECRET"),
    ("- key: DB_PASSWORD\n  value: R10_KEY_VALUE_SECRET", "R10_KEY_VALUE_SECRET"),
    ("--set name=DB_PASSWORD --set value=R10_SET_SECRET", "R10_SET_SECRET"),
    ("- name: DB_PASSWORD\n  value: p@ss R10_TRAILING_PAIR_SECRET", "R10_TRAILING_PAIR_SECRET"),
    ("- name: \"API_TOKEN\"\n  value: R10_QUOTED_NAME_SECRET", "R10_QUOTED_NAME_SECRET"),
])
def test_round_ten_kubernetes_name_value_pairs_are_redacted(raw, secret):
    assert secret not in ledger.redact(raw)


def test_round_ten_unterminated_secret_quote_stops_at_the_line_boundary():
    cases = (
        (
            'note: password: "x\nBlocked on a reviewer for the "merge"',
            'note: password: "<secret>"\nBlocked on a reviewer for the "merge"',
        ),
        (
            'password: "x\nBlocked on a reviewer for the "merge"',
            'password: "<secret>"\nBlocked on a reviewer for the "merge"',
        ),
    )
    for raw, expected in cases:
        assert ledger.redact(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (
        'password: "line1\nR10_MULTILINE_SECRET"\nQuestion: keep?',
        'password: "<secret>"\nQuestion: keep?',
    ),
    (
        'password: "a\nb\nc R10_MULTILINE_SECRET"\nQuestion: keep?',
        'password: "<secret>"\nQuestion: keep?',
    ),
])
def test_round_ten_closed_multiline_secret_quotes_are_consumed(raw, expected):
    assert ledger.redact(raw) == expected


def test_round_ten_unterminated_pair_quote_keeps_nonsecret_blocker_text():
    raw = '- name: DB_PASSWORD\n  value: "x\nBlocked on a reviewer for the "merge"\nQuestion: keep?'
    expected = '- name: DB_PASSWORD\n  value: "<secret>"\nBlocked on a reviewer for the "merge"\nQuestion: keep?'
    assert ledger.redact(raw) == expected


def test_round_ten_unclosed_container_redacts_only_to_the_line_boundary():
    raw = 'auth: {"k": "R10_OPEN_CONTAINER_SECRET"\nBlocked on a reviewer for the merge'
    assert ledger.redact(raw) == 'auth: "<secret>"\nBlocked on a reviewer for the merge'


@pytest.mark.parametrize("raw,expected", [
    ("password is currently R10_CURRENT_SECRET", "password is currently <secret>"),
    ("password is\nR10_NEWLINE_SECRET", "password is\n<secret>"),
    ("password changed to R10_CHANGED_SECRET", "password changed to <secret>"),
    ("password is still R10_STILL_SECRET", "password is still <secret>"),
    ("password is actually R10_ACTUALLY_SECRET", "password is actually <secret>"),
    ("password is the following: R10_FOLLOWING_SECRET", "password is the following: <secret>"),
    ("password will be R10_WILL_SECRET", "password will be <secret>"),
    ("password should be R10_SHOULD_SECRET", "password should be <secret>"),
    ("password must be R10_MUST_SECRET", "password must be <secret>"),
    ("password for db is R10_DB_SECRET", "password for db is <secret>"),
    ("password (prod) is R10_PROD_SECRET", "password (prod) is <secret>"),
    ("password is missing; use R10_MISSING_SECRET", "password is missing; use <secret>"),
    ("password is expired, new one R10_EXPIRED_SECRET", "password is expired, new one <secret>"),
    ("token is not set; use R10_TOKEN_SECRET", "token is not set; use <secret>"),
    ("signature: t=1,v1=R10_SIGNATURE_FIELD_SECRET", "signature: t=1,v1=<secret>"),
    ("signature: hmac-sha256 R10_HMAC_SECRET", "signature: hmac-sha256 <secret>"),
    ("signature: HMAC R10_HMAC_FIELD_SECRET", "signature: HMAC <secret>"),
    ("token: Bearer R10_BEARER_SECRET", "token: Bearer <secret>"),
    ("auth_token: Bearer R10_AUTH_TOKEN_SECRET", "auth_token: Bearer <secret>"),
    ("oauth: Bearer R10_OAUTH_BEARER_SECRET", "oauth: Bearer <secret>"),
    ("pass: 1 of 3 checks R10_PASS_TAIL_SECRET", "pass: 1 of 3 checks <secret>"),
    ("token: a;R10_TRAILING_SECRET", "token: a;<secret>"),
    ("token: a|R10_PIPE_SECRET", "token: a|<secret>"),
    ("pass=$S", "pass=<secret>"),
    ('password is "my R10_QUOTED_PROSE_SECRET"', 'password is "<secret>"'),
    ("password: is R10_ASSIGNED_SECRET", "password: is <secret>"),
    ("pw: now R10_PW_SECRET", "pw: now <secret>"),
    ("pass R10_PASS_SECRET", "pass <secret>"),
    ('dbpass "a b R10_DBPASS_SECRET"', 'dbpass "<secret>"'),
    ("--pass R10_FLAG_SECRET", "--pass <secret>"),
    ("-pw R10_FLAG_PW_SECRET", "-pw <secret>"),
    ("xh -a bob:R10_XH_SECRET", "xh -a bob:<secret>"),
    ("http -a bob:password x", "http -a bob:<secret> x"),
    ("redis-cli -u redis://:R10_URI_SECRET@host", "redis-cli -u redis://<cred>@host"),
])
def test_round_ten_credential_values_are_redacted_without_damaging_neighboring_prose(raw, expected):
    assert ledger.redact(raw) == expected


@pytest.mark.parametrize("raw,secret", [
    ("x-hub-signature-256: sha256=R10_HUB_SECRET", "R10_HUB_SECRET"),
    ("Stripe-Signature: t=123,v1=R10_STRIPE_SECRET", "R10_STRIPE_SECRET"),
    ("Authorization: Hawk id=\"a\", mac=\"R10_HAWK_SECRET\"", "R10_HAWK_SECRET"),
])
def test_round_ten_signature_and_authorization_headers_are_redacted(raw, secret):
    assert secret not in ledger.redact(raw)


@pytest.mark.parametrize("raw,expected", [
    ("sig=hunter2ZZ9", "sig=<secret>"),
    ("&sig=hunter2ZZ9", "&sig=<secret>"),
    ("X-Hmac: hunter2ZZ9", "X-Hmac: <secret>"),
    ("digest: hunter2ZZ9", "digest: <secret>"),
    ('password="required" continue with SYNTH_R9_SECRET',
     'password="required" continue with <secret>'),
    ('password="required" continue with the rollout',
     'password="required" continue with the rollout'),
])
def test_round_ten_signature_aliases_and_quoted_status_tails(raw, expected):
    assert ledger.redact(raw) == expected


def test_round_ten_single_character_secrets_and_markdown_links_are_redacted():
    for raw, expected in (
        ("redis-cli -aS", "redis-cli -a<secret>"),
        ("http -a S x", "http -a <secret> x"),
        ("passwd not-S", "passwd not-<secret>"),
        ('pw: "is S"', 'pw: "<secret>"'),
        ("password is currently S", "password is currently <secret>"),
        ("password changed to S", "password changed to <secret>"),
        ("x-hub-signature-256: sha256=S", "x-hub-signature-256: sha256=<secret>"),
        ("Stripe-Signature: t=123,v1=S", "Stripe-Signature: t=123,v1=<secret>"),
        ('Authorization: Hawk id="a", mac="S"', "Authorization: <secret>"),
        ("xh -a bob:S", "xh -a bob:<secret>"),
        ("redis-cli -u redis://:S@h", "redis-cli -u redis://<cred>@h"),
        ("token: [x](S)", 'token: "<secret>"'),
        ("password: [link](https://x.test/S)", 'password: "<secret>"'),
        ("secret: [S](y)", 'secret: "<secret>"'),
    ):
        assert ledger.redact(raw) == expected


@pytest.mark.parametrize("raw,secret", [
    ("password:\n- R10_LIST_VALUE_SECRET", "R10_LIST_VALUE_SECRET"),
    ('cookies: ["R10_COOKIE_LIST_SECRET"]', "R10_COOKIE_LIST_SECRET"),
    ('adminpw: ["R10_SHORTPASS_LIST_SECRET"]', "R10_SHORTPASS_LIST_SECRET"),
    ('adminpw: "first\n  R10_SHORTPASS_QUOTE_SECRET"', "R10_SHORTPASS_QUOTE_SECRET"),
    ("password: |2\n    first\n  R10_INDENTED_BLOCK_SECRET", "R10_INDENTED_BLOCK_SECRET"),
    ('password: "first\\"\n  R10_ESCAPED_QUOTE_SECRET"\nQuestion: keep?', "R10_ESCAPED_QUOTE_SECRET"),
    ("Authorization: OAuth R10_OAUTH_AUTH_SECRET", "R10_OAUTH_AUTH_SECRET"),
    ("password is required_R10_PROSE_SECRET", "R10_PROSE_SECRET"),
    ("signature=required_R10_SIGNATURE_SECRET", "R10_SIGNATURE_SECRET"),
])
def test_sol_round_ten_redaction_probe_cases(raw, secret):
    assert secret not in ledger.redact(raw)


def test_round_ten_yaml_block_and_kubernetes_secrets_do_not_reach_persisted_rows():
    note = '- password: |\n    R10_PERSISTED_BLOCK_SECRET\n- name: DB_PASSWORD\n  value: {key: R10_PERSISTED_PAIR_SECRET}'
    ledger.add("miss", "round-ten-persisted", note=note)
    row = [r for r in ledger.rows() if r["key"] == "round-ten-persisted"][-1]
    assert "R10_PERSISTED_BLOCK_SECRET" not in row["note"]
    assert "R10_PERSISTED_PAIR_SECRET" not in row["note"]
