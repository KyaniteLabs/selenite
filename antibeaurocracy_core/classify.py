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

# The one wall list. Calm mode, the doctrine, the nudge, ask mode's question and the docs all quote it,
# so no facet carries a narrower list than another (a test checks every surface).
WALLS = ("credentials", "spending money", "publishing, deploying or changing visibility",
         "deleting or other irreversible steps", "legal", "a named freeze",
         "a question only a person can answer")
WALLS_TEXT = ", ".join(WALLS[:-1]) + ", and " + WALLS[-1]

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
    PARKING: "Unpark: ask whoever set the hold for a named owner and an expiry, then dispatch it, put it in triage, or close it. A hold with neither lapses.",
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
        # "needs credentials", "needs Ana's credentials", "requires the npm token", "missing npm token":
        # up to three words (possessives included) between the verb and the secret.
        r"\b(missing|expired|invalid|revoked|no(?! (output|input|context|more) )|no working|needs?(?! no\b| zero\b)|"
        r"requir(e|es|ed|ing)(?! no\b| zero\b)|rotat\w*|share|paste|blocked on|waiting (on|for)|only \w+ (has|holds|knows)) ([\w'’.-]+ ){0,3}"
        r"(credentials?|tokens?(?![ \t]+(?:budget|of[ \t]+context)\b)|api[ -]?keys?|passwords?|secrets?|2fa|otp)(?![\w-])|"  # not "credential-free" or LLM token budgets
        # a person has to sign in: "waiting on Ana to log in to npm", "needs to authenticate with PyPI"
        r"\b(needs?|waiting (for|on)|awaiting) (\w+ ){0,6}(credentials?|tokens?(?![ \t]+(?:budget|of[ \t]+context)\b)|(api|deploy|ssh|access)[ -]?keys?|passwords?|secrets?|2fa|otp)\b(?!-free\b)|"
        r"\b(to|must|has to|needs? to|have to) (log ?in|sign ?in|authenticate|re-?auth\w*)\b|"
        # "waiting for the GitHub token", "blocked on credentials for…", "need the SSH key", "provide the
        # passphrase", "need someone to log in to the AWS console", "waiting for access to the private repo"
        r"\b(need(s|ed|ing)?|waiting (for|on)|await\w*|blocked on|provide|send)(?! no\b| zero\b) (an? |the |new |our |my |your |their )?(\w+ ){0,3}"
        r"(credentials?|tokens?(?![ \t]+(?:budget|of[ \t]+context)\b)|api[ -]?keys?|ssh[ -]?keys?|private keys?|passwords?|passphrases?|secrets?|2fa|otp|mfa)\b(?!-)|"
        r"\b(need(s|ed|ing)?|waiting for|await\w*|requires?|ha(s|ve) to|must) (\w+ ){0,2}to (log|sign) ?in\b|"
        r"\b(need(s|ed|ing)?|waiting (for|on)|await\w*|blocked on|requires?|requesting) (\w+ ){0,2}access (to|for)\b|"
        r"\bre-?auth(enticate)?\b|oauth (flow|login|consent)|sudo password|"
        # only the person's own account will do: "fill the Typeform with his own login"
        r"\b(his|her|their|my|\w+['’]s) own (login|account|sign-?in|credentials?)\b)", _I)),
    ("spend", re.compile(
        r"(\$\s?\d|\b\d+ ?(usd|eur|dollars?)\b|\b(spend(ing)?|billing|payment|pay (for|the)|invoice|purchas\w*|buy(ing)?|top[- ]?up|refund\w*|"
        r"balance exhausted|402 payment|paid (plan|tier)|subscription|budget (approval|cap|exceeded|sign-?off)|billing approv\w*|cost(s|ing)? (us )?(about |around |roughly |over |up to |~ ?)?\$?\d[\d,.]*k?\b|(\$\s?\d[\d,.]*k?|\b\d[\d,.]*k|\b\d{3,}[\d,.]*|\b\d[\d,.]* ?(usd|eur|dollars?)) ?(per|a|/) ?(month|year|mo|yr)\b|"
        r"charg(e|ing) (the |a )?(card|customer|account)|wire (the )?(money|funds|transfer|\$)|transfer funds)\b)", _I)),
    ("publish", re.compile(
        r"\b(publish\w*|release (to|on)|public release|make (it |the repo )?public|go(es)? public|"
        r"post(ing)? (to|on) (x|twitter|linkedin|reddit|bluesky|mastodon|hacker ?news|social)|tweet\w*|press release|"
        r"send\w* (an? |the )?(\w+ ){0,3}(email|newsletter|message|dm|sms|invite)s?|email (the )?(customers?|users?|list|clients?)|"
        r"in (the ceo|the user|the operator|the owner)'?s voice|external(ly)? (communicat|send|post)|"
        r"deploy\w* (to )?(prod\w*|live)|\b(prod|production) (deploy\w*|release|rollout)\b|terraform (apply|destroy)|kubectl (apply|delete)|helm (install|upgrade|uninstall)|roll\w* out to (prod\w*|users|customers)|ship(ping)? to (prod\w*|customers|users)|merg\w* (\w+ ){0,3}(to|into) (main|master|prod\w*|release)|"
        r"submi\w* (\w+ ){0,3}(catalog|marketplace|store|registry)s?\b|(catalog|marketplace|store|registry) (entry|submission|listing)s?\b|"
        # "before posting publicly", "the upstream catalog PR": outside readers see it
        r"(post|open|fil|submit|comment)\w* (\w+ ){0,2}publicly|upstream (\w+ ){0,2}(pr|pull request|issue)s?\b|public(ly)?[- ]expos\w*|public exposure)", _I)),
    ("destructive", re.compile(
        r"\b(irreversibl\w*|destructive|drop (the |a |an |all |our |\w+ ){0,3}(tables?|databases?|schemas?|collections?|indexes|indices)\b|(prod\w*|production|live) (\w+ ){0,2}migrations?\b|truncate|rm -rf|force[- ]push|push (-f|--force)|git push --force|delete everything|"
        r"delet\w* (the |all |a |production |prod |user |customer )*(\w+ ){0,2}(repo|repository|database|db|rows?|tables?|buckets?|account|data|history|backups?|branch|records?|files?|users?|namespaces?|clusters?|volumes?|disks?|tenants?)|"
        r"rewrit\w* (git )?history|reset --hard|wipe|purge|erase|data[- ]loss|shut ?down (prod|production)|revoke (access|keys?))", _I)),
    ("legal", re.compile(
        r"\b(legal (review|to review|team|sign-?off|approval|counsel)|(approval|sign-?off|ok) from legal|lawyer|licen[cs]e (\w+ )?(review|compat\w*)|contract signature|sign (the |a )?contract|"
        r"terms of service|gdpr|hipaa|privacy review|trademark|copyright)\b", _I)),
    ("named-freeze", re.compile(
        r"\b(?:(security hold|(ceo|board|exec\w*) (freeze|hold)|code freeze|change freeze|FROZEN by|incident hold|e-?stop|kill switch|embargo)\b"
        r"|frozen\s*[:;\u2014-]|frozen until\b|freeze (?:is )?(?:on|in (?:effect|place)|until)\b|(?:repin|merge|release|deploy|publish|plugin)s? freeze\b)", _I)),
]

