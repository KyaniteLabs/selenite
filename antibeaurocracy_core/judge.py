"""Optional second opinion for the audit: run any command you choose over the blocked cards.

Off by default and CLI-only. The plugin's hooks never call it, so no block waits on a model and
nothing leaves the machine unless you pass ``--judge``.

The command is yours (``claude -p``, ``llm``, ``ollama run <model>``, a script): it gets one prompt on
stdin and must print one of WALL, HUMAN, MACHINERY, DEPENDENCY or FAKE. It is run without a shell,
one card at a time, with a timeout. The regex verdict stays the audit's verdict; the judge only adds
a list of cards where the two disagree, for a person to look at.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Callable, Iterable, Optional

from .classify import FAKE

CLASSES = ("WALL", "HUMAN", "MACHINERY", "DEPENDENCY", "FAKE")
_CLASS = "|".join(CLASSES)
_ANSWER_LINE = re.compile(
    r'^[\s>*#\-\d.)]*[*_`]*(?:FINAL[ \t]+)?ANSWER[*_`]*[ \t]*:[ \t]*(?:\r?\n[ \t]*)?[*_`\[<({"\']*[ \t]*('
    + _CLASS
    + r')(?![A-Za-z0-9])(?!_(?:' + _CLASS + r')\b)'
    + r'(?![ \t]*(?:/|or\b)[ \t]*(?:' + _CLASS + r')\b)'
    + r'(?![^\r\n]*\|[ \t]*(?:' + _CLASS + r')\b)'
    + r'(?![^\r\n]*\|\s*$)'
    + r'(?![ \t]*\?[ \t]*[Nn]o[,;:]?[ \t]+(?:' + _CLASS + r')\b)'
    + r'[^\r\n]*$',
    re.IGNORECASE | re.MULTILINE,
)
_UPPER_CLASS = re.compile(r"\b(" + _CLASS + r")\b")
_BARE = re.compile(rf"(?:(?!\|)[\W_])*({_CLASS})(?:(?!\|)[\W_])*", re.IGNORECASE)
_THINK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|\Z)", re.I | re.S)


def _ambiguous_classes(match: re.Match[str]) -> bool:
    """Reject a second uppercase class choice while allowing class-leading explanation prose."""
    first = match.group(1).upper()
    suffix = match.string[match.end(1):match.end()]
    for other in _UPPER_CLASS.finditer(suffix):
        label = other.group(1)
        if label == first:
            continue
        before = suffix[:other.start()]
        after = suffix[other.end():]
        if re.search(r"\b(?:not|no|never|without|isn't|aren't|wasn't)\s*$", before, re.IGNORECASE):
            continue
        if (first == "WALL" and label == "HUMAN"
                and re.search(r"\(\s*$", before)
                and re.match(r"\s+must\b", after, re.IGNORECASE)):
            continue
        if (first == "HUMAN" and label == "WALL"
                and re.search(r"[-—]\s*$", before)
                and re.match(r"\s+is\s+not\s+involved\b", after, re.IGNORECASE)):
            continue
        return True
    return False

PROMPT = """Classify why this kanban card is blocked. Think briefly if you must, then end with a final line of the form
ANSWER: <CLASS>
where <CLASS> is exactly one of WALL, HUMAN, MACHINERY, DEPENDENCY, FAKE.

WALL: credentials, spend, publishing or deploying, a destructive step, legal, or a named freeze. WALL wins: if the wait involves any of these, answer WALL even when a person must approve it.
HUMAN: a question or choice only a person can answer, with no credential, spend, publish, deploy, destructive, legal or freeze step in it.
MACHINERY: a tool, permission or host is broken or missing.
DEPENDENCY: another task has to land first.
FAKE: waiting only for another agent's OK, relay, ruling or ceremony on work the blocked agent could do.
If unsure, ANSWER: WALL.

Block reason:
{reason}
"""


def parse(out: str) -> str:
    """The class on the last ``ANSWER: <CLASS>`` line, outside any think block, or "" when there is none.

    Prose is never scanned for class words ("Not FAKE, this is a WALL" must not read as FAKE). The one
    exception is a reply that is nothing but a single class word, the old one-word contract.
    """
    text = _THINK.sub("", out or "")
    found = [m.group(1) for m in _ANSWER_LINE.finditer(text) if not _ambiguous_classes(m)]
    if found:
        return found[-1].upper()
    m = _BARE.fullmatch(text.strip())
    return m.group(1).upper() if m else ""


def split_command(cmd: str, windows: Optional[bool] = None) -> list[str]:
    """Split a ``--judge`` command line. On Windows a backslash is a path separator, not an escape."""
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.split(cmd)
    return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t for t in shlex.split(cmd, posix=False)]


def runner(cmd: str, timeout_s: float = 60.0) -> Callable[[str], str]:
    argv = split_command(cmd)
    if not argv:
        raise ValueError("--judge needs a command")

    def ask(prompt: str) -> str:
        try:
            p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout_s)
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
