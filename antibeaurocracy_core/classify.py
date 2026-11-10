"""Classify a "wait" (a block reason, an ask, a hold) as a real wall, a question for a person,
a machinery fault, a task dependency, or bureaucracy between agents.

Deterministic, stdlib-only, fast enough for a pre_tool_call hook. Every wait gets exactly one class:
WALL, HUMAN, DEPENDENCY, MACHINERY or FAKE. FAKE has six subtypes.

The rule order is the safety bias. Wall checks run first and are written broadly, so the
classifier leans toward calling something a wall. It is still a pattern heuristic: it can
miss a wall phrased in a way it has never seen. That is why the plugin's default mode only
nudges, and why the FAKE actions never say a step is safe; they say how to check.

Precedence, as an explicit table (first match wins): see ``RULES``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

WALL = "WALL"
HUMAN = "HUMAN"
MACHINERY = "MACHINERY"
DEPENDENCY = "DEPENDENCY"
FAKE = "FAKE"
CLASSES = (WALL, HUMAN, DEPENDENCY, MACHINERY, FAKE)

# FAKE subtypes
ACK = "F1-ack"  # one agent asking another agent for an OK
RELAY = "F2-relay"  # work done; another agent must carry/create/merge it
LIMBO = "F3-ownership-limbo"  # "X must own/rule/declare/jointly adopt"
CEREMONY = "F4-ceremony"  # attestations, receipts, review-of-review
PARKING = "F5-parking-lot"  # HOLD with no owner and expiry
STALE = "F6-stale-wait"  # waiting with no named next actor or action

ACTIONS = {
    WALL: "Escalate once to the human with a decision-only ask (one line, options, default). Keep doing every other part of the work.",
    HUMAN: "A question for a person, not an agent gate. Leave it to the person's queue; this plugin does not judge it.",
    MACHINERY: "Not a gate, a fault. Fix it or reroute to a host or lane that can do it, and file the repro with whoever owns that machinery.",
    DEPENDENCY: "Link the parent task (kind=dependency) so it resumes on its own.",
    ACK: "Another agent's OK adds nothing unless it owns a wall here. Check: is the step in your scope, and can it be undone? If both, do it and record how to undo it. If not, it's a wall: name it.",
    RELAY: "Collapse the hop: do the carry step yourself if your lane can. If it can't, ask whoever owns the capability for it once, rather than asking another agent for a favour each time.",
    LIMBO: "Make the call with a stated default and a revert path, comment it on the card, and move on. If ownership really is disputed, ask the named decider once.",
    CEREMONY: "Drop the ceremony. Keep only evidence a reader would actually check (a test run, a diff, a URL). Comment, don't open a new card.",
    PARKING: "Unpark: dispatch it, put it in triage, or close it. A hold needs a named owner and an expiry, or it lapses.",
    STALE: "Name the next actor and action in one line, or close the card. A wait with no next step is not a wait.",
}

_I = re.I

# A negator directly in front of a wall phrase ("no spend involved", "not a force-push", "nothing to
# publish") denies the wall. Kept deliberately narrow: "cannot proceed without deleting" or "no way
# around a force-push" still claim the wall. A missed negation costs a pass; a false one hides a wall.
MAX_CHARS = 4000

_NEGATED = re.compile(r"\b(no|not an?|without any|nothing to|zero)[ \t]+\Z", _I)
# ...except where "no" states an absence that is itself the wall: "no budget approval yet", "no
# subscription seat left", "no API key". Those still count.
# ...but "no payment needed", "no credentials required", "no secrets in the diff" deny it again.
_DENIED_AFTER = re.compile(r"[ \t]*(needed|required|involved|necessary|in (the|this) (diff|change|patch|pr|commit|repo))\b", _I)
_ABSENCE = re.compile(r"(approv|sign-?off|subscription|seat|plan|tier|key|token|credential|password|secret|budget|payment|balance|permission)", _I)

# Authority walls. Verb stems, so "delete the rows", "wire $4,000" or "deploy to prod" all count.
_WALL = [
    ("credentials", re.compile(
        r"(ENEEDAUTH|E401|HTTP 40[13]|\b401 unauthori[sz]ed|push=false|READ permission|permission denied \(publickey|login required|"
        r"\b(missing|expired|invalid|revoked|no(?! (output|input|context|more) )|no working|needs? (a |new )?|rotate|share|paste) (\w+ ){0,2}(credentials?|tokens?|api[ -]?keys?|passwords?|secrets?|2fa|otp)\b|"
        r"\bre-?auth(enticate)?\b|oauth (flow|login|consent)|sudo password)", _I)),
    ("spend", re.compile(
        r"(\$\s?\d|\b\d+ ?(usd|eur|dollars?)\b|\b(spend(ing)?|billing|payment|pay (for|the)|invoice|purchas\w*|buy(ing)?|top[- ]?up|refund\w*|"
        r"balance exhausted|402 payment|paid (plan|tier)|subscription|budget (approval|cap|exceeded|sign-?off)|billing approv\w*|cost(s|ing)? (us )?(about |around |roughly |over |up to |~ ?)?\$?\d[\d,.]*k?\b|(\$\s?\d[\d,.]*k?|\b\d[\d,.]*k|\b\d{3,}[\d,.]*|\b\d[\d,.]* ?(usd|eur|dollars?)) ?(per|a|/) ?(month|year|mo|yr)\b|"
        r"charg(e|ing) (the |a )?(card|customer|account)|wire (the )?(money|funds|transfer|\$)|transfer funds)\b)", _I)),
    ("publish", re.compile(
        r"\b(publish\w*|release (to|on)|public release|make (it |the repo )?public|go(es)? public|"
        r"post(ing)? (to|on) (x|twitter|linkedin|reddit|bluesky|mastodon|hacker ?news|social)|tweet\w*|press release|"
        r"send\w* (an? |the )?(\w+ ){0,3}(email|newsletter|message|dm|sms|invite)s?|email (the )?(customers?|users?|list|clients?)|"
        r"in (the ceo|the user|the operator|the owner)'?s voice|external(ly)? (communicat|send|post)|"
        r"deploy\w* (to )?(prod\w*|live)|terraform (apply|destroy)|kubectl (apply|delete)|helm (install|upgrade|uninstall)|roll\w* out to (prod\w*|users|customers)|ship(ping)? to (prod\w*|customers|users)|merg\w* (\w+ ){0,3}(to|into) (main|master|prod\w*|release))", _I)),
    ("destructive", re.compile(
        r"\b(irreversibl\w*|destructive|drop (table|database|schema)|truncate|rm -rf|force[- ]push|push (-f|--force)|git push --force|delete everything|"
        r"delet\w* (the |all |a |production |prod |user |customer )*(\w+ ){0,2}(repo|repository|database|db|rows?|tables?|buckets?|account|data|history|backups?|branch|records?|files?|users?|namespaces?|clusters?|volumes?|disks?|tenants?)|"
        r"rewrit\w* (git )?history|reset --hard|wipe|purge|erase|data[- ]loss|shut ?down (prod|production)|revoke (access|keys?))", _I)),
    ("legal", re.compile(
        r"\b(legal (review|team|sign-?off|approval|counsel)|(approval|sign-?off|ok) from legal|lawyer|licen[cs]e (\w+ )?(review|compat\w*)|contract signature|sign (the |a )?contract|"
        r"terms of service|gdpr|hipaa|privacy review|trademark|copyright)\b", _I)),
    ("named-freeze", re.compile(
        r"\b(security hold|(ceo|board|exec\w*) (freeze|hold)|code freeze|change freeze|FROZEN by|incident hold|e-?stop|kill switch|embargo)\b", _I)),
]

# A question addressed to a person. Hermes treats needs_input as the worker's human channel,
# so it is the person's queue, not an agent-to-agent gate.
_INFRA = re.compile(r"(terraform (apply|destroy)|kubectl (apply|delete)|helm (install|upgrade|uninstall))", _I)
_INFRA_FAULT = re.compile(r"\b(failed|fails|errored|error|timed out|time ?out|connection refused|dry-run)\b", _I)

# The loose net enforce mode checks before it refuses anything. It is meant to over-match: any word
# from a wall family (money, infra, deletion, credentials, publishing, legal, freezes) or a person's
# role anywhere in the full text means the agent is nudged, never refused. A miss here costs one
# refusal of a real wall; a false hit only costs a refusal of a fake that gets nudged instead.
WALL_FAMILY = re.compile(
    r"(\$|€|£|\b\d{3,}\b|\b\d+k\b|\b(cost|price|pay|paid|payment|bill\w*|budget|spend\w*|invoice|purchas\w*|buy\w*|"
    r"subscri\w*|seat|plan|tier|quota|balance|charg\w*|refund\w*|money|funds?|usd|eur|dollars?|"
    r"prod\w*|live|deploy\w*|terraform|kubectl|helm|namespace|cluster|database|db|table|schema|migrat\w*|"
    r"delet\w*|drop\w*|wipe\w*|purg\w*|eras\w*|destroy\w*|destructive|truncat\w*|force|irreversibl\w*|"
    r"rewrit\w*|history|reset|rm|revok\w*|"
    r"credential\w*|token\w*|keys?|secrets?|passwords?|auth\w*|login|oauth|sudo|40[123]|permission\w*|"
    r"publish\w*|public|npm|pypi|email\w*|tweet\w*|post|announce\w*|customers?|users?|clients?|"
    r"legal|lawyer|licen[cs]\w*|gdpr|hipaa|privacy|trademark|copyright|terms|"
    r"freeze|frozen|e-?stop|incident|embargo|kill switch|security|"
    r"ceo|cto|cfo|coo|founders?|owner|operator|human|boss|board|executives?|manager|person))\b", _I)


_HUMAN = re.compile(
    r"(\b(should i|shall i|do you want me to|want me to|would you like me to|may i|can i go ahead|ok to proceed|okay to proceed|"
    r"let me know if (you'?d like|you want) me to|your (call|decision|choice|preference)|which (do|would) you (prefer|like|want))\b|"
    r"\b(ask|asking|waiting (for|on)|need) (the )?(human|user|operator|person|customer|ceo|founder)\b)", _I)

# A person with authority named as the source of a stop or an OK ("ACK from the CEO", "HOLD per the
# owner"). That wait is a person's decision, not an agent gate, whatever gate phrase surrounds it.
_ROLE = (r"(ceo|cto|cfo|coo|founders?|owner|operator|user|human|boss|board|executives?|manager|legal|customers?|"
         r"clients?|person)")
_NOT_A_PERSON = r"(?!-|('s)?\s+(agent|bot|seat|module|lane|worker|service|process)s?\b)"
_HUMAN_AUTHORITY = re.compile(
    # the source of the wait: "ACK from the CEO", "HOLD per the owner", "approved by the founder"
    rf"(\b(from|per|by) (the |my |our )?{_ROLE}\b{_NOT_A_PERSON}|"
    # the person's own word: "the founder's OK"
    rf"\b(the |my |our )?{_ROLE}'s (approval|ok|okay|sign-?off|go-?ahead|decision|call|ack)\b|"
    # the person as the subject: "the CEO must countersign", "CEO has not signed", "until the CEO approves"
    rf"\b{_ROLE} (must|has to|needs to|has not|hasn't|has yet to|approves?|approved|signs?|signed|"
    rf"decides?|countersigns?|ratif\w*|sign(s|ed)? off)\b)", _I)

_WAIT_WORD = re.compile(r"\b(await\w*|waiting|approv\w*|ack|ok|okay|sign-?off|go-?ahead|hold|decision|decide|ruling|call)\b", _I)

_MACHINERY = re.compile(
    r"\b(read-?only (file ?system|fs)|errno ?\d+|no such file|not found|command not found|missing (binary|tool|package|dependency|module)|"
    r"no gpu|out of memory|oom|disk full|no space left|quota exceeded|rate[- ]limit(ed|ing)?|too many requests|429|timed? ?out|"
    r"crash(ed|es|-loop)?|segfault|unreachable|host (is )?(down|offline)|connection (refused|reset)|ssh .*fail|ci (is )?red|build fail\w*|"
    r"tests? fail\w*|schema mismatch|no (such )?action|unsupported (action|operation)|executor has no|spawn fail\w*|gave up after)\b",
    _I,
)

_DEPENDENCY = re.compile(r"\b(waiting on (task|card|parent|pr|issue) [#\w-]+|depends on (task|card|pr|issue) |blocked by (t_[0-9a-f]+|#\d+)|after (t_[0-9a-f]+|#\d+) (lands|merges|finishes))", _I)

# Generic agent roles. Teams add their own seat names with configure(seats=[...]); none ship here.
# Human roles (owner, manager, legal, maintainer) are deliberately absent: a person's sign-off is not agent bureaucracy.
_BASE_SEATS = ("product", "security", "platform", "engineering", "design", "ops", "reviewer agent", "orchestrator",
               "the other agent", "the owning agent", "the other seat", "seat", "agent", "bot")
_extra_seats: tuple[str, ...] = ()
_extra_ceremony: tuple[str, ...] = ()


def configure(seats: Iterable[str] = (), ceremony_phrases: Iterable[str] = ()) -> None:
    """Add a team's own seat names and ceremony phrases (from plugin config). Process-wide."""
    global _extra_seats, _extra_ceremony, _FAKE
    _extra_seats = tuple(s.strip() for s in seats if s and s.strip())
    _extra_ceremony = tuple(p.strip() for p in ceremony_phrases if p and p.strip())
    _FAKE = _build_fake()