# A question addressed to a person. Hermes treats needs_input as the worker's human channel,
# so it is the person's queue, not an agent-to-agent gate.
_INFRA = re.compile(r"(terraform (apply|destroy)|kubectl (apply|delete)|helm (install|upgrade|uninstall))", _I)
_INFRA_FAULT = re.compile(r"\b(failed|fails|errored|error|timed out|time ?out|connection refused|dry-run)\b", _I)
_WALL_FAMILY_ACTION = re.compile(
    r"\b(remov\w*|overwrit\w*|disabl\w*|reset\w*|rotat\w*|turn off|rewrit\w*|announc\w*|publish\w*|delet\w*|drop\w*|wipe\w*|purge\w*|erase\w*|"
    r"destroy\w*|revoke\w*|force[- ]push)\b.{0,60}\b(production|prod|live|customer|user|passwords?|mfa|2fa|certificates?|certs?|"
    r"volumes?|history|announcements?|launch)\b", _I)
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
    r"credential\w*|token(?![ \t]+(?:budget|of[ \t]+context)\b)\w*|keys?|secrets?|passwords?|auth\w*|login|oauth|mfa|2fa|certificates?|sudo|40[123]|permission\w*|"
    r"publish\w*|public|npm|pypi|email\w*|tweet\w*|post|announce\w*|customers?|users?|clients?|"
    r"legal|lawyer|licen[cs]\w*|gdpr|hipaa|privacy|trademark|copyright|terms|"
    r"freeze|frozen|e-?stop|incident|embargo|kill switch|security|"
    r"ceo|cto|cfo|coo|founders?|owner|operator|human|boss|board|executives?|manager|person))\b", _I)

