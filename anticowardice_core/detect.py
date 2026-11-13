"""Deterministic detectors for epistemic cowardice: a vague, hedged or deferential reply that avoids
committing to a position or an action the agent has the evidence and authority for.

Each detector reads one finished turn (the final message, the user's last message, the tool calls and
results of that turn, and optionally the earlier transcript) and returns Findings. It is advice only:
nothing here blocks, edits or approves anything, and no detector calls a model.

Walls are not cowardice. The stop check has one source of truth, the fake-gate facet: its strict
classifier (an authority wall, or a wait on a named person) and, for the sentence itself, its loose
wall-family net (credentials, spend, publishing or deploying, destructive steps, legal, a freeze, a
person's role). That facet judges whether a wait is fake, so it calls "waiting for sign-off" with no
named person fake; it has no word for the holds a user gives ("please hold", "plan only", "what do you
recommend?"). `_HOLD` covers only that gap. A flagged sentence is dropped when the sentence, or the one
before or after it, trips the check, or when the user's message (or their recent messages) names a hold.
The net over-matches on purpose: a missed finding costs a nudge, a pushed wall costs a person.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

try:  # inside the Hermes plugin package the sibling facet is one level up; standalone it is top-level
    from ..antibeaurocracy_core import HUMAN, WALL, WALLS_TEXT, classify, wall_family
    from ..antibeaurocracy_core.classify import _WALL_FAMILY_ACTION
except (ImportError, ValueError):
    from antibeaurocracy_core import HUMAN, WALL, WALLS_TEXT, classify, wall_family
    from antibeaurocracy_core.classify import _WALL_FAMILY_ACTION

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
_GENERIC = frozenset({"error", "faile", "failu", "fails", "timed", "refus", "denie", "inval", "unabl", "panic"})
_CODE = re.compile(r"```.*?(```|\Z)|~~~.*?(~~~|\Z)|`[^`\n]+`|^[ \t]*>.*$|^(?: {4}|\t).*$", re.S | re.M)
_QUOTED = re.compile(r"\"[^\"\n]{1,1000}\"|“[^”\n]{1,1000}”|(?<![\w'])'[^'\n]{1,1000}'(?![\w'])")


def _clean(text) -> str:
    """The agent's own words: code blocks, inline code and quoted spans are mentions, not claims."""
    return _QUOTED.sub(" ", _CODE.sub(" ", str(text or "")))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(str(text or "")) if s and s.strip()]


def _words(text: str, min_len: int = 4) -> set[str]:
    """Content words by their first five letters, so "resetting" meets "reset" and "usb1-port4" meets "port"."""
    return {w[:5] for w in re.findall(r"[a-z]+", str(text or "").lower()) if len(w) >= min_len and w not in _STOP}


def _snip(s: str, n: int = 80) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


_NEG_BEFORE = re.compile(r"\b(not|never|no longer|isn'?t|aren'?t|wasn'?t|won'?t|don'?t|doesn'?t|didn'?t|cannot|can'?t|"
                         r"without|nothing|no|zero|n'?t)[^\w,;.:!?]+(\w+[^\w,;.:!?]+){0,2}\Z", re.I)


def _negated(text: str, start: int) -> bool:
    """True when a negator sits just before text[start:]."""
    return bool(_NEG_BEFORE.search(text[max(0, start - 28):start]))


# ---------------------------------------------------------------- the stop check (walls and holds)

# What the fake-gate classifier has no word for: a hold, a wait on a person, or a request that only wants
# advice or analysis. It judges whether a wait is fake; this judges whether the agent should stop.
_HOLD = re.compile(
    r"\b(on hold|hold (off|until|for|on|everything)|please hold|(?<!\w)hold\.?$|freeze|frozen|(?<!is )(?<!are )(?<!was )(?<!went )read-?only|research-?only|"
    r"only research|(advice|analysis|diagnosis|plan|review|report)[- ]only|"
    r"just (diagnose|investigate|explain|plan|look|research|review|advise|report|tell|check)|"
    r"no (changes|edits|writes|actions?)|don'?t (do )?anything|do not do anything|nothing (should|is to|to) (move|change|happen)|"
    r"(do not|don'?t|never|must not|mustn'?t|not to) (touch|change|restart|merge|deploy|delete|push|close|edit|modify|run|commit|"
    r"send|install|rename|write|stop(?! (until|before|till))|reboot|migrate|restore|upload|publish|release|ship|remove|apply|start|kill|update|create|"
    r"act|move|proceed|continue|go ahead|fix|ship|tag|post|email|reset|drop|wipe)|"
    r"wait(ing|s|ed)? until\b|"
    r"wait(ing|s|ed)? (for|on) ([\w']+ ){0,3}(approval|sign-?off|go-?ahead|green-?light|decision|ok|okay|review|confirmation|reply|response|"
    r"answer|word|permission|consent|say-?so)|wait(ing|s|ed)? (for|on) [\w']+ to (confirm|approve|reply|respond|sign|review|decide|say|ok|lift|"
    r"land|merge|finish|clear)|"
    r"(blocked|parked|paused|held|stalled|pending) (on|pending|until|by|as|per)\b|pending (approval|review|"
    r"sign-?off|a decision|the)|awaiting|(need|needs|needed|require|requires|required|pending|without|until|after|for|from|"
    r"before) ([\w']+ ){0,3}(sign-?off|go-?ahead|green-?light)|[\w]+'s (sign-?off|go-?ahead)|"
    r"your (ok|okay|approval|word|say-?so)|"
    r"(requires?|needs?) (the )?(\w+'?s? )?(approval|sign-?off|consent|permission|ok|okay)|"
    r"(once|when|after|until) (you|he|she|they|\w+) (say|says|approve|approves|confirm|confirms|ok|signs?|lifts?|opens?|lands?)|"
    r"(once|when|after|until) (the )?[\w' -]{1,40} (lands?|merges?|approves?|signs? off|clears?|finishes|ships|lifts?)|"
    r"(no|any) (further|more) \w+ until|until the [\w.]+ (window|freeze|review|lifts|opens|ships|lands)|"
    r"what do you (recommend|suggest|think)|your (recommendation|advice|opinion)|any (suggestions|recommendations|thoughts)|"
    r"(do you|would you) (recommend|suggest)|how (would|should|could) (you|i|we)|(give|write|draft|propose) me (a |an )?(plan|proposal|approach|outline)|"
    r"walk me through|what would you do)\b", _I)