def _seats_rx() -> str:
    return "(" + "|".join(re.escape(s) for s in (*_extra_seats, *_BASE_SEATS)) + ")"


def _build_fake() -> list[tuple[str, re.Pattern]]:
    seats = _seats_rx()
    extra = "|".join(re.escape(p) for p in _extra_ceremony)
    return [
        (RELAY, re.compile(
            r"\b(await(ing)? .{0,30}relay|relay .{0,40}(create|open|carry|merge|push|file)|"
            r"hand(ed)? off to .{0,30} to (create|open|merge|push|run)|"
            rf"(await(ing)?|waiting (for|on)|need|needs) (the |my |our )?([\w-]+ )?{seats} to (open|create|push|run|carry|file|merge|land) (the|a|an|this|my|our) (pr|patch|change|command|card|branch|fix|diff))", _I)),
        (LIMBO, re.compile(
            rf"\b({seats}\s*(/\s*{seats}\s*)*\s+(must|needs? to|has to|to)\s+(own|record|rule|decide|declare|reconcile|bind|ratify|adopt|countersign|agree)|"
            r"jointly (adopt|implement|agree|own)|pending (ruling|decision) (from|by)|owner (must|to) declare|no (accepted|authoritative) (owner|disposition|ruling)|"
            r"which (seat|agent|team) owns|ownership (unclear|unresolved|dispute))", _I)),
        (ACK, re.compile(
            rf"(\bACK (from|by)\b|\bawait(ing)? ACK\b|acknowledg(e|ment) (from|by) {seats}|sign-?off (from|by) {seats}|(approval|go-?ahead|ok) (from|by) {seats}|"
            rf"(awaiting|await|wait(ing)? (for|on)) {seats}('s)? (approval|go-?ahead|green light|ok\b|okay|confirmation|sign-?off|ack))", _I)),
        (CEREMONY, re.compile(
            r"\b(attest(ation)?|receipt (card|chain|required)|re-?verify the (verification|receipt)|"
            r"review of (the )?review|countersign|ratif(y|ied|ication)|"
            r"acceptance (card|ritual)|ledger row|"
            r"contract (is|says) .{0,30}(cannot|can't) (mark|close)|cannot mark (it )?done" + (f"|{extra}" if extra else "") + r")", _I)),
        (PARKING, re.compile(
            r"((?-i:\bPARKED\b|\bHOLD\b)(?!er)|do not (re)?dispatch|parked by|keep (it )?blocked|preserve .{0,20}until further notice)", _I)),
    ]