# LLM token capacity is a compute limit, not an authentication credential. Match the
# resource and its context structurally, then remove it before either wall detector runs.
_LLM_TOKEN_CONTEXT = re.compile(
    r"\b(?:(?:(?:\d+\s+)?(?:more\s+)?tokens|\d+\s+(?:more\s+)?token)\s+(?:of|for)\s+(?:the\s+)?(?:llm\s+)?context(?:[ -]+(?:window|length))?(?![-\w])|"
    r"token\s+(?:of|for)\s+(?:the\s+)?(?:llm\s+)?context[ -]+(?:window|length)(?![-\w])"
    r"(?![ \t]+(?:checks?|services?|apis?|brokers?|endpoints?|limits?|requests?|validation|proxy|proxies|monitoring|quotas?|gateways?|inspection)\b)|"
    r"(?:out of|ran out of)\s+(?:the\s+)?(?:llm\s+)?(?:(?:\d+\s+)?tokens|\d+\s+token)|"
    r"(?:llm\s+)?tokens?\s+(?:budget|limit)|"
    r"(?:llm\s+)?context(?:\s+window)?\s+(?:is\s+)?(?:full|exhausted))\b",
    _I,
)
_LLM_TOKEN_CREDENTIAL_CONTEXT = re.compile(
    r"\b(github|api|deploy\w*|access|pat|vault|credential\w*|secret)\b", _I
)


def _without_llm_token_context(text: str) -> str:
    if _LLM_TOKEN_CREDENTIAL_CONTEXT.search(text):
        return text
    return _LLM_TOKEN_CONTEXT.sub(" ", text)


_HUMAN = re.compile(
    r"(\b(should i|shall i|do you want me to|want me to|would you like me to|may i|can i go ahead|ok to proceed|okay to proceed|"
    r"let me know if (you'?d like|you want) me to|your (call|decision|choice|preference)|which (do|would) you (prefer|like|want))\b|"
    r"\b(ask|asking|waiting (for|on)|need) (the )?(human|user|operator|person|customer|ceo|founder)\b)", _I)

# A person with authority named as the source of a stop or an OK ("ACK from the CEO", "HOLD per the
# owner"). That wait is a person's decision, not an agent gate, whatever gate phrase surrounds it.
# Seat names this org actually uses; product/growth/content are deliberately absent (common nouns).
# Seats are agents, not people: a wait ON a seat's approval is fake-gate territory per the shipped
# contract ("waiting on platform approval" is FAKE). Seats appear only in the capability-infinitive
# form ("need the platform seat/Platform to expose a GUI wrapper"), where the seat is who must BUILD, not gate.
_SEAT = r"(platform|security|design|engineering|governance|income|chief.?scientist)"
_ROLE = (r"(ceo|cto|cfo|coo|founders?|owner|operator|user|human|boss|board|executives?|manager|legal|customers?|"
         r"clients?|person)")
_NOT_A_PERSON = r"(?!-|('s)?\s+(agent|bot|seat|module|lane|worker|service|process)s?\b)"
_NOUN = r"(approvals?|ok|okay|yes(/yes)?|consent|sign-?offs?|go|words?|green-?light|blessing|decisions?|calls?|ack|rulings?|verdicts?|adjudicat\w*|hands)"
# The people who hold authority here (not "user" or "customer"): their word may carry one or two
# describing words before the noun ("the CEO's explicit word", "CEO drain word", "Owner adjudication").
_PRINCIPAL = r"(ceo|cto|cfo|coo|founders?|owner|operator|boss)"
# weak: the role is only referenced ("ACK from the CEO"); needs a wait word or gate phrase to count
_HUMAN_AUTHORITY = re.compile(
    # the source of the wait: "ACK from the CEO", "HOLD per the owner", "approved by the founder"
    rf"(\b(from|per|by) (the |my |our )?{_ROLE}\b{_NOT_A_PERSON})", _I)