# Phrases that hold only when the user says them; an agent's "not committed yet" is a state, not a stop.
_ADVICE_ASK = re.compile(r"what do you|your (recommendation|advice|opinion)|any (suggestions|recommendations|thoughts)|(do you|would you) (recommend|suggest)|"
                         r"how (would|should|could)|(give|write|draft|propose) me|walk me through|what would you do", _I)
_USER_HOLD = re.compile(r"\b((not|n'?t) \w+( \w+)? yet|for now|later (today|tonight|this \w+))\b", _I)
# Publishing and release steps the sibling facet's wall list has no word for.
_EXTRA_WALL = re.compile(r"\b(tag(ging)? (and|&) release|release (tag|v?\d)|registry|visib(le|ility)|go(ing)? public|"
                         r"make \w+ public|upstream|pypi|npm publish)\b", _I)
_ASK_PHRASE = re.compile(r"\b(should (i|we)|shall (i|we)|do you want me|want me to|would you like me|may i|can i|"
                         r"is it ok|ok(ay)? to proceed|let me know|your (call|decision|choice|preference)|which (do|would) you)\b", _I)
_GATE_CACHE: dict = {}


def _verdict(sentence: str):
    key = sentence[:400]
    if key not in _GATE_CACHE:
        if len(_GATE_CACHE) > 2048:
            _GATE_CACHE.clear()
        try:
            v = classify(key)
            _GATE_CACHE[key] = (v.cls == WALL, v.cls == HUMAN and any(not _ASK_PHRASE.search(m) for m in v.matched))
        except Exception:  # the classifier is a dependency; if it breaks, do not nudge
            _GATE_CACHE[key] = (True, True)
    return _GATE_CACHE[key]


def _gate(sentence: str) -> bool:
    """The fake-gate classifier's strict verdict: an authority wall, or a wait on a named person.
    A bare question to a person (HUMAN by its own rules) is not a stop here: C5 is about those."""
    wall, human = _verdict(sentence)
    return wall or human


def _strict(sentence: str) -> bool:
    return bool(_HOLD.search(sentence) or _EXTRA_WALL.search(sentence) or _gate(sentence))


_MONEY = re.compile(r"[$€£]\s?\d|\b\d+k?\s?(usd|eur|dollars)\b", _I)


_LIVE_NOUN = re.compile(r"\b(production|prod|credentials?|secrets?|tokens?|passwords?|api keys?|host-b)\b", _I)


def _loose_wall(sentence: str) -> bool:
    """The sibling facet's noun net matches "auth.py", "the users page" and any 3-digit number, so on its own it
    swallows ordinary work. Here it counts only with a destructive or publishing verb on a live target, or money."""
    return bool(_MONEY.search(sentence) or (wall_family(sentence) and (_WALL_FAMILY_ACTION.search(sentence) or _LIVE_NOUN.search(sentence))))


_LINK = re.compile(r"\b(after|once|until|when|then|afterwards|following|pending|that|those|them|it|this|these|first|before|so|because|but)\b", _I)


def _linked(here: str, neighbour: str) -> bool:
    """A wall next door protects a sentence that refers back to it ("I'll proceed after.") or shares its subject.
    "Blocked on the CEO for the deploy sign-off. Meanwhile I'll write the runbook tests." is independent work."""
    return bool(_LINK.search(here) or len(_words(here) & _words(neighbour)) >= 1 or len(here.split()) <= 4)


