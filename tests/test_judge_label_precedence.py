"""The judge prompt's WALL and HUMAN labels overlapped ("CEO approves the deploy" fits both).

LFM3 answered HUMAN for that case 3 times out of 3 (21/24 overall); with WALL stated as winning and
HUMAN stated as excluding the wall items it got 24/24. The prompt must keep that precedence.
"""
import pytest

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


@pytest.mark.parametrize("text", [
    "**ANSWER**: FAKE",
    "### ANSWER: FAKE",
    "ANSWER: `FAKE`",
    "1. ANSWER: FAKE",
    "ANSWER: [FAKE]",
    "__ANSWER:__ FAKE",
    "ANSWER: _FAKE_",
    'ANSWER: "FAKE"',
    "ANSWER: (FAKE)",
    "2) ANSWER: FAKE",
    "Final answer: FAKE",
])
def test_parse_accepts_common_markdown_answer_lines(text):
    assert judge.parse(text) == "FAKE"


@pytest.mark.parametrize("text,label", [
    ("ANSWER: HUMAN (needs a pricing decision)", "HUMAN"),
    ("ANSWER: WALL - deploy needs approval", "WALL"),
    ("ANSWER: FAKE — just waiting for a relay", "FAKE"),
    ("ANSWER: DEPENDENCY, task t_12 must land", "DEPENDENCY"),
    ("**ANSWER: MACHINERY** because the host is down", "MACHINERY"),
    ("ANSWER: WALL</s>", "WALL"),
    ("ANSWER:\nFAKE", "FAKE"),
])
def test_parse_accepts_a_verdict_followed_by_its_reason(text, label):
    assert judge.parse(text) == label


@pytest.mark.parametrize("text,label", [
    ("ANSWER: WALL (HUMAN must approve deploy)", "WALL"),
    ("ANSWER: HUMAN - WALL is not involved", "HUMAN"),
    ("ANSWER: HUMAN (pricing choice)", "HUMAN"),
    ("ANSWER: WALL. Human sign-off is the wall.", "WALL"),
    ("ANSWER: FAKE, dependency already landed", "FAKE"),
    ("ANSWER: MACHINERY (fake heartbeat from cron)", "MACHINERY"),
    ("ANSWER: HUMAN (pricing | legal review)", "HUMAN"),
])
def test_parse_keeps_reasons_that_mention_another_class(text, label):
    assert judge.parse(text) == label


@pytest.mark.parametrize("text", [
    "ANSWER: [WALL|HUMAN|MACHINERY|DEPENDENCY|FAKE]",
    "ANSWER: <FAKE|WALL>",
    "ANSWER: WALL | HUMAN",
    "ANSWER: WALL/HUMAN",
    "ANSWER: WALL or HUMAN",
    "ANSWER: WALL, HUMAN",
    "ANSWER: WALL - HUMAN",
    "ANSWER: WALL. HUMAN.",
    "ANSWER: WALL (HUMAN)",
    "ANSWER: FAKE or WALL",
    "ANSWER: FAKE and WALL",
    "ANSWER: FAKE (or WALL)",
    "ANSWER: FAKE unless credentials are needed, then WALL",
    "ANSWER: FAKE is wrong; this is a WALL",
    "ANSWER: FAKE -> WALL",
    "ANSWER: FAKE & HUMAN",
    "FAKE? No, WALL.",
])
def test_parse_rejects_echoed_class_templates(text):
    assert judge.parse(text) == ""


def test_an_ambiguous_later_answer_does_not_replace_an_earlier_verdict():
    assert judge.parse("ANSWER: WALL\nANSWER: FAKE or WALL (not sure)") == ""


def test_class_leading_reason_is_counted_as_a_judge_disagreement():
    boards = [{"blocked": [{
        "id": "t_r9",
        "reason": "Awaiting approval from Product",
        "age_h": 1,
        "bucket": "blocked",
        "verdict": {"cls": "FAKE", "label": "FAKE"},
    }]}]
    answer = judge.parse("ANSWER: WALL (HUMAN must approve deploy)")
    result = judge.second_opinion(boards, lambda _: answer)
    assert result["no_answer"] == 0
    assert result["disagree"] == [{"id": "t_r9", "regex": "FAKE", "judge": "WALL"}]


