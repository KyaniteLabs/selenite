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

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

try:  # inside the Hermes plugin package the sibling facet is one level up; standalone it is top-level
    from ..antibeaurocracy_core import HUMAN, WALL, WALLS_TEXT, classify, wall_family
except (ImportError, ValueError):
    from antibeaurocracy_core import HUMAN, WALL, WALLS_TEXT, classify, wall_family

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
_CODE = re.compile(r"```.*?(```|\Z)|`[^`\n]+`", re.S)
_QUOTED = re.compile(r"\"[^\"\n]{1,200}\"|“[^”\n]{1,200}”|(?<![\w'])'[^'\n]{1,200}'(?![\w'])")


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
                         r"without|nothing|no|zero|n'?t)\W+(\w+\W+){0,2}\Z", re.I)


def _negated(text: str, start: int) -> bool:
    """True when a negator sits just before text[start:]."""
    return bool(_NEG_BEFORE.search(text[max(0, start - 28):start]))


# ---------------------------------------------------------------- the stop check (walls and holds)

# What the fake-gate classifier has no word for: a hold, a wait on a person, or a request that only wants
# advice or analysis. It judges whether a wait is fake; this judges whether the agent should stop.
_HOLD = re.compile(
    r"\b(on hold|hold (off|until|for|on|everything)|please hold|(?<!\w)hold\.?$|freeze|frozen|read-?only|research-?only|"
    r"only research|(advice|analysis|diagnosis|plan|review|report)[- ]only|"
    r"just (diagnose|investigate|explain|plan|look|research|review|advise|report|tell|check)|"
    r"no (changes|edits|writes|actions?)|don'?t (do )?anything|do not do anything|nothing (should|is to|to) (move|change|happen)|"
    r"(do not|don'?t|never|must not|mustn'?t|not to) (touch|change|restart|merge|deploy|delete|push|close|edit|modify|run|commit|"
    r"send|install|rename|write|stop|reboot|migrate|restore|upload|publish|release|ship|remove|apply|start|kill|update|create|"
    r"act|move|proceed|continue|go ahead|fix|ship|tag|post|email|reset|drop|wipe)|"
    r"wait(ing|s|ed)? (for|on|until)\b|(blocked|parked|paused|held|stalled|pending) (on|pending|until|by)\b|pending (approval|review|"
    r"sign-?off|a decision|the)|awaiting|sign-?off|go-?ahead|green-?light|your (ok|okay|approval|word|call|say-?so)|"
    r"(requires?|needs?) (the )?(\w+'?s? )?(approval|sign-?off|consent|permission|ok|okay)|"
    r"(once|when|after|until) (you|he|she|they|\w+) (say|says|approve|approves|confirm|confirms|ok|signs?|lifts?|opens?|lands?)|"
    r"(once|when|after|until) (the )?[\w' -]{1,40} (lands?|merges?|approves?|signs? off|clears?|finishes|ships|lifts?)|"
    r"(no|any) (further|more) \w+ until|until the [\w.]+ (window|freeze|review|lifts|opens|ships|lands)|"
    r"what do you (recommend|suggest|think)|your (recommendation|advice|opinion)|any (suggestions|recommendations|thoughts)|"
    r"(do you|would you) (recommend|suggest))\b", _I)
# Phrases that hold only when the user says them; an agent's "not committed yet" is a state, not a stop.
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


def _walled(sents: Sequence[str], i: int, loose: bool = True) -> bool:
    """Is sentence i a stop, or next to one? A wall or a hold in the sentence before or after counts.
    Action modes also use the loose wall-family net on the sentence itself; the rest use the strict check."""
    here = sents[i]
    if _strict(here) or (loose and wall_family(here)):
        return True
    return any(_strict(sents[j]) for j in (i - 1, i + 1) if 0 <= j < len(sents))


def _user_hold(t: "Turn") -> bool:
    """A hold, a request for advice only, or a named person's sign-off in the user's message or their
    recent earlier messages. The user naming a wall word (deploy, credentials) is a request, not a hold."""
    for text in (t.user or "", (t.context or "")[-1500:]):
        if _HOLD.search(text) or _USER_HOLD.search(text):
            return True
    return any(_verdict(x)[1] for x in _sentences(t.user or ""))  # a person is named as the one who must say yes