def _walled(sents: Sequence[str], i: int, loose: bool = True) -> bool:
    """Is sentence i a stop, or next to one? A wall or a hold in the sentence before or after counts.
    Action modes also use the loose wall-family net on the sentence itself; the rest use the strict check."""
    here = sents[i]
    if _strict(here) or (loose and _loose_wall(here)):
        return True
    return any(_strict(sents[j]) and _linked(here, sents[j]) for j in (i - 1, i + 1) if 0 <= j < len(sents))


_APPROVED = re.compile(r"\b(approved|signed off|(has|have|had|gave|given|got) (my |the |his |her |their )?(sign-?off|approval|go-?ahead|ok|okay)|"
                       r"you have (my|the) |no (sign-?off|approval|permission)s? (is |are )?(needed|required|necessary)|not (needed|required))\b", _I)
_NUDGE_BLOCK = re.compile(r"\[selenite\] anticowardice:[^\n]*\n(?:- [^\n]*\n)*If you now have grounds[^\n]*")


def _hard_hold(text: str, advice: bool = True) -> bool:
    """A _HOLD phrase that is not itself negated ("no need to wait for approval" is not a hold). A request for
    advice only holds the message that asked; with advice=False (earlier messages) it is ignored."""
    return any(not _negated(text, m.start()) and (advice or not _ADVICE_ASK.search(m.group(0)))
               for m in _HOLD.finditer(text or ""))


def _user_hold(t: "Turn") -> bool:
    """A hold, a request for advice only, or a named person's sign-off in the user's message or their
    recent earlier messages. The user naming a wall word (deploy, credentials) is a request, not a hold.
    A grant in the same message beats a hold phrase in it, and beats anything said earlier."""
    user = t.user or ""
    if any(_verdict(x)[1] and not (_APPROVED.search(x) or _granted(x)) for x in _sentences(user)):  # a person must still say yes
        return True
    if _granted(user):
        return False
    if _hard_hold(user) or any(_USER_HOLD.search(x) for x in _sentences(user) if not x.rstrip().endswith("?")):  # a question about "for now" is not a stop
        return True
    return _hard_hold(_NUDGE_BLOCK.sub(" ", (t.context or "")[-1500:]), advice=False)  # only hard holds outlive their message


# ---------------------------------------------------------------- C1 hedging when the evidence is clear

_HEDGE_WORDS = re.compile(
    r"\b(i )?(suspect(s|ed)?|might|maybe|perhaps|possibly|probably|likely|presumably|i'?d say|my (?:guess|bet) is|could (be|have been)|may (be|have)|"
    r"seems? (to|like)|appears? to|i (think|believe|guess|assume))\b", _I)
# A line of tool output that states a hard fact.
_FACT = re.compile(
    r"\b(error|errors|fail(ed|s|ure)?|reset|resetting|timed? ?out|refused|denied|disconnect(ed)?|not found|"
    r"no such|panic|traceback|segfault|killed|oom|unable|invalid|exit(ed)?( with)?( code| status)? ?[1-9]|"
    r"returned [1-9]|status[: =]+[45]\d\d|http\W+(\d\.\d\W+)?[45]\d\d)\b", _I)
_ZERO_FACT = re.compile(r"\b(0|no|zero|without|none)\s+(\w+\s+)?(errors?|fail(ed|ures?|s)?|warnings?)\b|"
                        r"\b(errors?|fail(ed|ures?)?)\s*[:=]\s*0\b|\b0 (errors?|failed)\b", _I)
# The sentence itself says the question is open: honest uncertainty, not a hedge past the evidence.
_OPEN = re.compile(r"\b(have not|haven'?t|did not|didn'?t|not yet|cannot|can'?t|could not|couldn'?t) (been )?(tested|test|"
                   r"confirmed|confirm|verified|verify|checked|check|tell|determined|determine|reproduced|reproduce|identified|identify)|"
                   r"(not|n'?t|never) (tested|confirmed|verified|checked|measured|known|identif\w+)|unverified|untested|unconfirmed|"
                   r"not sure|unknown|no evidence|does not (say|show|identify|tell|name)|doesn'?t (say|show|identify|tell|name)|"
                   r"will tell|would tell|to be (seen|confirmed|determined)|\bor\b", _I)


# A cause is not in a log that only shows the symptom: a hedged "because"/"causing" is an inference, not a stalled fact.
_CAUSAL = re.compile(r"\b(caus(e|es|ed|ing)|because|due to|root cause|result of|responsible for|explains?|behind (this|that|it|the))\b", _I)


def _hedge(t: Turn, sents: list[str]) -> list[Finding]:
    fact_words = [_words(ln) - _GENERIC for c in t.tools for ln in str(c.output or "").splitlines()
                  if _FACT.search(ln) and (not _ZERO_FACT.search(ln) or _FACT.search(_ZERO_FACT.sub(" ", ln)))]
    if not fact_words:
        return []
    out = []
    for i, s in enumerate(sents):
        if s.endswith("?") or not _HEDGE_WORDS.search(s) or _OPEN.search(s) or _CAUSAL.search(s) or _walled(sents, i, loose=False):
            continue
        subject = _words(_HEDGE_WORDS.sub(" ", s)) - _GENERIC
        if subject and any(subject & fw for fw in fact_words):
            out.append(Finding(HEDGE, _snip(s), ADVICE[HEDGE]))
    return out


