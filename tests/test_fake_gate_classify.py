import pytest

from antibeaurocracy_core import DEPENDENCY, FAKE, HUMAN, MACHINERY, WALL, classify, configure
from antibeaurocracy_core.classify import ACTIONS

WALLS = [
    ("npm publish fails: ENEEDAUTH, no working token on this host", "credentials"),
    ("push denied HTTP 403; bot identity push=false on the repo", "credentials"),
    ("Search API balance exhausted (402 Payment Required); top-up is a spend decision", "spend"),
    ("Ready to publish to npm once approved", "publish"),
    ("This would force-push over main and is irreversible", "destructive"),
    ("Needs license compatibility review before vendoring", "legal"),
    ("Endpoint is under a security hold; no restart", "named-freeze"),
    # Phrasings that once slipped through as "Proceed".
    ("Waiting for approval from the owner before I delete the production database rows", "destructive"),
    ("Should I wire the $4,000 to the vendor?", "spend"),
    ("Awaiting go-ahead to send the launch email to the customer list", "publish"),
    ("Waiting for permission to merge to main and deploy to prod", "publish"),
    ("Awaiting approval to charge the customer's card", "spend"),
    ("Need the reviewer's OK before I rewrite history on the release branch", "destructive"),
    ("Waiting on the lead before I tweet the announcement", "publish"),
    ("Approval from ops to buy the extra seats", "spend"),
    ("Awaiting the bot to merge the PR to main", "publish"),
]

FAKES = [
    ("Awaiting approval from Product before I run the tests", "F1-ack"),
    ("Await the release agent to open the PR from my patch", "F2-relay"),
    ("Need the other agent to push my branch", "F2-relay"),
    ("Product must record the ruling on the release format", "F3-ownership-limbo"),
    ("Security and Platform jointly adopt the review contract", "F3-ownership-limbo"),
    ("Contract says local-only, so cannot mark done", "F4-ceremony"),
    ("HOLD: keep the old export until further notice", "F5-parking-lot"),
]

# A wall word that is being denied must not make the wait a wall (and so hide bureaucracy).
NEGATED = [
    "HOLD. No spend involved.",
    "HOLD: not a force-push, just a rebase on my branch",
    "Awaiting ACK from platform; nothing to publish here",
]


@pytest.mark.parametrize("text,sub", WALLS)
def test_walls(text, sub):
    v = classify(text)
    assert v.cls == WALL and sub in v.subtype, v


@pytest.mark.parametrize("text,sub", FAKES)
def test_fakes(text, sub):
    v = classify(text)
    assert v.cls == FAKE and v.subtype == sub, v


@pytest.mark.parametrize("text", NEGATED)
def test_negated_wall_words_do_not_count(text):
    assert classify(text).cls == FAKE


def test_negation_does_not_hide_a_real_wall_elsewhere():
    assert classify("No ACK needed, but this will delete the production database").cls == WALL


def test_no_action_claims_safety():
    for text in ACTIONS.values():
        assert "Proceed." not in text and "is reversible" not in text


def test_bare_words_are_not_walls():
    assert classify("Preserved the custody disposition for the credential handoff notes").cls != WALL
    assert classify("Technical capability gap, not an approval ask: need a credential-free desktop").cls != WALL
    assert classify("Waiting for sign-off from product on the budget line wording").cls == FAKE


def test_wall_beats_fake():
    assert classify("Awaiting approval from Product; push=false for the bot").cls == WALL


def test_human_questions_are_not_agent_gates():
    assert classify("Should I rename the module to core?").cls == HUMAN
    assert classify("Which do you prefer, A or B?").cls == HUMAN
    assert classify("anything at all", kind="needs_input").cls == HUMAN
    assert classify("Product must reconcile the scope", kind="needs_input").cls == FAKE
    assert classify("this run has no GPU device exposed", kind="needs_input").cls == MACHINERY


def test_machinery():
    assert classify("Runtime has no GPU: no GPU here, no ROCm devices").cls == MACHINERY
    assert classify("Provider rate limited us, retry later").cls == MACHINERY
    assert classify("worker crashed 3 times; gave up after 3 attempts").cls == MACHINERY


def test_dependency():
    assert classify("blocked by t_1a2b3c4d").cls == DEPENDENCY
    assert classify("anything", kind="dependency").cls == DEPENDENCY


def test_defaults_are_not_evidenced():
    v = classify("", created_blocked=True)
    assert v.subtype == "F5-parking-lot" and not v.evidenced and v.confidence < 0.6
    v = classify("Looking into it", age_hours=72)
    assert v.subtype == "F6-stale-wait" and not v.evidenced
    assert classify("Looking into it", age_hours=2).confidence < 0.6
    assert classify("Awaiting approval from Product").evidenced


def test_age_hours_as_string():
    assert classify("Looking into it", age_hours="72").subtype == "F6-stale-wait"
    assert classify("Looking into it", age_hours="soon").cls == FAKE


def test_hold_with_expiry_is_legit():
    assert classify("HOLD until 2026-11-17 for the compute window").cls != FAKE


def test_configured_seats():
    assert classify("Awaiting approval from quartermaster").cls != FAKE or classify("Awaiting approval from quartermaster").subtype != "F1-ack"
    configure(seats=["quartermaster"])
    try:
        assert classify("Awaiting approval from quartermaster").subtype == "F1-ack"
    finally:
        configure()


def test_human_roles_are_not_seats():
    assert classify("Waiting for approval from the owner").cls != FAKE or classify("Waiting for approval from the owner").subtype != "F1-ack"
    assert classify("Need sign-off from legal on the terms").cls == WALL