# ---------------------------------------------------------------- C1 hedging when the evidence is clear

_HEDGE_WORDS = re.compile(
    r"\b(i )?(suspect(s|ed)?|might|maybe|perhaps|possibly|probably|likely|could (be|have been)|may (be|have)|"
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


def _hedge(t: Turn, sents: list[str]) -> list[Finding]:
    fact_words = [_words(ln) - _GENERIC for c in t.tools for ln in str(c.output or "").splitlines()
                  if _FACT.search(ln) and not _ZERO_FACT.search(ln)]
    if not fact_words:
        return []
    out = []
    for i, s in enumerate(sents):
        if s.endswith("?") or not _HEDGE_WORDS.search(s) or _OPEN.search(s) or _walled(sents, i, loose=False):
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
               "chec": ("check", "test", "pytest", "diff", "status"), "veri": ("verify", "test", "pytest", "diff"),
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
    return [seg.split() for seg in re.split(r"&&|\|\||[;|\n]", cmd) if seg.strip()]


def _passive(words: list[str]) -> bool:
    if not words:
        return True
    head = words[0].rsplit("/", 1)[-1].lower()
    if head == "git" and len(words) > 1:
        return words[1].lower() in ("diff", "log", "show", "status", "blame")
    return head in _PASSIVE_HEADS


def _action_tokens(t: Turn) -> set[str]:
    """Lower-case word tokens of what the turn's tool calls actually did, not what they mention."""
    toks: set[str] = set()
    for c in t.tools:
        name = str(c.name or "")
        if _SHELL.search(name) or name.lower() in ("bash", "terminal"):
            for words in _heads(_command(c)):
                if not _passive(words):
                    toks.update(re.findall(r"[a-z]+", " ".join(words).lower()))
        elif not _PASSIVE_NAMES.search(name):
            toks.update(re.findall(r"[a-z]+", f"{name} {c.args}".lower()))
    return toks


def _acted(verb: str, t: Turn) -> bool:
    stems = _DONE_STEMS.get(verb[:4]) or _DONE_STEMS.get(verb[:3]) or (verb[:4],)
    toks = _action_tokens(t)
    return any(tok.startswith(st) for tok in toks for st in stems)


def _ready(t: Turn, sents: list[str]) -> list[Finding]:
    out = []
    for i, s in enumerate(sents):
        m = _READY.search(s)
        if not m or s.endswith("?") or _negated(s, m.start()) or _walled(sents, i):
            continue
        if _acted(m.group("verb").lower(), t):
            continue
        out.append(Finding(READY, _snip(s), ADVICE[READY]))
    return out


# ---------------------------------------------------------------- C3 caveat as exit

_RISK = re.compile(
    r"\b(would (be )?(lost|overwritten|wiped)|will be (lost|overwritten|wiped)|would lose|will lose|"
    r"won'?t survive|will not survive|not (yet )?(tracked|committed|in version control|persisted|backed up|saved)|"
    r"uncommitted|untracked|(lives|exists|stored|saved|kept) only (on|in)|"
    r"a (rebuild|reinstall|reboot) (would|will) (lose|wipe|erase|undo|revert|reset|clear|overwrite))\b", _I)
_SIGNOFF = re.compile(r"^(?:[-\u2014\u2013]+\s*\w[\w .]*$|(?:let me know|thanks|thank you|hope|cheers|happy to)\b[^\n]{0,120}$)", _I)
_COMMIT = re.compile(r"\bgit\b[^|;&\n]*\bcommit\b", _I)


def _caveat(t: Turn, sents: list[str]) -> list[Finding]:
    paras = [p for p in re.split(r"\n\s*\n", _clean(t.assistant).strip()) if p.strip()]
    if not paras:
        return []
    committed = any(_COMMIT.search(_command(c)) for c in t.tools)
    out = []
    tail = [paras[-1]]
    i = len(paras) - 1
    while i > 0 and len(tail) < 3 and _SIGNOFF.match(paras[i].strip()):  # a sign-off can follow the caveat
        i -= 1
        tail.append(paras[i])
    for para in tail:
        ps = _sentences(para)
        for i, s in enumerate(ps):
            m = _RISK.search(s)
            if not m or s.endswith("?") or _walled(ps, i) or _negated(s, m.start()):
                continue
            if committed:
                continue  # the turn did commit something; the caveat is not an exit
            out.append(Finding(CAVEAT, _snip(s), ADVICE[CAVEAT]))
    return out[:2]


# ---------------------------------------------------------------- C4 narrow reading of a broad instruction

_BROAD = re.compile(r"\b(all|everything|every|each|whole|entire|any and all|noise)\b", _I)
_USER_NARROW = re.compile(r"\b(only|just|first|instead|except|leave (the )?(rest|others?|remaining)|not all|rather than|"
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
    r"\b(fix (it )?all|do (it|everything|all)|go ahead|just do|you decide|your call|don'?t ask|no questions|"
    r"all approved|use your judg(e)?ment|without asking|make the call|do whatever you (think|want|like)|"
    r"whatever you think (is )?best|up to you)\b", _I)
_NOT_YET = re.compile(r"^\W*(yet|first|until)\b", _I)


def _granted(text: str) -> bool:
    for m in _GRANT.finditer(text or ""):
        if not _negated(text, m.start()) and not _NOT_YET.match(text[m.end():m.end() + 8]):
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
        if re.search(r"\bor\b", rest, _I):
            continue  # a real choice: the context does not pick for the agent
        verbs = {w for w in _words(rest, min_len=3) if w not in ("this", "that", "them", "with")}
        shared = verbs & user_words
        # Answered means the user granted it outright, or asked for this very thing: the question's verb and its
        # object both appear in the user's own words. One shared noun is topic overlap, not an answer.
        if _granted(asked) or len(shared) >= 2:
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
    u = user or ""
    return len(re.findall(r"\w+", u)) >= 6 or bool(re.search(r"\d|[:=]", u))


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
    r"^\W*absolutely[,!. ]|^\W*that'?s (a )?(great|excellent|fantastic) (point|catch|idea|observation|call)", _I)