# ---------------------------------------------------------------- C2 "ready to X" / "I'll X" instead of doing X

_ACTION_VERBS = (r"close|complete|finish|merge|commit|ship|release|deploy|publish|push|tag|fix|patch|archive|move|update|add|"
                 r"remove|delete|write|run|rerun|start|restart|proceed|implement|apply|migrate|rename|create|send|install|"
                 r"retry|resolve|address|land|pin|bump|revert|open|submit|sync|clean|check|test|verify|file|record|document|"
                 r"look (?:into|at)|investigate|dig into|follow up|get back|report back")
_READY = re.compile(
    r"\b(?:ready to|(?:i|we) (?:would|'d) (?:suggest|recommend)|(?:i|we) (?:suggest|recommend)|suggest(?:ed)? (?:that )?we|"
    r"recommend (?:that )?we|next step (?:is|would be) to|(?:i|we)(?:'ll| will| shall)|(?:i|we)(?: am|'m|'re| are) (?:going|about|planning) to|"
    r"(?:i|we) (?:should|need to|have to|must)(?: probably)?|let me(?! know)(?: go ahead and)?|going to|next,? (?:i|we)(?:'ll| will)|"
    rf"planning to)\s+(?:be\s+|go ahead and\s+|now\s+|also\s+|then\s+)?(?P<verb>{_ACTION_VERBS})\b", _I)
# Tool-call words that count as doing the step, by the first letters of the verb.
_DONE_STEMS = {"clos": ("close", "complete", "done", "finish"), "merg": ("merge",), "comm": ("commit",),
               "ship": ("ship", "release"), "fix": ("fix", "edit", "write", "patch"),
               "arch": ("archive", "complete", "close"), "move": ("move", "mv", "update"),
               "run": ("run", "pytest", "test", "make", "unittest"), "test": ("test", "pytest"),
               "chec": ("check", "test", "pytest", "diff", "status", "read", "view", "grep", "glob", "tail"),
               "look": ("look", "read", "view", "grep", "glob"), "inve": ("investigate", "read", "view", "grep", "test"), "veri": ("verify", "test", "pytest", "diff"),
               "upda": ("update", "edit", "write", "patch"), "add": ("add", "edit", "write"),
               "writ": ("write", "edit"), "comp": ("complete", "close", "done")}
_SHELL = re.compile(r"(bash|shell|terminal|exec|command|run_command|sh)$", _I)
# Commands that look at or print things; naming a verb in their arguments is not doing it.
_PASSIVE_HEADS = frozenset("echo printf rg grep egrep ag ack cat ls head tail find less more wc stat file which type pwd date".split())
_PASSIVE_NAMES = re.compile(r"(comment|note|search|memory|todo|message|say|send_message|respond|log)", _I)


def _command(c: ToolCall) -> str:
    args = str(c.args or "")
    m = re.search(r'"(?:command|cmd|script)"\s*:\s*"((?:[^"\\]|\\.)*)"', args)
    return m.group(1).replace("\\n", "\n") if m else args


def _heads(cmd: str) -> list[list[str]]:
    """Each simple command of a shell line as its words."""
    masked = re.sub(r"\"[^\"]*\"|'[^']*'", lambda m: "Q" * len(m.group(0)), cmd)  # a quoted ; or && is text, not a separator
    segs, pos = [], 0
    for m in re.finditer(r"&&|\|\||[;|\n]", masked):
        segs.append(cmd[pos:m.start()])
        pos = m.end()
    segs.append(cmd[pos:])
    return [seg.split() for seg in segs if seg.strip()]


_PASSIVE_SUBS = frozenset(("view", "list", "checks", "status", "diff", "show", "log", "blame", "ls", "search", "get", "inspect"))


def _passive(words: list[str]) -> bool:
    if not words:
        return True
    head = words[0].rsplit("/", 1)[-1].lower()
    if head in ("git", "gh", "glab", "fj", "tea") and len(words) > 1:
        return any(w.lower() in _PASSIVE_SUBS for w in words[1:3])
    return head in _PASSIVE_HEADS


def _action_tokens(t: Turn) -> set[str]:
    """Lower-case word tokens of what the turn's tool calls actually did, not what they mention. For a
    shell line that is each command's name and its next two words (so `gh pr merge`, `python3 -m pytest`),
    never its free text or comments; for any other tool it is the tool's name, never its arguments."""
    toks: set[str] = set()
    for c in t.tools:
        name = str(c.name or "")
        if _SHELL.search(name) or name.lower() in ("bash", "terminal"):
            for words in _heads(re.sub(r"\s#.*", "", _command(c))):
                if not _passive(words):
                    toks.update(re.findall(r"[a-z]+", " ".join(words[:3]).lower()))
        elif not _PASSIVE_NAMES.search(name):
            toks.update(re.findall(r"[a-z]+", name.lower()))
    return toks


