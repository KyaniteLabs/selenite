"""Deterministic detectors for epistemic cowardice: a vague, hedged or deferential reply that avoids
committing to a position or an action the agent has the evidence and authority for.

Each detector reads one finished turn (the final message, the user's last message, the tool calls and
results of that turn, and optionally the earlier transcript) and returns Findings. It is advice only:
nothing here blocks, edits or approves anything, and no detector calls a model.

Walls are not cowardice. A flagged sentence is dropped when the fake-gate facet's wall-family net
(credentials, spend, publishing or deploying, destructive steps, legal, a named freeze, a person's role)
matches it, or when it or the user's message names a hold. The net over-matches on purpose: a missed
finding costs a nudge, a pushed wall costs a person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

try:  # inside the Hermes plugin package the sibling facet is one level up; standalone it is top-level
    from ..antibeaurocracy_core import WALLS_TEXT, wall_family
except (ImportError, ValueError):
    from antibeaurocracy_core import WALLS_TEXT, wall_family

HEDGE = "C1-hedge"                # hedging when the evidence is clear
READY = "C2-ready-to"             # "ready to X" / "suggest we X" instead of doing X
CAVEAT = "C3-caveat-exit"         # ending on a risk the agent could have fixed
NARROW = "C4-narrow-read"         # a narrow reading of a broad instruction
DEFER = "C5-false-deference"      # a question the context already answers
OVERCORRECT = "C6-over-correction"  # flipping a claim after criticism instead of narrowing it
SYCOPHANCY = "C7-sycophancy"      # agreement without checking
VAGUE = "C8-vague-status"         # "should be fine" with nothing verified
MODES = (HEDGE, READY, CAVEAT, NARROW, DEFER, OVERCORRECT, SYCOPHANCY, VAGUE)
_ACT_MODES = frozenset({READY, CAVEAT, NARROW, DEFER})  # a hold stops these; it does not make a hedge right

ADVICE = {
    HEDGE: "The evidence in this turn already settles it: state the conclusion and act on it.",
    READY: "Do the step instead of announcing it, unless it is a wall.",
    CAVEAT: "Fix the risk you named (commit it, record it, add the test) instead of ending on it.",
    NARROW: "Read the instruction at the scope it was given; finish the broad part or say why one part is a wall.",
    DEFER: "The context already answers this question: take the default and say what you did.",
    OVERCORRECT: "Narrow the earlier claim to fit the evidence; do not invert it without new evidence.",
    SYCOPHANCY: "Check the point first (read, run, diff), then agree or disagree with what you found.",
    VAGUE: "Verify it now (run the test, probe the service, read it back) and report what you saw.",
}

_I = re.I


@dataclass(frozen=True)
class ToolCall:
    name: str = ""
    args: str = ""
    output: str = ""


@dataclass
class Turn:
    assistant: str                      # the final message of the turn
    user: str = ""                      # the user's message that started it
    tools: Sequence[ToolCall] = ()      # tool calls (with results) made in this turn
    previous_assistant: str = ""        # the agent's message before the user's last one
    context: str = ""                   # earlier transcript text, for "is this already answered?"


@dataclass(frozen=True)
class Finding:
    mode: str
    phrase: str   # a short quote of the agent's own sentence; used for the in-process nudge, never ledgered
    advice: str = field(default="", compare=False)


# ---------------------------------------------------------------- text helpers

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_STOP = frozenset("""the a an and or but if then than that this these those with without from into onto over under
for are was were been being have has had not can could would should will shall may might must its our their your
there here what when where which who whom how why also just only very more most some any all each every about
after before again because while does did doing done get got make made one two""".split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(str(text or "")) if s and s.strip()]


def _words(text: str, min_len: int = 4) -> set[str]:
    """Content words by their first five letters, so "resetting" meets "reset" and "usb1-port4" meets "port"."""
    return {w[:5] for w in re.findall(r"[a-z]+", str(text or "").lower()) if len(w) >= min_len and w not in _STOP}


def _snip(s: str, n: int = 80) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# A hold the user or the sentence names. "Hold" in the sense of waiting is a wall; so is a freeze.
_HOLD = re.compile(
    r"\b(on hold|hold (off|until|for)|held|freeze|frozen|read-only|research-only|only research|"
    r"(do not|don'?t|never) (touch|change|restart|merge|deploy|delete|push|close|edit|modify|run)|"
    r"wait (for|until) (my|the|your) (ok|okay|approval|go|word|reply))\b", _I)


def _walled(sentence: str) -> bool:
    return bool(_HOLD.search(sentence)) or wall_family(sentence)


# ---------------------------------------------------------------- C1 hedging when the evidence is clear

_HEDGE_WORDS = re.compile(
    r"\b(i )?(suspect(s|ed)?|might|maybe|perhaps|possibly|probably|likely|could (be|have been)|may (be|have)|"
    r"seems? (to|like)|appears? to|i (think|believe|guess|assume))\b", _I)
# A line of tool output that states a hard fact.
_FACT = re.compile(
    r"\b(error|errors|fail(ed|s|ure)?|reset|resetting|timed? ?out|refused|denied|disconnect(ed)?|not found|"
    r"no such|panic|traceback|segfault|killed|oom|unable|invalid|exit(ed)?( with)?( code| status)? ?[1-9]|"
    r"returned [1-9]|status[: =]+[45]\d\d)\b", _I)


def _hedge(t: Turn) -> list[Finding]:
    fact_lines = [ln for c in t.tools for ln in str(c.output or "").splitlines() if _FACT.search(ln)]
    if not fact_lines:
        return []
    out = []
    for s in _sentences(t.assistant):
        if s.endswith("?") or not _HEDGE_WORDS.search(s) or _walled(s):
            continue
        subject = _words(_HEDGE_WORDS.sub(" ", s))
        if subject and any(subject & _words(ln) for ln in fact_lines):
            out.append(Finding(HEDGE, _snip(s), ADVICE[HEDGE]))
    return out


# ---------------------------------------------------------------- C2 "ready to X" instead of doing X

_READY = re.compile(
    r"\b(ready (to|for)|(i|we) (would|'d) (suggest|recommend)|(i|we) (suggest|recommend)|suggest(ed)? (we|that we)|"
    r"recommend (we|that we)|next step (is|would be) to)\s+(?:be\s+)?(?P<verb>[a-z]+)?", _I)
# Tool-call words that count as doing the step, by the first four letters of the verb.
_DONE_STEMS = {"clos": ("close", "complete", "done", "finish"), "merg": ("merge",), "comm": ("commit",),
               "ship": ("ship", "release"), "fix": ("fix", "edit", "write", "patch"),
               "arch": ("archive", "complete", "close"), "move": ("move", "update")}


def _acted(verb: str, t: Turn) -> bool:
    stems = _DONE_STEMS.get(verb[:4]) or (verb[:4],)
    blob = " ".join(f"{c.name} {c.args}" for c in t.tools).lower()
    return any(st in blob for st in stems)


def _ready(t: Turn) -> list[Finding]:
    out = []
    for s in _sentences(t.assistant):
        m = _READY.search(s)
        if not m or s.endswith("?") or _walled(s):
            continue
        verb = (m.group("verb") or "").lower()
        if len(verb) >= 3 and _acted(verb, t):
            continue
        out.append(Finding(READY, _snip(s), ADVICE[READY]))
    return out


# ---------------------------------------------------------------- C3 caveat as exit

_RISK = re.compile(
    r"\b(would (be )?(lost|overwritten|wiped)|will be (lost|overwritten|wiped)|would lose|will lose|"
    r"won'?t survive|will not survive|not (yet )?(tracked|committed|in version control|persisted|backed up|saved)|"
    r"uncommitted|untracked|(lives|exists) only|only (lives|exists)|only on|a rebuild|a reinstall|a reboot would)\b", _I)
_VCS = re.compile(r"\bgit (add|commit)\b", _I)


def _caveat(t: Turn) -> list[Finding]:
    paras = [p for p in re.split(r"\n\s*\n", str(t.assistant or "").strip()) if p.strip()]
    if not paras:
        return []
    out = []
    for s in _sentences(paras[-1]):
        if not _RISK.search(s) or s.endswith("?") or _walled(s):
            continue
        if _VCS.search(" ".join(c.args for c in t.tools)) and re.search(r"track|commit|version|control|repo", s, _I):
            continue  # the turn did commit something; the caveat is not an exit
        out.append(Finding(CAVEAT, _snip(s), ADVICE[CAVEAT]))
    return out


# ---------------------------------------------------------------- C4 narrow reading of a broad instruction

_BROAD = re.compile(r"\b(all|everything|every|each|whole|entire|any and all|noise|across)\b", _I)
_NARROWED = re.compile(
    r"\b((only|just|merely) (fixed|addressed|handled|touched|changed|removed|silenced|cleared)|"
    r"(the )?(rest|remaining|others?) (is|are|was|were|remain\w*|still|left|untouched)|"
    r"left (the )?(rest|others?|remaining)|not (touched|addressed|fixed|handled)|"
    r"(single|one) (log )?(line|file|item|warning|case))\b", _I)


def _narrow(t: Turn) -> list[Finding]:
    if not _BROAD.search(t.user or ""):
        return []
    out = []
    for s in _sentences(t.assistant):
        if _NARROWED.search(s) and not s.endswith("?") and not _walled(s):
            out.append(Finding(NARROW, _snip(s), ADVICE[NARROW]))
    return out[:1]


# ---------------------------------------------------------------- C5 false deference

_ASK = re.compile(r"\b(should i|shall i|do you want me to|would you like me to|want me to|can i|may i|is it ok(ay)? (if|to)|"
                  r"let me know (if|whether|how))\b(?P<rest>[^?.\n]*)", _I)
_GRANT = re.compile(
    r"\b(fix (it )?all|do (it|everything|all)|go ahead|just do|you decide|your call|don'?t ask|no questions|"
    r"all approved|approved|authori[sz]ed|use your judg(e)?ment|without asking|make the call)\b", _I)


def _defer(t: Turn) -> list[Finding]:
    asked = t.user or ""
    ctx = f"{t.user}\n{t.context}"
    out = []
    for s in _sentences(t.assistant):
        m = _ASK.search(s)
        if not m or _walled(s):
            continue
        verbs = _words(m.group("rest"), min_len=3)
        answered = bool(_GRANT.search(asked)) or any(
            v in _words(ctx, min_len=3) for v in verbs if len(v) >= 4 and v not in ("this", "that", "them", "with"))
        if answered:
            out.append(Finding(DEFER, _snip(s), ADVICE[DEFER]))
    return out[:1]


# ---------------------------------------------------------------- C6 over-correction after criticism

_CRITICISM = re.compile(r"\b(wrong|incorrect|not true|that'?s not|are you sure|you missed|mistake|bad|no[,.!]|nope|false)\b", _I)
_RETRACT = re.compile(
    r"\b(i was (completely |totally |entirely )?(wrong|mistaken|incorrect)|scratch that|i retract|disregard (that|my)|"
    r"(my|the) (earlier|previous|last|original|first) (claim|answer|statement|analysis|diagnosis|conclusion) was "
    r"(wrong|incorrect|false|mistaken)|the opposite is true|actually the reverse)\b", _I)
_NARROWING = re.compile(r"\b(only|except|but not|narrow\w*|in part|partly|still (true|holds|stands)|does not change|doesn'?t change|"
                        r"remains (true|valid)|part of)\b", _I)


def _overcorrect(t: Turn) -> list[Finding]:
    if not (t.previous_assistant and _CRITICISM.search(t.user or "") and not t.tools):
        return []
    for s in _sentences(t.assistant):
        if _RETRACT.search(s) and not _NARROWING.search(t.assistant) and not _walled(s):
            return [Finding(OVERCORRECT, _snip(s), ADVICE[OVERCORRECT])]
    return []


# ---------------------------------------------------------------- C7 sycophancy

_FLATTER = re.compile(
    r"^\W*(you'?re|you are) (absolutely|completely|totally|entirely|quite|so|100% )?\s*right\b|"
    r"^\W*(great|excellent|good|fantastic|wonderful|brilliant|sharp) (point|question|catch|idea|observation|call)\b|"
    r"^\W*absolutely[,!. ]|^\W*that'?s (a )?(great|excellent|fantastic) ", _I)
_VERIFY = re.compile(
    r"\b(pytest|test|check|status|curl|grep|rg|diff|cat|ls|head|tail|read|verify|probe|doctor|ping|journalctl|"
    r"git (status|diff|log|show)|--version|stat|wc|find|lint)\b", _I)


def _verified(t: Turn) -> bool:
    return any(_VERIFY.search(f"{c.name} {c.args}") for c in t.tools)


def _syco(t: Turn) -> list[Finding]:
    s = _sentences(t.assistant)
    if not s or not _FLATTER.search(s[0]) or _verified(t) or _walled(s[0]):
        return []
    return [Finding(SYCOPHANCY, _snip(s[0]), ADVICE[SYCOPHANCY])]


# ---------------------------------------------------------------- C8 vague status

_VAGUE = re.compile(
    r"\b(should be (fine|good|ok|okay|working|done|all set|resolved)|(it|that|this) (should|ought to) work|"
    r"looks? (good|fine|ok|okay|right)( to me)?|seems? (fine|good|ok|okay|to work)|probably (works|fine|ok|okay)|"
    r"good to go|all good|i think (it|that|this) works)\b", _I)


def _vague(t: Turn) -> list[Finding]:
    if _verified(t):
        return []
    for s in _sentences(t.assistant):
        if _VAGUE.search(s) and not s.endswith("?") and not _walled(s):
            return [Finding(VAGUE, _snip(s), ADVICE[VAGUE])]
    return []


_DETECTORS = ((HEDGE, _hedge), (READY, _ready), (CAVEAT, _caveat), (NARROW, _narrow), (DEFER, _defer),
              (OVERCORRECT, _overcorrect), (SYCOPHANCY, _syco), (VAGUE, _vague))


def analyze(turn: Turn) -> list[Finding]:
    """Every finding for one turn, at most a few per mode. A hold in the user's message silences the
    action modes (ready-to, caveat, narrow, deference): waiting is the right answer there."""
    if not str(turn.assistant or "").strip():
        return []
    held = bool(_HOLD.search(turn.user or ""))
    out: list[Finding] = []
    for mode, fn in _DETECTORS:
        if held and mode in _ACT_MODES:
            continue
        out.extend(fn(turn)[:2])
    return out


def nudge_text(findings: Iterable[Finding]) -> str:
    """The context note for the agent's next turn. Quotes its own sentences back, nothing else."""
    findings = list(findings)
    if not findings:
        return ""
    lines = [f"- {f.mode}: \"{f.phrase}\" -> {f.advice}" for f in findings[:4]]
    return ("[selenite] anticowardice: your last reply held back where the evidence and your authority were enough.\n"
            + "\n".join(lines)
            + "\nIf you now have grounds, commit to the position or do the step and say what you did. Walls still stand "
              "and still get one short question: " + WALLS_TEXT + ".")