_FAKE = _build_fake()

_HOLD_WITH_EXPIRY = re.compile(r"\b(until|expires?|through|till)\s+\d{4}-\d{2}-\d{2}|\buntil \d{1,2}[/-]\d{1,2}\b", _I)


@dataclass
class Verdict:
    cls: str
    subtype: str = ""
    confidence: float = 0.0
    reason: str = ""
    action: str = ""
    matched: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.subtype or self.cls

    @property
    def is_fake(self) -> bool:
        return self.cls == FAKE

    @property
    def evidenced(self) -> bool:
        """True when a phrase in the text, not a default, produced the verdict."""
        return bool(self.matched)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


def _hits(pattern: re.Pattern, text: str, *, skip_negated: bool = False) -> list[str]:
    out = []
    for m in pattern.finditer(text):
        if skip_negated:
            g = m.group(0)
            negated = bool(_NEGATED.search(text[max(0, m.start() - 20):m.start()]))
            if (negated or g[:3].lower() == "no ") and _DENIED_AFTER.match(text, m.end()):
                continue  # "no payment needed", "no secrets in the diff"
            if negated and not _ABSENCE.search(g):
                continue  # "no spend involved"
        out.append(m.group(0)[:60])
    return out[:3]


def _as_float(x) -> float | None:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def classify(text: str, *, kind: str | None = None, age_hours: float | str | None = None,
             created_blocked: bool = False) -> Verdict:
    """Classify one wait. ``kind`` is the kanban block kind if known
    (dependency/needs_input/capability/transient). ``age_hours`` enables the stale check.
    ``created_blocked`` marks a card created straight into blocked with no reason of its own."""
    t = str(text or "").strip()
    if len(t) > MAX_CHARS:  # bounded, since a hook that times out fails closed in Hermes; keep both ends
        t = t[:MAX_CHARS // 2] + "\n" + t[-MAX_CHARS // 2:]
    kind = str(kind or "").strip().lower() or None
    age = _as_float(age_hours)

    # 1. Authority walls win over everything (negated mentions don't count).
    walls = [(name, _hits(p, t, skip_negated=True)) for name, p in _WALL]
    walls = [(n, h) for n, h in walls if h]
    fakes = [(sub, _hits(p, t)) for sub, p in _FAKE]
    fakes = [(s, h) for s, h in fakes if h]
    # An infra command reported as failing, with nothing waiting on anyone, is a fault, not a wall.
    if (walls and not fakes and all(_INFRA.fullmatch(h) for _, hs in walls for h in hs)
            and _INFRA_FAULT.search(t)):
        return Verdict(MACHINERY, "", 0.7, "an infra command failed", ACTIONS[MACHINERY], _hits(_INFRA_FAULT, t))
    if walls:
        names = ", ".join(n for n, _ in walls)
        return Verdict(WALL, names, 0.9, f"authority wall: {names}", ACTIONS[WALL], [h for _, hs in walls for h in hs])

    # 2. A question addressed to a person is the person's queue, never an agent gate.
    human = _hits(_HUMAN, t)
    if human:
        return Verdict(HUMAN, "", 0.8, "addressed to a person", ACTIONS[HUMAN], human)

    # 3. A real task dependency resumes on its own.
    if kind == "dependency" or _DEPENDENCY.search(t):
        return Verdict(DEPENDENCY, "", 0.8, "waits on another task, auto-resumes", ACTIONS[DEPENDENCY],
                       _hits(_DEPENDENCY, t) or ["kind=dependency"])

    # 4. The agent declared a capability or transient gap: trust the declared kind.
    if kind in ("capability", "transient"):
        return Verdict(MACHINERY, "", 0.6, f"declared {kind} gap", ACTIONS[MACHINERY], [f"kind={kind}"])

    mach = _hits(_MACHINERY, t)

    # 5. A wait whose source is a person with authority is that person's call.
    authority = _hits(_HUMAN_AUTHORITY, t)
    if authority and (fakes or _WAIT_WORD.search(t)):
        return Verdict(HUMAN, "", 0.7, "a person's stop or approval", ACTIONS[HUMAN], authority)

    # 6. A hold with an explicit expiry is legitimate parking.
    if fakes and [s for s, _ in fakes] == [PARKING] and _HOLD_WITH_EXPIRY.search(t):
        return Verdict(DEPENDENCY, "", 0.7, "time-boxed hold with an expiry; it lapses on its own",
                       "Leave it. When the expiry passes, dispatch or close it.", _hits(_HOLD_WITH_EXPIRY, t))

    # 7. needs_input is the worker's channel to a person. It stays HUMAN unless the text itself shows
    # an agent gate or a fault, in which case that wins with a little less certainty.
    if kind == "needs_input" and not (fakes or mach):
        return Verdict(HUMAN, "", 0.7, "filed as needs_input", ACTIONS[HUMAN], ["kind=needs_input"])

    # 8. A fault with no gate layered on it.
    if mach and not fakes:
        return Verdict(MACHINERY, "", 0.75, "environment/tooling fault", ACTIONS[MACHINERY], mach)

    # 9. Bureaucracy, evidenced by a phrase.
    if fakes:
        sub, hits = fakes[0]
        conf = min(0.95, 0.6 + 0.1 * len(fakes))
        if mach:  # the fault is real; the gate layered on it is still bureaucracy, with less certainty
            conf -= 0.15
        if kind == "needs_input":
            conf -= 0.1
        return Verdict(FAKE, sub, round(conf, 2), f"bureaucratic wait ({sub})", ACTIONS[sub],
                       hits + [h for _, hs in fakes[1:] for h in hs] + mach)

    # 10. Defaults: no phrase matched. These are low-confidence and never "evidenced".
    if created_blocked:
        return Verdict(FAKE, PARKING, 0.5, "created blocked with no reason of its own", ACTIONS[PARKING], [])
    if not t:
        return Verdict(FAKE, PARKING, 0.5, "blocked with no stated reason", ACTIONS[PARKING], [])
    if age is not None and age > 24:
        return Verdict(FAKE, STALE, 0.5, f"waiting {age:.0f}h with no recognised wall", ACTIONS[STALE], [])
    return Verdict(FAKE, STALE, 0.3, "no wall, fault or dependency named", ACTIONS[STALE], [])


RULES = (
    "1 WALL: a credential, spend, publish/deploy/send, destructive, legal or named-freeze phrase, unless a negator sits directly before it",
    "2 HUMAN: the text asks a person a question",
    "3 DEPENDENCY: kind=dependency, or the text names another task",
    "4 MACHINERY: kind=capability or kind=transient",
    "5 HUMAN: a wait or gate phrase whose source is a person with authority ('from the CEO', 'per the owner', "
    "'the founder's OK', 'the CEO must sign'); a bare role noun, or an agent named after a role, does not count",
    "6 DEPENDENCY: a HOLD with an explicit expiry date",
    "7 HUMAN: kind=needs_input with no gate or fault phrase in the text",
    "8 MACHINERY: a fault phrase with no gate phrase",
    "9 FAKE F1-F5: an agent-to-agent gate phrase (confidence 0.7-0.95, less when mixed with a fault or filed as needs_input)",
    "10 FAKE default, not evidenced: created blocked or empty (0.5), older than 24h (0.5), anything else (0.3)",
)