def _forms(stem: str) -> set[str]:
    return {stem, stem + "s", stem + "es", stem + "d", stem + "ed", stem + "ing", stem.rstrip("e") + "ing", stem.rstrip("e") + "ed"}


_EDIT_STEMS = frozenset(("edit", "write", "patch", "update", "add", "fix", "move", "mv"))
_OBJ_SKIP = frozenset(("also", "again", "well", "next", "first", "later", "then", "just", "that", "this", "these", "those", "them", "there"))


def _acted(verb: str, t: Turn, sent: str = "") -> bool:
    """Did a tool call do this verb? A generic Edit/Write only counts for an announcement whose object it touched:
    "Ready to fix the docs too." is not answered by an edit of src/main.py."""
    stems = _DONE_STEMS.get(verb[:4]) or _DONE_STEMS.get(verb[:3]) or (verb[:4],)
    toks = _action_tokens(t)
    hit = {tok for tok in toks for st in stems if tok in _forms(st)}
    if not hit:
        return False
    if sent and hit <= _EDIT_STEMS:
        after = sent.lower().split(verb, 1)[-1]
        obj = _words(after) - _OBJ_SKIP
        if obj:
            touched = _words(" ".join(str(c.args or "") for c in t.tools if not _SHELL.search(str(c.name or ""))))
            return bool(obj & touched)
    return True


_REPORTED = re.compile(r"\b(says?|said|according to|states?|stated|notes?|noted|claims?|claimed|reports?|reported|docs?|documentation|changelog|readme|spec|guide)\b", _I)
_COND = re.compile(r"^\W*(if|unless|when|once|in case)\b", _I)


def _ready(t: Turn, sents: list[str]) -> list[Finding]:
    out = []
    for i, s in enumerate(sents):
        m = _READY.search(s)
        if not m or s.endswith("?") or _COND.search(s) or _negated(s, m.start()) or _walled(sents, i):
            continue
        if m.group(0).lower().startswith("going to") and s[:m.start()].strip(" \"'-\u2014*_"):
            continue  # "The release is going to ship Thursday" describes the future; only a sentence that opens with it promises
        if _REPORTED.search(s[:m.start()]):
            continue  # "The docs say we should update the flag" reports what someone else said
        if _acted(m.group("verb").lower(), t, s):
            continue
        out.append(Finding(READY, _snip(s), ADVICE[READY]))
    return out


# ---------------------------------------------------------------- C3 caveat as exit

_RISK = re.compile(
    r"\b(would (be )?(lost|overwritten|wiped)|will be (lost|overwritten|wiped)|would lose|will lose|"
    r"won'?t survive|will not survive|(?:not|isn'?t|aren'?t|wasn'?t|hasn'?t been|haven'?t been) (yet )?(tracked|committed|in version control|persisted|backed up|saved)|"
    r"uncommitted|untracked|(lives|exists|stored|saved|kept) only (on|in)|"
    r"a (rebuild|reinstall|reboot) (would|will) (lose|wipe|erase|undo|revert|reset|clear|overwrite))\b", _I)
_SIGNOFF = re.compile(r"^(?:[-\u2014\u2013]+\s*\w[\w .]*$|(?:let me know|thanks|thank you|hope|cheers|happy to)\b[^\n]{0,120}$)", _I)
_COMMIT = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b", _I)


def _did_commit(t: Turn) -> bool:
    """A shell line that runs `git commit` (any global options before it), not one that mentions the word."""
    for c in t.tools:
        if _SHELL.search(str(c.name or "")) or str(c.name or "").lower() in ("bash", "terminal"):
            for w in _heads(_command(c)):
                if w and w[0].rsplit("/", 1)[-1].lower() == "git" and "commit" in [x.lower() for x in w[1:5] if not x.startswith("-") or x == "-m"][:2]:
                    return True
    return False


def _caveat(t: Turn, sents: list[str]) -> list[Finding]:
    paras = [p for p in re.split(r"\n\s*\n", _clean(t.assistant).strip()) if p.strip()]
    if not paras:
        return []
    committed = _did_commit(t)
    out = []
    # Walls are judged against the whole reply, so a wall in the paragraph above or below still counts.
    flat: list[str] = []
    spans: list[tuple[int, int]] = []
    for para in paras:
        ps = _sentences(para)
        spans.append((len(flat), len(flat) + len(ps)))
        flat.extend(ps)
    tail = [len(paras) - 1]
    i = len(paras) - 1
    while i > 0 and len(tail) < 3 and _SIGNOFF.match(paras[i].strip()):  # a sign-off can follow the caveat
        i -= 1
        tail.append(i)
    for pi in tail:
        for j in range(*spans[pi]):
            s = flat[j]
            m = _RISK.search(s)
            if not m or s.endswith("?") or _walled(flat, j) or _negated(s, m.start()):
                continue
            if committed:
                continue  # the turn did commit something; the caveat is not an exit
            out.append(Finding(CAVEAT, _snip(s), ADVICE[CAVEAT]))
    return out[:2]


# ---------------------------------------------------------------- C4 narrow reading of a broad instruction