# strong: the role itself acts or is asked to act — evidence enough on its own
_HUMAN_AUTHORITY_STRONG = re.compile(
    # the person's own word as a noun: "the founder's OK", "needs CEO approval", "CEO word on the copy"
    rf"(\b(the |my |our |needs? |pending |awaiting |without )?{_ROLE}(?:'s)? {_NOUN}\b|"
    rf"\b{_PRINCIPAL}(?:'s|’s)?{_NOT_A_PERSON} ([\w-]+ ){{0,2}}{_NOUN}\b|"
    # the person as the subject: "the CEO must countersign", "CEO has not signed", "until the CEO approves",
    # and the infinitive form after the role: "needs the CEO to approve", "waiting on the owner to sign off"
    rf"\b{_ROLE} (must|has to|needs to|has not|hasn't|has yet to|approves?|approved|signs?|signed|"
    rf"decides?|countersigns?|ratif\w*|sign(s|ed)? off)\b|"
    rf"\b{_ROLE} to (approv\w*|sign(s|ed)? off|decide|ratif\w*|countersign\w*|green-?light|"
    rf"expose|provide|grant|create|open|enable)\b|"
    # the person's spoken stop: "because the operator said no upstream bump", "the owner told us to wait"
    rf"\b{_ROLE} (said|says|asked|told (us|me|you|them))( to)? (no|not|don'?t|do not|wait|hold|stop|pause)\b|"
    # the wait names the person directly: "decision waiting on the operator", "blocked on the owner"
    rf"\b(waiting (for|on)|awaiting|blocked on) (the |my |our )?(ceo|cto|cfo|coo|founders?|owner|operator|boss|board|executives?|manager|legal)\b{_NOT_A_PERSON}|"
    # a seat named as the builder of a missing capability: "need the platform seat/Platform to expose a GUI wrapper"
    rf"\b(need|needs|needing) {_SEAT}(?:/\w+){{0,3}} to (expose|provide|grant|create|open|enable|build)\b)", _I)

# A person with authority named anywhere in a needs_input ask: the worker is asking that person.
_PRINCIPAL_NAMED = re.compile(rf"\b{_PRINCIPAL}\b{_NOT_A_PERSON}", _I)
# HOLD offered as one of the answers ("GO-DATA vs HOLD", "CONSOLE / HOLD") is a choice, not a parked card.
_HOLD_OPTION = re.compile(r"((\bvs\.?|/|\bor)\s*(?-i:HOLD)\b|(?-i:\bHOLD)\s*(\bvs\.?|/|\bor\b))", _I)

_WAIT_WORD = re.compile(r"\b(await\w*|waiting|approv\w*|ack|ok|okay|sign-?off|go(-?ahead)?|word|hold|decision|decide|ruling|call|need(s|ed)?)\b", _I)

_MACHINERY = re.compile(
    r"\b(read-?only (file ?system|fs)|errno ?\d+|no such file|not found|command not found|missing (binary|tool|package|dependency|module)|"
    r"no gpu|out of memory|oom|disk full|no space left|quota exceeded|rate[- ]limit(ed|ing)?|too many requests|429|timed? ?out|"
    r"crash(ed|es|-loop)?|segfault|unreachable|host (is )?(down|offline)|connection (refused|reset)|ssh .*fail|ci (is )?red|build fail\w*|"
    r"tests? fail\w*|schema mismatch|no (such )?action|unsupported (action|operation)|executor has no|spawn fail\w*|gave up after)\b",
    _I,
)

_DEPENDENCY = re.compile(r"\b(waiting on (task|card|parent|pr|issue) [#\w-]+|depends on (task|card|pr|issue) |blocked by ((task|card|parent|pr|issue) )?(t_[0-9a-f]+|#\d+)|after (t_[0-9a-f]+|#\d+) (lands|merges|finishes))", _I)

