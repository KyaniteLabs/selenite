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