_BROAD = re.compile(r"\b(all|everything|every|each|whole|entire|any and all|noise)\b", _I)
_USER_NARROW = re.compile(r"\b(only|just(?! (\w+ )?(all|everything|every|each)\b)|first (one|file|item|few|two|three|\d|warning|error|issue|failure|test|bug)|instead|except|"
                          r"leave (the )?(rest|others?|remaining|everything else)|skip everything else|ignore (every|all) other|ignore (\w+ ){1,3}(and|,) ?(just )?(fix|do|handle|address)|not all|rather than|"
                          r"don'?t (fix|touch|change) (all|everything))\b", _I)
_NARROWED = re.compile(
    r"\b((only|just|merely) (fixed|addressed|handled|touched|changed|removed|silenced|cleared)|"
    r"(the )?(rest|remaining|others?) (is|are|was|were|remain\w*|still|left|untouched)|"
    r"left (the )?(rest|others?|remaining)|not (touched|addressed|fixed|handled))\b", _I)
_NARROW_SINGLE = re.compile(r"\b(only|just) (a |the )?(single|one) (log )?(line|file|item|warning|case)\b", _I)


def _broad_user(user: str) -> bool:
    for m in _BROAD.finditer(user or ""):
        if not _negated(user, m.start()):
            return True
    return False


def _narrow(t: Turn, sents: list[str]) -> list[Finding]:
    if not _broad_user(t.user) or _USER_NARROW.search(t.user or ""):
        return []
    out = []
    for i, s in enumerate(sents):
        if (_NARROWED.search(s) or _NARROW_SINGLE.search(s)) and not s.endswith("?") and not _walled(sents, i):
            out.append(Finding(NARROW, _snip(s), ADVICE[NARROW]))
    return out[:1]


# ---------------------------------------------------------------- C5 false deference

_ASK = re.compile(r"\b(should (i|we)|shall (i|we)|do you want me to|would you like me to|want me to|can i|may i|is it ok(ay)? (if|to))\b"
                  r"(?P<rest>[^?.\n]*)", _I)
_GRANT = re.compile(
    r"(?:^|[;:.,]\s*)(?:so )?(?:fix|update|add|implement|run|write|finish)\b|\bstop waiting|\bact on your|\b(?:has |have )?come through|\bcame through|"
    r"\bjust (?:close|fix|ship|merge|update|run|finish)\b|\b(fix (it )?(all|everything)|do (it|everything|all)|go[- ]?ahead|you have (my|the) (sign-?off|approval|ok|okay)|"
    r"(now|meanwhile|in the meantime),? (close|fix|update|add|run|write|change|finish|merge|ship|commit|do|go)|just do|you decide|your call|(hold|freeze|block|lock|embargo|wall) (is |has been |was )?(lifted|over|ended|removed|cleared)|lifted the (hold|freeze)|"
    r"carry on|resume|you may proceed|don'?t ask|no questions|"
    r"all approved|use your judg(e)?ment|without asking|make the call|do whatever you (think|want|like)|"
    r"whatever you think (is )?best|up to you)\b", _I)
_NOT_YET = re.compile(r"^\W*(yet|first|until|only|but|after|once|when|unless)\b", _I)


_CONDITIONAL = re.compile(r"\b(only after|after i|until|unless|once i|when i|before i)\b", _I)


def _granted(text: str) -> bool:
    for m in _GRANT.finditer(text or ""):
        if (not _negated(text, m.start()) and not _NOT_YET.match(text[m.end():m.end() + 8])
                and not _CONDITIONAL.search(text[m.end():m.end() + 40])):
            return True
    return False


def _grant_covers(asked: str, verbs: set[str]) -> bool:
    """A blanket grant ("go ahead", "fix everything") answers any question; a scoped one ("go ahead and read the
    logs") only answers questions about its own words."""
    for sent in _sentences(asked):
        for m in _GRANT.finditer(sent):
            if _negated(sent, m.start()) or _NOT_YET.match(sent[m.end():m.end() + 8]):
                continue
            tail = re.split(r"[;,:]", sent[m.end():])[0]  # what the grant is about runs to the end of its clause
            left = _words(tail, min_len=3) - {"best", "good", "fine", "please", "just", "then", "whatever", "anything", "judgment", "judgement"}
            if not left or left & verbs:
                return True
    return False


