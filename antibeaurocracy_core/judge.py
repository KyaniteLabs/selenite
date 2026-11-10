"""Optional second opinion for the audit: run any command you choose over the blocked cards.

Off by default and CLI-only. The plugin's hooks never call it, so no block waits on a model and
nothing leaves the machine unless you pass ``--judge``.

The command is yours (``claude -p``, ``llm``, ``ollama run <model>``, a script): it gets one prompt on
stdin and must print one of WALL, HUMAN, MACHINERY, DEPENDENCY or FAKE. It is run without a shell,
one card at a time, with a timeout. The regex verdict stays the audit's verdict; the judge only adds
a list of cards where the two disagree, for a person to look at.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Callable, Iterable

from .classify import FAKE

CLASSES = ("WALL", "HUMAN", "MACHINERY", "DEPENDENCY", "FAKE")
_ANSWER = re.compile(r"\b(" + "|".join(CLASSES) + r")\b")

PROMPT = """Classify why this kanban card is blocked. Answer with exactly one word.

WALL: credentials, spend, publishing or deploying, a destructive step, legal, or a named freeze.
HUMAN: a question only a person can answer, or a stop or OK from a person with authority.
MACHINERY: a tool, permission or host is broken or missing.
DEPENDENCY: another task has to land first.
FAKE: waiting only for another agent's OK, relay, ruling or ceremony on work the blocked agent could do.
If unsure, answer WALL.

Block reason:
{reason}
"""


def parse(out: str) -> str:
    """The first class word in the output, or "" when there is none."""
    m = _ANSWER.search((out or "").upper())
    return m.group(1) if m else ""


def runner(cmd: str, timeout_s: float = 60.0) -> Callable[[str], str]:
    argv = shlex.split(cmd)
    if not argv:
        raise ValueError("--judge needs a command")

    def ask(prompt: str) -> str:
        try:
            p = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=timeout_s)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return parse(p.stdout) if p.returncode == 0 else ""

    return ask


def candidates(boards: Iterable[dict]) -> list[dict]:
    """Cards worth a second look: every FAKE verdict (evidenced or not) that has a reason to read."""
    out = []
    for b in boards:
        for c in b.get("blocked", []):
            if c["verdict"]["cls"] == FAKE and c.get("reason") and c.get("bucket") not in ("auto_blocked", "created_blocked"):
                out.append(c)
    out.sort(key=lambda c: -c["age_h"])
    return out


def second_opinion(boards: Iterable[dict], ask: Callable[[str], str], limit: int = 20) -> dict:
    cards = candidates(boards)[:max(0, limit)]
    agree = no_answer = 0
    disagree = []
    for c in cards:
        got = ask(PROMPT.format(reason=c["reason"]))
        if not got:
            no_answer += 1
        elif got == FAKE:
            agree += 1
        else:
            disagree.append({"id": c["id"], "regex": c["verdict"]["label"], "judge": got})
    return {"asked": len(cards), "agree": agree, "no_answer": no_answer, "disagree": disagree}


def render(op: dict) -> str:
    L = ["## Second opinion (--judge)",
         f"Asked about {op['asked']} cards the regex calls fake: {op['agree']} agree, "
         f"{len(op['disagree'])} disagree, {op['no_answer']} gave no usable answer.",
         "The regex verdict above still stands; check these by hand."]
    for d in op["disagree"]:
        L.append(f"- `{d['id']}` regex **{d['regex']}**, judge **{d['judge']}**")
    return "\n".join(L) + "\n"