# A wall no agent can clear in its own lane: an appeal held by a person, an action only the human
# principal can take. Surfaced by the Income seat dogfood: without this, such cards read as
# "close the card" (stale-wait) when the only honest move is to escalate.
_CAPABILITY_WALL = re.compile(
    r"\b(ceo|owner|operator|principal)s?[- ]held\b|"
    r"\bno (agent|seat|bot|worker|tool) can (clear|lift|grant|approve|resolve|undo)\b|"
    r"\bonly (the ceo|the owner|the operator|a human|the principal) can\b|"
    r"\bappeal\w* (is|are|rests?|sits) with\b", _I)

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
    approvers = rf"(?:{seats}|[\w-]+[ -](agent|seat|bot|worker)s?)"
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
            rf"(awaiting|await|wait(ing)? (for|on)) (the |my |our )?{approvers}('s)? (approval|go-?ahead|green light|ok\b|okay|confirmation|sign-?off|ack|verdict|(delta )?(re-?)?(check|review)|to (sign[ -]?off|approv\w*|confirm|review|re-?check))\b|"
            rf"\b{approvers} (needs? to|must|has to|to) (sign[ -]?off|approv\w*|confirm|review)\b|"
            rf"\buntil (the )?{approvers} (reviews?|approves?|signs? off|acks?|confirms?|okays?|clears? it)\b)", _I)),
        (CEREMONY, re.compile(
            r"\b(attest(ation)?|receipt (card|chain|required)|re-?verify the (verification|receipt)|"
            r"review of (the )?review|countersign|ratif(y|ied|ication)|"
            r"acceptance (card|ritual)|ledger row|"
            r"contract (is|says) .{0,30}(cannot|can't) (mark|close)|cannot mark (it )?done" + (f"|{extra}" if extra else "") + r")", _I)),
        (PARKING, re.compile(
            r"((?-i:\bPARKED\b|\bHOLD\b)(?!er)|do not (re)?dispatch|parked by|keep (it )?blocked|preserve .{0,20}until further notice)", _I)),
    ]


_FAKE = _build_fake()


def wall_family(text: str) -> bool:
    """Ask mode's loose wall net, tested on the text with agent names removed. Seat names such as
    "Product", "Security" or "the board agent" name who is waited on, not a wall, so they must not
    stop the question that a wait on another agent is meant to get."""
    t = re.sub(r"\b[\w-]+[ -](agent|seat|bot|lane|worker)s?\b", " ", str(text or ""), flags=_I)
    t = re.sub(rf"\b{_seats_rx()}\b", " ", t, flags=_I)
    return bool(WALL_FAMILY.search(_without_llm_token_context(t)))


# An approval or review from a named party this plugin does not know ("approval from CoS", "until
# Compliance reviews"). The next actor is named, so "name the next actor or close the card" is wrong.
# It may be a person or an agent; safety bias reads it as a person's queue until the team adds the
# name to ``seats``.
_NAMED_APPROVER = re.compile(
    r"\b(approval|sign-?off|go-?ahead|ok|okay|ack|review|decision|ruling|confirmation)s? (from|by) (the )?[\w-]+|"
    r"\buntil (the )?[\w-]+ (reviews?|approves?|signs? off|acks?|confirms?|decides?|okays?)\b", _I)
NAMED_APPROVER_ACTION = ("A named approver this plugin does not know. If it is a person, it is their queue. "
                         "If it is an agent, add the name to seats so the plugin can judge the wait.")

_HOLD_WITH_EXPIRY = re.compile(r"\b(until|expires?|through|till)\s+\d{4}-\d{2}-\d{2}|\buntil \d{1,2}[/-]\d{1,2}\b", _I)

# A deliberate hold with a stated reason is not a parking lot: the work runs in another lane ("executed
# by zcode outside the gateway; do not dispatch"), or the card waits for room in a capped queue.
_RUNNING_ELSEWHERE = re.compile(
    r"\b((being )?(executed|executing|run|running|implemented|handled|worked on) (by|in|via) "
    r"(?!(the |an? )?(\w+ )?(approval|ack|sign-?off|ok|go-?ahead|review)\b)[\w.-]+|outside the (gateway|board|dispatcher)|"
    r"(supervisor|session|harness|owner) (now )?owns (this|the|it))\b", _I)