def _defer(t: Turn, sents: list[str]) -> list[Finding]:
    asked = f"{t.user or ''}\n{(t.context or '')[-1500:]}"
    user_words = _words(f"{t.user or ''}\n{t.context or ''}", min_len=3)
    out = []
    for i, s in enumerate(sents):
        m = _ASK.search(s)
        if not m or _walled(sents, i):
            continue
        rest = m.group("rest")
        if re.match(r"\s*(get|see|know|understand|explain|show|clarify|ask|find|hear)\b", rest, _I):
            continue  # "Can I get more detail" asks for information, not permission
        verbs = {w for w in _words(rest, min_len=3) if w not in ("this", "that", "them", "with")}
        if re.search(r"\bor\b", rest, _I):
            # A real choice unless the user already picked one side ("use blue" before "blue or green?").
            now = _words(t.user, min_len=3)
            picked = any(len({_words(a, 3).pop() if _words(a, 3) else a, _words(b, 3).pop() if _words(b, 3) else b} & now) == 1
                         for a, b in re.findall(r"(\w+) or (\w+)", rest, _I))
            if not picked:
                continue
        shared = verbs & user_words
        first = next(iter(_words(rest.split()[0] if rest.split() else "", min_len=3)), "")
        # Answered means a grant that covers this question, or the user asked for this very thing: the question's
        # verb and its object both appear in the user's own words. One shared noun is topic overlap, not an answer.
        if _grant_covers(asked, verbs) or (len(shared) >= 2 and first in user_words):
            out.append(Finding(DEFER, _snip(s), ADVICE[DEFER]))
    return out[:1]


# ---------------------------------------------------------------- C6 over-correction after criticism

_CRITICISM = re.compile(r"(\b(wrong|incorrect|not true|that'?s not|are you sure|you missed|mistake|bad|nope|false)\b|"
                        r"(?<!\w)no(?=[,.!]|\s*$))", _I)
_RETRACT = re.compile(
    r"\b(i was (completely |totally |entirely )?(wrong|mistaken|incorrect)|scratch that|i retract|disregard (that|my)|"
    r"(my|the) (earlier|previous|last|original|first) (claim|answer|statement|analysis|diagnosis|conclusion) was "
    r"(wrong|incorrect|false|mistaken)|the opposite is true|actually the reverse)\b", _I)
_NARROWING = re.compile(r"\b(only|except|but not|narrow\w*|in part|partly|still (true|holds|stands)|does not change|doesn'?t change|"
                        r"remains (true|valid)|part of)\b", _I)
# The criticism brings its own correction, or the retraction cites what it re-read: that is evidence.
_EVIDENCE = re.compile(r"\b(re-?read(ing)?|re-?ran|re-?check(ed|ing)?|looking (back )?at|last turn|the (log|trace|output|diff|file|test)s? "
                       r"(show|says?|confirm)s?|according to|you (said|showed|pointed))\b", _I)


def _user_supplies(user: str) -> bool:
    """The criticism brings its own correction: several content words beyond the complaint itself.
    Length, digits and punctuation are not evidence."""
    rest = _words(_CRITICISM.sub(" ", user or "")) - {"again", "think", "really", "sure", "know", "better", "should", "completely", "totally"}
    return bool(re.search(r"\d|=|`", user or "")) or len(rest) >= 3


def _overcorrect(t: Turn, sents: list[str]) -> list[Finding]:
    if not (t.previous_assistant and _CRITICISM.search(t.user or "") and not t.tools):
        return []
    if _user_supplies(t.user) or _EVIDENCE.search(t.assistant):
        return []
    for i, s in enumerate(sents):
        if _RETRACT.search(s) and not _NARROWING.search(t.assistant) and not _walled(sents, i, loose=False):
            return [Finding(OVERCORRECT, _snip(s), ADVICE[OVERCORRECT])]
    return []


# ---------------------------------------------------------------- C7 sycophancy

_FLATTER = re.compile(
    r"^\W*(you'?re|you are) (absolutely|completely|totally|entirely|quite|so|100% )?\s*right\b|"
    r"^\W*(great|excellent|good|fantastic|wonderful|brilliant|sharp) (point|catch|idea|observation|call)\b|"
    r"^\W*absolutely(?!\s+not\b)[,!. ]|^\W*that'?s (a )?(great|excellent|fantastic) (point|catch|idea|observation|call)", _I)
# Tools that only read: a read-back is a check.
_READ_TOOLS = re.compile(r"^(read|read_file|view|open|cat|grep|glob|search_files|search|find|list_dir|ls_files|web_fetch|fetch)$", _I)
# Commands that only look, whatever their arguments.
_VERIFY_HEADS = frozenset(("pytest unittest tox lint ruff mypy eslint tsc diff cmp stat wc ping dig nc ss journalctl curl wget "
                           "cat head tail sha256sum md5sum jq grep egrep rg ag").split())
# Commands that look or change depending on the subcommand: only these subcommands check anything.
_VERIFY_SUBS = {
    "npm": ("test", "run test", "run lint", "run check", "run build", "t", "build"), "pnpm": ("test", "lint", "check", "build", "run test", "run lint"),
    "yarn": ("test", "lint", "check", "build", "run test", "run lint"), "make": ("", "test", "check", "lint", "verify", "ci", "build", "all"),
    "cargo": ("test", "check", "clippy", "build", "doc"), "go": ("test", "vet", "build"),
    "systemctl": ("status", "is-active", "is-enabled", "is-failed", "show", "list-units"), "docker": ("ps", "logs", "inspect", "compose ps", "compose logs"),
    "kubectl": ("get", "describe", "logs", "rollout status"), "mvn": ("test", "verify"), "gradle": ("test", "check", "build"),
    "nix": ("flake check", "build"), "python3": ("-m pytest", "-m unittest", "-m compileall", "-m doctest"),
    "python": ("-m pytest", "-m unittest", "-m compileall", "-m doctest"), "uv": ("run pytest", "run python -m pytest"),
    "node": ("--check", "--test", "-c"), "npx": ("tsc", "eslint", "jest", "vitest"), "ruby": ("-c",),
}
_VERIFY_TOKENS = re.compile(r"\b(pytest|--version|doctor|verify|probe|lint|unittest)\b", _I)


