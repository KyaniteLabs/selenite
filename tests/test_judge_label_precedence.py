"""The judge prompt's WALL and HUMAN labels overlapped ("CEO approves the deploy" fits both).

LFM3 answered HUMAN for that case 3 times out of 3 (21/24 overall); with WALL stated as winning and
HUMAN stated as excluding the wall items it got 24/24. The prompt must keep that precedence.
"""
from antibeaurocracy_core import judge


def _line(label):
    return next(l for l in judge.PROMPT.splitlines() if l.startswith(label + ":"))


def test_wall_is_stated_to_win_over_a_person_approving():
    assert "WALL wins" in _line("WALL")
    assert "even when a person must approve" in _line("WALL")


def test_human_excludes_the_wall_steps():
    human = _line("HUMAN")
    for word in ("credential", "spend", "publish", "deploy", "destructive", "legal", "freeze"):
        assert word in human
    assert "authority" not in human  # the old "OK from a person with authority" overlapped WALL


def test_prompt_still_formats_and_names_every_class():
    out = judge.PROMPT.format(reason="x")
    for c in judge.CLASSES:
        assert c in out