_THROTTLE = re.compile(
    r"\b((queue|backlog) (that |which )?(already )?ha(s|ve) \d+|max_in_progress\w*|throttl\w*|"
    r"queue (cap|limit)|(when|until|once) the queue has (capacity|room)|(max|maximum|at most) \d+ (in[ -]progress|running|at a time)|"
    r"so (it|they) (do(es)? not|don'?t|won'?t) auto-?dispatch)", _I)
# A wait on a running check (CI, a build, a test run) clears on its own; it is neither a gate nor a fault yet.
_RUNNING_CHECK = re.compile(
    r"\b(waiting|wait|await\w*) (for|on) (the )?(ci|build|tests?|test run|checks?|pipeline|workflow( run)?|job)\b"
    r"(?! (fail\w*|broke\w*|is red|errored))", _I)


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
    wall_text = _without_llm_token_context(t)
    walls = [(name, _hits(p, wall_text, skip_negated=True)) for name, p in _WALL]
    walls = [(n, h) for n, h in walls if h]
    fakes = [(sub, _hits(p, t)) for sub, p in _FAKE]
    fakes = [(s, h) for s, h in fakes if h]
    if kind == "needs_input" and _HOLD_OPTION.search(t):
        holds = len(re.findall(r"(?-i:\bHOLD\b)", t))
        if holds and holds <= len(_HOLD_OPTION.findall(t)):  # every HOLD is offered as an answer
            fakes = [(s, h) for s, h in fakes if s != PARKING]
    # An infra command reported as failing, with nothing waiting on anyone, is a fault, not a wall.
    if (walls and not fakes and all(_INFRA.fullmatch(h) for _, hs in walls for h in hs)
            and _INFRA_FAULT.search(t)):
        return Verdict(MACHINERY, "", 0.7, "an infra command failed", ACTIONS[MACHINERY], _hits(_INFRA_FAULT, t))
    if walls:
        names = ", ".join(n for n, _ in walls)
        return Verdict(WALL, names, 0.9, f"authority wall: {names}", ACTIONS[WALL], [h for _, hs in walls for h in hs])

    # Give direct classifier callers the gate's safety override for an explicit destructive or
    # security-control action. The loose family guard alone also matches incidental mentions.
    if wall_family(t) and _WALL_FAMILY_ACTION.search(t):
        return Verdict(WALL, "", 0.6, "possible authority wall", ACTIONS[WALL], [t])

    # 2. A question addressed to a person is the person's queue, never an agent gate.
    human = _hits(_HUMAN, t)
    if human:
        return Verdict(HUMAN, "", 0.8, "addressed to a person", ACTIONS[HUMAN], human)

    # 3. A real task dependency resumes on its own.
    if kind == "dependency" or _DEPENDENCY.search(t):
        return Verdict(DEPENDENCY, "", 0.8, "waits on another task, auto-resumes", ACTIONS[DEPENDENCY],
                       _hits(_DEPENDENCY, t) or ["kind=dependency"])

    # 4. The agent declared its kind: trust it. Hermes defines capability as a hard wall (no access, missing
    # credentials, an action no agent can do) that surfaces to a person; transient is a fault that may clear.
    if kind == "capability":
        return Verdict(WALL, "declared-capability", 0.6, "declared a hard wall (kind=capability)", ACTIONS[WALL],
                       ["kind=capability"])
    if kind == "transient":
        return Verdict(MACHINERY, "", 0.6, "declared transient gap", ACTIONS[MACHINERY], ["kind=transient"])

    # 4b. A wall no agent can clear: an appeal a person holds, an action only the principal can take.
    capwall = _hits(_CAPABILITY_WALL, t)
    if capwall and not fakes:
        return Verdict(WALL, "declared-capability", 0.6, "an agent cannot clear this; it belongs to a person",
                       ACTIONS[WALL], capwall)

    mach = _hits(_MACHINERY, t)

    # 5. A wait whose source is a person with authority is that person's call.
    # The strong form (the role acts, is asked to act, or its word is the noun) is evidence alone;
    # the weak form (the role is only referenced) still needs a wait word or a gate phrase.
    strong = _hits(_HUMAN_AUTHORITY_STRONG, t)
    authority = _hits(_HUMAN_AUTHORITY, t)
    if strong or (authority and (fakes or _WAIT_WORD.search(t))):
        return Verdict(HUMAN, "", 0.7, "a person's stop or approval", ACTIONS[HUMAN], strong or authority)

    # 6. A hold with an explicit expiry is legitimate parking.
    if fakes and [s for s, _ in fakes] == [PARKING] and _HOLD_WITH_EXPIRY.search(t):
        return Verdict(DEPENDENCY, "", 0.7, "time-boxed hold with an expiry; it lapses on its own",
                       "Leave it. When the expiry passes, dispatch or close it.", _hits(_HOLD_WITH_EXPIRY, t))

    # 6b. A deliberate hold that says why: the work runs in another lane, or it waits for queue room.
    if fakes and {s for s, _ in fakes} <= {PARKING, CEREMONY}:
        held = _hits(_RUNNING_ELSEWHERE, t) or _hits(_THROTTLE, t)
        if held:
            return Verdict(DEPENDENCY, "", 0.7, "a declared hold: the work runs elsewhere or waits for queue room",
                           "Leave it. Unblock it when the other lane lands or the queue has room.", held)

    # 7. needs_input is the worker's channel to a person. It stays HUMAN unless the text itself shows
    # an agent gate or a fault, in which case that wins with a little less certainty.
    # 7a. A needs_input ask that names a person with authority is that person's question, whatever
    # ceremony words ("ratify", "attest") or decision options it carries.
    if kind == "needs_input" and _PRINCIPAL_NAMED.search(t):
        return Verdict(HUMAN, "", 0.7, "needs_input naming a person with authority", ACTIONS[HUMAN],
                       _hits(_PRINCIPAL_NAMED, t))
    if kind == "needs_input" and not (fakes or mach):
        return Verdict(HUMAN, "", 0.7, "filed as needs_input", ACTIONS[HUMAN], ["kind=needs_input"])

    # 8. A fault with no gate layered on it.
    if mach and not fakes:
        return Verdict(MACHINERY, "", 0.75, "environment/tooling fault", ACTIONS[MACHINERY], mach)

    # 8b. A wait on a running check clears on its own.
    check = _hits(_RUNNING_CHECK, t)
    if check and not fakes:
        return Verdict(MACHINERY, "", 0.6, "waits on a running check; it clears on its own",
                       "Not a gate. Let the check finish; if it fails, fix it.", check)

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

    # 9b. A declared hold with no gate phrase at all ("throttled at 3 running", "the supervisor owns
    # this") is the same declared hold as 6b; don't let it fall through to a stale-wait default.
    held = _hits(_RUNNING_ELSEWHERE, t) or _hits(_THROTTLE, t)
    if held:
        return Verdict(DEPENDENCY, "", 0.7, "a declared hold: the work runs elsewhere or waits for queue room",
                       "Leave it. Unblock it when the other lane lands or the queue has room.", held)

    # 10. An approval from a named party the plugin does not know: a person until configured otherwise.
    named = _hits(_NAMED_APPROVER, t)
    if named:
        return Verdict(HUMAN, "", 0.5, "an approval from a named party this plugin does not know",
                       NAMED_APPROVER_ACTION, named)

    # 11. Defaults: no phrase matched. These are low-confidence and never "evidenced".
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
    "4 WALL: kind=capability (Hermes: a hard wall that surfaces to a person); MACHINERY: kind=transient",
    "5 HUMAN: a wait or gate phrase whose source is a person with authority ('from the CEO', 'per the owner', "
    "'the founder's OK', 'the CEO must sign'); a bare role noun, or an agent named after a role, does not count",
    "6 DEPENDENCY: a HOLD with an explicit expiry date, or a hold that names where the work runs or a queue cap (also when no gate phrase matched)",
    "7 HUMAN: kind=needs_input naming a person with authority (CEO, owner, operator...), or with no gate or fault phrase",
    "8 MACHINERY: a fault phrase, or a wait on a running check (CI, build, tests), with no gate phrase",
    "9 FAKE F1-F5: an agent-to-agent gate phrase (confidence 0.7-0.95, less when mixed with a fault or filed as needs_input)",
    "10 HUMAN (0.5): an approval or review from a named party that is not a configured seat ('approval from CoS')",
    "11 FAKE default, not evidenced: created blocked or empty (0.5), older than 24h (0.5), anything else (0.3)",
)