def _verified(t: Turn) -> bool:
    for c in t.tools:
        name = str(c.name or "")
        if _READ_TOOLS.match(name):
            return True
        if _SHELL.search(name) or name.lower() in ("bash", "terminal"):
            for words in _heads(_command(c)):
                if not words:
                    continue
                head = words[0].rsplit("/", 1)[-1].lower()
                if head == "git" and len(words) > 1 and words[1].lower() in ("status", "diff", "log", "show"):
                    return True
                if head in _VERIFY_SUBS:
                    rest = " ".join(w.lower() for w in words[1:] if not w.startswith("-") or head in ("python", "python3", "node", "ruby"))
                    if any(rest == sub or rest.startswith(sub + " ") for sub in _VERIFY_SUBS[head]):
                        return True
                elif head in _VERIFY_HEADS or _VERIFY_TOKENS.search(" ".join(words)):
                    return True
    return False


def _syco(t: Turn, sents: list[str]) -> list[Finding]:
    if not sents or not _FLATTER.search(sents[0]) or _verified(t) or _walled(sents, 0, loose=False):
        return []
    # Agreeing with a fact the user just stated, in the user's own words, has nothing to check.
    m = _FLATTER.search(sents[0])
    if re.match(r"^\W*absolutely", sents[0], _I) and (t.user or "").rstrip().endswith("?"):
        return []  # "Absolutely, it is deployed" answers a question; it does not flatter a claim
    rest = _words(sents[0][m.end():]) | (_words(sents[1]) if len(sents) > 1 and sents[0].rstrip().endswith(("—", "-", ":")) else set())
    if len(rest & _words(t.user)) >= 2:
        return []
    return [Finding(SYCOPHANCY, _snip(sents[0]), ADVICE[SYCOPHANCY])]


# ---------------------------------------------------------------- C8 vague status

_BASIS = re.compile(r"\d|\b(green|passing|passed|ci|confirmed|verified|line)\b", _I)  # the sentence cites what it saw
_VAGUE = re.compile(
    r"\b(should be (fine|good|ok|okay|working|done|all set|resolved)|(it|that|this|everything) (should|ought to) (work|do it)|no reason (it|this|that) (should ?n'?t|wouldn'?t) work|"
    r"looks? (good|fine|ok|okay|right)( to me)?|seems? (fine|good|ok|okay|to work)|probably (works|fine|ok|okay)|"
    r"good to go|all good|i think (it|that|this) works)\b", _I)


def _vague(t: Turn, sents: list[str]) -> list[Finding]:
    if _verified(t):
        return []
    for i, s in enumerate(sents):
        if _VAGUE.search(s) and not _BASIS.search(s) and not s.endswith("?") and not _walled(sents, i, loose=False):
            return [Finding(VAGUE, _snip(s), ADVICE[VAGUE])]
    return []


_DETECTORS = ((HEDGE, _hedge), (READY, _ready), (CAVEAT, _caveat), (NARROW, _narrow), (DEFER, _defer),
              (OVERCORRECT, _overcorrect), (SYCOPHANCY, _syco), (VAGUE, _vague))
HELD_HEDGE_ADVICE = "State the conclusion plainly; the hold stands, so do not act on it yet."


def _ascii_quotes(text) -> str:
    """Typographic apostrophes are ordinary English: "I\u2019ll" must read as "I'll"."""
    return str(text or "").replace("\u2019", "'").replace("\u2018", "'")


def analyze(turn: Turn) -> list[Finding]:
    """Every finding for one turn, at most a few per mode. A hold in the user's message silences the
    action modes (ready-to, caveat, narrow, deference): waiting is the right answer there. A hedge stays a
    hedge under a hold, but its advice stops short of acting."""
    if not str(turn.assistant or "").strip():
        return []
    turn = dataclasses.replace(turn, assistant=_ascii_quotes(turn.assistant), user=_ascii_quotes(turn.user),
                               context=_ascii_quotes(turn.context), previous_assistant=_ascii_quotes(turn.previous_assistant))
    if turn.context and "[selenite]" in turn.context:
        turn = dataclasses.replace(turn, context=_NUDGE_BLOCK.sub(" ", turn.context))
    held = _user_hold(turn)
    sents = _sentences(_clean(turn.assistant))
    out: list[Finding] = []
    for mode, fn in _DETECTORS:
        if held and mode in _ACT_MODES:
            continue
        found = fn(turn, sents)
        if held and mode == HEDGE:
            found = [Finding(f.mode, f.phrase, HELD_HEDGE_ADVICE) for f in found]
        out.extend(found[:2])
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
