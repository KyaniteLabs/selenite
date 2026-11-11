"""Classifier regressions from the 2026-11-10 dogfood report.

Catalog/marketplace submissions are publishing walls, and the infinitive form
after a role ("needs the CEO to approve") reads as a person's approval.
Proper names are deliberately still not matched: a product or model name is
not a person.

The packaging findings from the same report (install.sh on a read-only target,
cleanse.py on an unwritable state folder) are covered in
``tests/test_seat_packaging.py`` with this card's contract: a read-only target
is skipped, the install still ends with a summary and exit 0, and cleanse
falls through the state folders and exits 0. Keeping one copy of those shell
fixtures avoids two tests asserting opposite contracts.
"""
import json
import sys

from antibeaurocracy_core import DEPENDENCY, FAKE, HUMAN, WALL, classify


def test_catalog_entry_is_a_publishing_wall():
    v = classify("Needs Alex to approve the catalog entry before we submit")
    assert v.cls == WALL
    assert v.subtype == "publish"
    assert v.confidence >= 0.9


def test_marketplace_submission_is_a_publishing_wall():
    v = classify("Blocked until we submit the marketplace listing")
    assert v.cls == WALL
    assert v.subtype == "publish"


def test_role_to_approve_is_a_person():
    v = classify("Needs the CEO to approve the copy change")
    assert v.cls == HUMAN
    assert v.confidence >= 0.7


def test_waiting_on_owner_to_sign_off_is_a_person():
    v = classify("Waiting on the owner to sign off on the pricing page")
    assert v.cls == HUMAN


def test_ordinary_wait_stays_stale_not_wall():
    v = classify("Waiting on the build to finish before we can test")
    assert v.cls == FAKE  # still the low-confidence stale default, never a wall
    assert v.confidence < 0.6  # below the action threshold


def test_product_name_is_not_a_person():
    # "Sol" is a model, not a person: proper names must not match the role list.
    v = classify("Waiting on Sol to finish the render")
    assert v.cls != HUMAN


# --- D5 (cco) + D9 (cgo): seat-dogfood classifier gaps -------------------

def test_seat_roles_and_noun_approvals_are_people():
    for text in (
        "needs CEO approval to submit.",
        "CEO word on the catalog description copy.",
        "technical capability gap, need Liam/Platform to expose a GUI wrapper",
        "the CEO's approval",
    ):
        assert classify(text).cls == HUMAN, text


def test_seat_go_stays_a_fake_gate_per_shipped_contract():
    # cco expected HUMAN; the shipped round-4 contract says a wait on an agent seat's GO
    # ("waiting on platform approval", "needs Security GO") is a fake gate the seats can clear
    # themselves. The seat-as-builder form above is the only seat path to HUMAN.
    assert classify("needs Security GO plus all-CI-green.").cls == FAKE
    assert classify("waiting on platform approval before I merge").cls == FAKE


def test_pr_dependency_is_a_dependency():
    assert classify("blocked by PR #271.").cls == DEPENDENCY
    assert classify("Waiting on task t_abc123 to land.").cls == DEPENDENCY


def test_publish_with_ceo_approval_is_still_a_wall():
    v = classify("cannot publish without CEO approval")
    assert v.cls == WALL  # rule 1 wins over rule 5


def test_capability_wall_escalates_instead_of_closing():
    v = classify("appeal is Simon-held, no agent can clear it")
    assert v.cls == WALL
    assert v.subtype == "declared-capability"
    assert v.confidence >= 0.6  # above the action threshold: escalate, never "close the card"


def test_product_and_model_names_are_still_not_people():
    assert classify("Waiting on Sol to finish the render").cls != HUMAN
    assert classify("the product must ship before Friday").cls != HUMAN


def test_weak_authority_still_needs_a_wait_word():
    # "the CEO" alone, referenced with no wait word and no gate, is not a person's stop
    assert classify("mention the CEO in the postmortem").cls != HUMAN


# --- D6 (cco) + D10 (cgo): per-seat scoping and nested profile skills -----

def test_nested_profile_skills_are_scanned(tmp_path, monkeypatch):
    import skills.frictionless.scripts.cleanse as c
    home = tmp_path / "home"
    prof = home / ".hermes-org" / "profiles" / "cco"
    nested = prof / "skills" / "creative" / "video-production"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("no frontmatter at all\n")  # bad on purpose: proof of visibility
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(prof))  # a seat exports its profile as the Hermes home
    monkeypatch.setattr(c, "HOME", home)  # HOME is read at import; point the module at the fixture
    findings = c.check_skills({"days": 30, "paths": []})
    assert any(f["check"] == "no-frontmatter" and "video-production" in f["where"] for f in findings), \
        "a skill one level deep (category/skill) used to be invisible (D6)"


def test_only_flag_excludes_other_roots(tmp_path, monkeypatch):
    import skills.frictionless.scripts.cleanse as c
    home = tmp_path / "home"
    prof = home / ".hermes-org" / "profiles" / "cco"
    (prof / "skills").mkdir(parents=True)
    bad = home / ".claude" / "skills" / "broken"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("no frontmatter at all\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes-org"))
    monkeypatch.setattr(c, "HOME", home)
    findings = c.check_skills({"days": 30, "paths": [], "only": [str(prof)]})
    assert findings == [], "--only must keep shared ~/.claude findings out of a seat report (D10)"
    full = c.check_skills({"days": 30, "paths": []})
    assert any(f["check"] == "no-frontmatter" for f in full), "without --only the shared root is still swept"


# --- D7/D8 (cco + cgo): mine.py seat attribution --------------------------

def test_mine_samples_are_fair_across_agents(tmp_path, monkeypatch):
    import skills.frictionless.scripts.mine as m
    def fake_claude(root, since):
        for i in range(20):
            yield "claude-code", "proj", f"wtf number {i}"
    def fake_hermes(db, since):
        for i in range(2):
            yield "hermes", "seat", f"wtf hermes {i}"
    monkeypatch.setattr(m, "iter_claude", fake_claude)
    monkeypatch.setattr(m, "iter_codex", lambda root, since: iter(()))
    monkeypatch.setattr(m, "iter_hermes", fake_hermes)
    monkeypatch.setattr(m, "HOME", tmp_path)
    monkeypatch.setattr(sys, "argv", ["mine.py", "--out", str(tmp_path), "--samples", "8"])
    rc = m.main()
    assert rc == 0
    sp = sorted(tmp_path.glob("samples-*.json"))[-1]
    samples = json.loads(sp.read_text())["curse"]
    agents = [s["agent"] for s in samples]
    assert agents.count("claude-code") <= 4, "one busy agent must not eat the whole budget (D8)"
    assert "hermes" in agents, "the seat's own friction must be visible in the default samples (D8)"


def test_mine_hermes_home_flag(tmp_path, monkeypatch):
    import skills.frictionless.scripts.mine as m
    captured = {}
    def fake_hermes(db, since):
        captured["db"] = db
        return iter(())
    monkeypatch.setattr(m, "iter_claude", lambda root, since: iter(()))
    monkeypatch.setattr(m, "iter_codex", lambda root, since: iter(()))
    monkeypatch.setattr(m, "iter_hermes", fake_hermes)
    monkeypatch.setattr(m, "HOME", tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    prof = tmp_path / "profiles" / "cco"
    monkeypatch.setattr(sys, "argv", ["mine.py", "--out", str(tmp_path), "--hermes-home", str(prof)])
    assert m.main() == 0
    assert captured["db"] == prof / "state.db", "--hermes-home must reach the source (D7)"