# Tools that only read: a read-back is a check.
_READ_TOOLS = re.compile(r"^(read|read_file|view|open|cat|grep|glob|search_files|search|find|list_dir|ls_files|web_fetch|fetch)$", _I)
_VERIFY_HEADS = frozenset(("pytest python3 python node npm npx pnpm yarn make cargo go nix mvn gradle ruby uv tox unittest curl wget "
                           "diff cmp stat wc ping dig nc ss journalctl systemctl docker kubectl lint ruff mypy eslint tsc cat head tail "
                           "sha256sum md5sum jq").split())
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
                if head in _VERIFY_HEADS or _VERIFY_TOKENS.search(" ".join(words)):
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

_VAGUE = re.compile(
    r"\b(should be (fine|good|ok|okay|working|done|all set|resolved)|(it|that|this) (should|ought to) work|"
    r"looks? (good|fine|ok|okay|right)( to me)?|seems? (fine|good|ok|okay|to work)|probably (works|fine|ok|okay)|"
    r"good to go|all good|i think (it|that|this) works)\b", _I)


def _vague(t: Turn, sents: list[str]) -> list[Finding]:
    if _verified(t):
        return []
    for i, s in enumerate(sents):
        if _VAGUE.search(s) and not s.endswith("?") and not _walled(sents, i, loose=False):
            return [Finding(VAGUE, _snip(s), ADVICE[VAGUE])]
    return []


_DETECTORS = ((HEDGE, _hedge), (READY, _ready), (CAVEAT, _caveat), (NARROW, _narrow), (DEFER, _defer),
              (OVERCORRECT, _overcorrect), (SYCOPHANCY, _syco), (VAGUE, _vague))
HELD_HEDGE_ADVICE = "State the conclusion plainly; the hold stands, so do not act on it yet."


def analyze(turn: Turn) -> list[Finding]:
    """Every finding for one turn, at most a few per mode. A hold in the user's message silences the
    action modes (ready-to, caveat, narrow, deference): waiting is the right answer there. A hedge stays a
    hedge under a hold, but its advice stops short of acting."""
    if not str(turn.assistant or "").strip():
        return []
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