@pytest.mark.parametrize("text,label", [
    ("ANSWER: WALL. A HUMAN cannot override it.", "WALL"),
    ("ANSWER: DEPENDENCY on the HUMAN review", "DEPENDENCY"),
    ("ANSWER: HUMAN (the CEO must decide; not a WALL)", "HUMAN"),
    ("ANSWER: FAKE (the WALL claim is bogus)", "FAKE"),
    ("ANSWER: MACHINERY (the HUMAN gate fired by mistake)", "MACHINERY"),
    ("ANSWER: WALL (needs HUMAN sign-off)", "WALL"),
    ("ANSWER: WALL - a HUMAN has to log in", "WALL"),
    ("ANSWER: FAKE. This is not a HUMAN gate.", "FAKE"),
    ("ANSWER: FAKE rather than WALL", "FAKE"),
    ("ANSWER: WALL (not HUMAN, FAKE or MACHINERY)", "WALL"),
    ("ANSWER: WALL because a HUMAN must approve", "WALL"),
    ("ANSWER: FAKE (the WALL is only a claim)", "FAKE"),
    ("ANSWER: WALL — not HUMAN, the policy forbids it", "WALL"),
    ("ANSWER: WALL, not HUMAN", "WALL"),
    ("ANSWER: WALL (HUMAN must not override)", "WALL"),
    ("ANSWER: HUMAN — WALL is not involved", "HUMAN"),
    ("ANSWER: HUMAN; WALL is not involved", "HUMAN"),
    ("ANSWER: FAKE — no HUMAN needed", "FAKE"),
    ("ANSWER: WALL | reason: needs HUMAN login", "WALL"),
    ("ANSWER: HUMAN (needs sign-off from the API owner)", "HUMAN"),
    ("ANSWER: MACHINERY (cron/systemd timer dead)", "MACHINERY"),
    ("ANSWER: HUMAN (approve or reject)", "HUMAN"),
    ("ANSWER: DEPENDENCY (t_12 or t_13 must land)", "DEPENDENCY"),
    ("ANSWER: HUMAN (Ada and/or Bob must sign)", "HUMAN"),
    ("ANSWER: DEPENDENCY - waiting on card t_1 which is a WALL", "DEPENDENCY"),
    ("ANSWER: FAKE, it is hardly a WALL", "FAKE"),
    ("ANSWER: FAKE instead of HUMAN", "FAKE"),
    ("ANSWER: WALL, as opposed to FAKE", "WALL"),
    ("ANSWER: WALL (I first thought FAKE)", "WALL"),
])
def test_round_ten_explanations_can_mention_other_classes(text, label):
    assert judge.parse(text) == label


@pytest.mark.parametrize("text", [
    "ANSWER: WALL/HUMAN",
    "ANSWER: WALL or HUMAN",
    "ANSWER: WALL | HUMAN",
    "ANSWER: WALL? HUMAN",
    "ANSWER: wall, human",
    "ANSWER: FAKE, or wall",
    "ANSWER: FAKE? no - wall",
    "ANSWER: FAKE? Not WALL",
    "ANSWER: WALL |",
    "ANSWER: HUMAN? No, WALL",
    "ANSWER: FAKE, WALL",
    "ANSWER: FAKE; WALL",
    "ANSWER: FAKE -> WALL",
    "ANSWER: FAKE... actually WALL",
    "ANSWER: FAKE vs WALL",
    "ANSWER: FAKE, possibly WALL",
])
def test_round_ten_genuine_class_alternatives_have_no_answer(text):
    assert judge.parse(text) == ""


def test_round_ten_unclear_last_answer_does_not_fall_back_to_an_earlier_one():
    assert judge.parse("ANSWER: FAKE\nANSWER: WALL or FAKE") == ""
    assert judge.parse("ANSWER: FAKE\nANSWER: unclear") == ""