# Round-2 review corpus: phrasings that must reach the right class.
ADVERSARIAL_WALLS = [
    ("Awaiting ACK from Platform to run terraform apply", "publish"),
    ("Awaiting ACK from Platform to git push --force", "destructive"),
    ("Awaiting ACK from Platform to delete everything in the old namespace", "destructive"),
    ("Awaiting ACK from Platform; this will cost about 3k per month", "spend"),
    ("Need an OK before kubectl delete on the staging cluster", "publish"),
    ("Cannot proceed without deleting the prod database", "destructive"),
    ("There is no way around a force-push here", "destructive"),
    ("Not sure whether to delete the production database", "destructive"),
    ("don't proceed until billing approves", "spend"),
]


@pytest.mark.parametrize("text,sub", ADVERSARIAL_WALLS)
def test_adversarial_walls(text, sub):
    v = classify(text)
    assert v.cls == WALL and sub in v.subtype, v


@pytest.mark.parametrize("text", ["Awaiting ACK from the CEO", "HOLD per the CEO", "Waiting on the founder's OK",
                                  "Awaiting approval from the owner"])
def test_a_person_with_authority_is_human(text):
    assert classify(text).cls == HUMAN


def test_lowercase_on_hold_is_not_evidence():
    v = classify("The service is on hold for now")
    assert not v.evidenced


def test_capability_kind_is_machinery_even_with_gate_words():
    assert classify("Product must reconcile the scope", kind="capability").cls == MACHINERY


def test_kind_of_any_type_does_not_raise():
    for k in (1, ["x"], {"a": 1}, 3.5, True):
        classify("Awaiting approval from Product", kind=k)
    classify(None)
    classify(12345)


# Round 3: a bare role noun is not a person's authority; the role must be the source of the wait.
@pytest.mark.parametrize("text,cls,sub", [
    ("Timed out waiting for the client to connect", MACHINERY, None),
    ("window manager crashed, waiting", MACHINERY, None),
    ("tests fail in the user module, ok", MACHINERY, None),
    ("attestation required before the board can be updated", FAKE, "F4-ceremony"),
    ("Awaiting ACK from platform on the customer-facing copy", FAKE, "F1-ack"),
])
def test_role_nouns_are_not_authority(text, cls, sub):
    v = classify(text)
    assert v.cls == cls and (sub is None or v.subtype == sub), v


def test_an_agent_named_after_a_role_is_not_a_person():
    assert classify("Awaiting ACK from the CEO agent").cls != HUMAN


@pytest.mark.parametrize("text,sub", [
    ("It will cost roughly 3000 to run; attestation required first", "spend"),
    ("This would cost about 3k", "spend"),
    ("need 3k/month", "spend"),
    ("No budget approval yet; awaiting the relay to create the PR", "spend"),
    ("no subscription seat left; need platform to merge the PR", "spend"),
    ("I have no API key for the registry; need platform to push the branch", "credentials"),
    ("Reversible: no\nDeploy to prod pending; awaiting the relay", "publish"),
])
def test_stated_absences_and_any_amount_stay_walls(text, sub):
    v = classify(text)
    assert v.cls == WALL and sub in v.subtype, v


@pytest.mark.parametrize("text", ["helm upgrade timed out", "kubectl apply dry-run failed: connection refused"])
def test_a_failing_infra_command_is_machinery(text):
    assert classify(text).cls == MACHINERY


def test_a_count_per_month_is_not_spend():
    assert classify("retries 3 per month on the cron").cls != WALL


def test_long_reasons_are_bounded():
    import time
    t = time.perf_counter()
    classify("awaiting " * 50_000)
    assert time.perf_counter() - t < 1.0


# Round 4: neighbouring phrasings of the round-3 fixes.
@pytest.mark.parametrize("text,sub", [
    ("Reversible: no \nDeploy to prod pending; awaiting relay", "publish"),
    ("Reversible: no\t\nDeploy to prod pending; awaiting relay", "publish"),
    ("kubectl delete failed for the prod namespace; need platform to run the command", "publish"),
    ("terraform destroy failed: forbidden; awaiting relay to run it with elevated rights", "publish"),
    ("helm uninstall errored; attestation required before I retry", "publish"),
    ("The new instance is 3000 per month; awaiting relay to create the PR", "spend"),
    ("e-stop is engaged; awaiting relay", "named-freeze"),
    ("Await the release agent to open the PR from my patch. " + "x " * 2150 + "This step will drop table users in prod.",
     "destructive"),
])
def test_round4_walls(text, sub):
    v = classify(text)
    assert v.cls == WALL and sub in v.subtype, v


@pytest.mark.parametrize("text", [
    "The CEO must countersign this before I continue", "Founder has to ratify the plan first",
    "Attestation required: CEO has not signed", "HOLD until the CEO approves",
    "Awaiting approval from the CEO; the last attempt timed out", "Awaiting approval from the owner; build failed twice",
])
def test_round4_person_is_human(text):
    assert classify(text).cls == HUMAN


@pytest.mark.parametrize("text", [
    "attestation required for the board update", "Awaiting ACK from platform on the customer portal copy",
    "Awaiting relay to create the PR for the client library", "Awaiting ACK from the CEO's agent",
    "no payment needed; awaiting relay to create the PR", "No credentials needed; awaiting relay to create the PR",
    "no secrets in the diff; awaiting relay to create the PR",
    "no output tokens left in this turn; awaiting relay to create the PR",
])
def test_round4_fakes_are_not_hidden(text):
    assert classify(text).cls == FAKE


@pytest.mark.parametrize("text", ["kubectl apply dry-run failed", "helm upgrade failed"])
def test_round4_failing_infra_alone_is_machinery(text):
    assert classify(text).cls == MACHINERY
