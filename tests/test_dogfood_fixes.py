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
from antibeaurocracy_core import FAKE, HUMAN, WALL, classify


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
