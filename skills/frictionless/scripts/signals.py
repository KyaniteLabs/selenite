"""Shared overload/friction signal detector. Stdlib only.

Used by mine.py, ledger.py and the Hermes plugin so the patterns live once.
Extra per-person words: $SELENITE_HOME/signals.txt, one regex per line,
format "<category>\t<regex>".
"""
from __future__ import annotations

import os
import re
from pathlib import Path

CATEGORIES: dict[str, list[str]] = {
    "human_gate": [
        r"\b(i|you) (have|need) to (log ?in|sign ?in|paste|approve|click|run)\b",
        r"\bmanual(ly)? steps?\b", r"\btoken step\b", r"\bre-?auth\b",
        r"\b(gh|gcloud|az|npm|hermes) (auth )?login\b", r"\b2fa\b|\botp\b",
        r"\bcredential(s)? (step|prompt)\b", r"\bcopy ?paste comm?and\b",
        r"\bfriction ?(free|less)\b",
    ],
    "permission_prompt": [
        r"\bpermission prompts?\b", r"\bstop (asking|prompting) (for )?permission",
        r"\ballow ?list\b", r"\bapprove (every|each|all)\b", r"\bkeeps? asking\b",
    ],
    "over_asking": [
        r"\bstop asking\b", r"\bdon'?t ask\b", r"\b(cant|can't|cannot) you just\b",
        r"\bjust do it\b", r"\btoo many questions\b", r"\bi already (told|said|answered)\b",
        r"\bno more questions\b",
    ],
    "repeat_work": [
        r"\bi keep (having|doing|telling)\b", r"\bsame (thing|mistake|step) again\b",
        r"\bfor the (nth|\d+(st|nd|rd|th)) time\b", r"\bevery ?time now\b",
        r"\bi (already |just )?told you( that)?( (already|before|twice|again|\w+ times))?\b(?! about)",
        r"\bhow many times (do|have|must|did) i\b", r"\b(still|again) (broken|failing|not working)\b",
    ],
    "stopping_short": [
        r"\bwhy did(n'?t)? you (stop|finish)\b", r"\byou stopped\b", r"\bwhy (did|are) you (stop|wait)",
        r"\bfinish (it|the job)\b", r"\barbitrar(il)?y waiting\b",
    ],
    "curse": [
        r"\bwtf\b", r"\bf+u+c+k", r"\bshit\b", r"\bdamn it\b", r"\bffs\b",
    ],
    "frustration": [
        r"\bugh\b", r"\bannoy(ing|ed)\b", r"\bfrustrat", r"\bwaste of time\b", r"\btedious\b",
    ],
    "slow_loop": [
        r"\btoo slow\b", r"\btaking forever\b", r"\bwaiting (on|for) (you|it)\b",
    ],
}

# Harness-injected or agent-authored text that is not the human typing.
NOISE = re.compile(
    r"<(system-reminder|command-|local-command|task-notification|role>|pasted_content)"
    r"|^\s*\[Request interrupted|^\s*You are (an? |acting as )|^\s*Review this plan"
    r"|Worker identity|^\s*#+ ",
    re.I,
)

# Categories that mean "switch to Calm mode now".
OVERLOAD = {"curse", "frustration", "over_asking", "stopping_short", "repeat_work"}

# Whole-word transpositions, stuck keys and ??? runs. Whole words only:
# "cannot", "robot" and "screenshot" must never count. It measures load, not
# spelling, and one hit is never enough (see overload()).
_TYPO = re.compile(
    r"\b(?:teh|adn|hte|taht|wiht|yoiu|tge|ahve|waht|thsi|jsut|becuase|plese|pleae|thier|buidl|broekn|agian)\b"
    r"|([a-z])\1{3,}|\?{3,}",
    re.I,
)
# Paths, URLs and identifiers are technical tokens, not evidence of typing load.
_TECHNICAL = re.compile(r"[/\\_:=@]|\w[.-]\w")


def _load_extra() -> dict[str, list[str]]:
    home = Path(os.environ.get("SELENITE_HOME", Path.home() / ".config/selenite"))
    extra: dict[str, list[str]] = {}
    f = home / "signals.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "\t" in line and not line.startswith("#"):
                cat, pat = line.split("\t", 1)
                extra.setdefault(cat.strip(), []).append(pat.strip())
    return extra


def _compile() -> dict[str, list[re.Pattern]]:
    merged = {k: list(v) for k, v in CATEGORIES.items()}
    for k, v in _load_extra().items():
        merged.setdefault(k, []).extend(v)
    out = {}
    for k, pats in merged.items():
        out[k] = []
        for p in pats:
            try:
                out[k].append(re.compile(p, re.I))
            except re.error:
                pass
    return out


COMPILED = _compile()


def is_human_text(text: str) -> bool:
    return bool(text) and not NOISE.search(text[:400])


def classify(text: str) -> list[str]:
    """Categories hit by a human-authored message. Empty for noise."""
    if not is_human_text(text):
        return []
    text = text[:4000]
    return [c for c, pats in COMPILED.items() if any(p.search(text) for p in pats)]


def typo_hits(text: str) -> int:
    return sum(len(_TYPO.findall(word)) for word in text.split() if not _TECHNICAL.search(word))


def typo_density(text: str) -> float:
    """Rough typo hits per 100 words. A load signal, not a spelling check."""
    words = max(1, len(text.split()))
    return 100.0 * typo_hits(text) / words


# Text the person is quoting rather than saying: fenced or inline code, "> " quote lines and
# double-quoted spans. A pasted log that says "wtf" or a quoted complaint is not their mood.
_QUOTED = re.compile(
    r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)|`[^`\n]*`|^[ \t]*>[^\r\n]*|(?<![\w])\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d",
    re.S | re.M,
)


def own_words(text: str) -> str:
    """The message with quoted, fenced and pasted spans removed."""
    return _QUOTED.sub(" ", text or "")


def overload(text: str) -> list[str]:
    """Overload reasons for one message ([] when calm).

    Only the person's own words count (see own_words()). One reason is
    information, not overload. Callers switch to Calm only on two distinct
    reasons in one message, or a reason in two messages in a row (see calm_due()).
    """
    if not is_human_text(text):
        return []
    text = own_words(text)
    reasons = [c for c in classify(text) if c in OVERLOAD]
    if len(text.split()) >= 4 and typo_hits(text) >= 2 and typo_density(text) >= 6:
        reasons.append("typo_burst")
    return reasons


def calm_due(reasons: list[str], previous_had_reason: bool) -> bool:
    """The two-signal rule: two reasons now, or one now and one last message."""
    return len(set(reasons)) >= 2 or (bool(reasons) and previous_had_reason)
