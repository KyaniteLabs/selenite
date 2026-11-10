"""Selenite: takes friction off the human, treated as accessibility.

Selenite is the stone used to clear the other stones, and it needs no
cleansing itself: no upkeep, self-trimming state. This Hermes plugin wraps
Selenite's three provider-agnostic facet skills and registers:

  skills   frictionless, antibeaurocracy, antipedantry   (skills/<name>/SKILL.md)
  commands /frictionless [cleanse|gate|calm|evolve] [text]
           /antibeaurocracy [audit|check|mode|ledger], /fake-gate <reason>
  tools    selenite_ledger (add, summary, cleanse), bureaucracy_classify, bureaucracy_audit
  hooks    pre_llm_call            -> Calm-mode context on the two-signal rule (never inside a kanban worker)
           post_approval_response  -> a human "once"/"session" on a safe, non-wall prompt logs an approval row;
                                      a human "always" logs that approval as fixed
           kanban_task_blocked     -> one observer: fake-gate verdict, plus a row when the wait lands on a human
           kanban_task_completed,
           on_kanban_task_updated  -> clear that task's blocked badge
           pre_tool_call, transform_tool_result, on_kanban_dispatch_tick
                                   -> the fake-gate facet (antibeaurocracy_core/plugin.py)

Hooks never approve, unblock or edit a card. Only fake_gate_mode "ask" hands a
kanban_block back with a question, at most max_refusals times, and fails open.
Turn every hook off with the `hooks` setting or SELENITE_HOOKS=0.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT / "skills" / "frictionless"


def _scripts(*names: str):
    """Load the skill's scripts as `selenite_frictionless.<name>`.

    A namespaced package keeps generic names (ledger, signals, evolve) out of
    sys.modules and sys.path, so they cannot collide with other plugins.
    """
    import importlib
    import importlib.util

    pkg = "selenite_frictionless"
    if pkg not in sys.modules:
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(pkg, loader=None, is_package=True))
        mod.__path__ = [str(SKILL_DIR / "scripts")]
        sys.modules[pkg] = mod
    return [importlib.import_module(f"{pkg}.{n}") for n in names]


cleanse, ledger, signals = _scripts("cleanse", "ledger", "signals")

# Hermes and the tests both load this file as a package, so the facet imports relatively.
from .antibeaurocracy_core import FAKE, HUMAN, WALL, WALLS_TEXT  # noqa: E402
from .antibeaurocracy_core import plugin as fake_gates  # noqa: E402

SKILLS = {  # one product, three facets of one intent: fewer steps, waits and checks reach the human
    "frictionless": "Clear and recharge every other tool in the stack so fewer steps reach the human.",
    "antibeaurocracy": "Tell a real wall from a wait between agents that will end up on the human's desk.",
    "antipedantry": "Tell rigor from checks that cannot change the decision but still delay it.",
}

MODES = ("cleanse", "gate", "calm", "evolve")
ALIASES = {"audit": "cleanse"}  # the 0.3 name for the same pass

CALM_CONTEXT = (
    "[selenite] Overload signals in the human's messages ({reasons}). Use the "
    "frictionless skill's Calm mode: find and fix the skipped rule first, pick the "
    "sensible default and act instead of asking, reply with a one-line result plus "
    "one next action, and verify against live state. Walls still stand and still "
    "get one short question: " + WALLS_TEXT.replace("{", "{{").replace("}", "}}") + "."
)

# Approval prompts that must never become allowlist candidates: payments, MCP trust and elicitation,
# and any Hermes pattern key that names a wall or a destructive step.
_NO_ALLOWLIST_SURFACE = re.compile(r"^(vault-payment|mcp-)", re.I)
_WALL_KEY = re.compile(
    r"delet|drop|truncat|wipe|format|kill|destruct|disk|block device|secret|ssh key|chown|writable|boot|"
    r"backup|shadow|registry|partition|remote content|force|overwrite|stop|fork bomb|payment|"
    r"credential|token|password|publish|deploy|visib|spend|purchas", re.I)

# A blocked Kanban task counts as waiting on a human only on these whole words.
_GATE_RE = re.compile(
    r"\b(human|approv(al|e|ed)|log ?in|sign ?in|2fa|otp|credentials?|api key|"
    r"manual(ly)?|needs? (the )?(owner|user|operator|ceo))\b", re.I)
_HUMAN_KINDS = frozenset({"needs_input", "capability"})  # Hermes: both surface to a person
# Kanban keys with an open blocked badge. Completion checks this set, and rereads the ledger only when
# another process (a worker) has written to it since the last read.
_blocked_now: set[str] = set()
_blocked_seen_mtime = [None]

STREAK_MAX = 256  # sessions remembered for the two-signal rule
_streak: "OrderedDict[str, bool]" = OrderedDict()  # session -> previous message had a reason
_ctx = None


def _cfg(key: str, default):
    try:
        val = _ctx.get_config(key, default) if _ctx is not None else default
    except Exception:
        val = default
    return default if val is None else val


def _hooks_on() -> bool:
    if os.environ.get("SELENITE_HOOKS", "1") == "0":
        return False
    return bool(_cfg("hooks", True))


def _calm_sender_ok(sender_id) -> bool:
    """In shared chats, only the configured people count toward Calm."""
    allowed = {s.strip() for s in str(_cfg("calm_senders", "")).split(",") if s.strip()}
    return not allowed or (sender_id is not None and str(sender_id) in allowed)


def _remember(key: str, had_reason: bool) -> bool:
    prev = _streak.pop(key, False)
    _streak[key] = had_reason
    while len(_streak) > STREAK_MAX:
        _streak.popitem(last=False)
    return prev


def _safe(fn):
    def wrapped(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # a friction plugin must never add friction, so it fails open, loudly
            logger.warning("selenite hook %s failed open: %s", fn.__name__, exc)
            return None
    wrapped.__name__ = fn.__name__
    return wrapped


# --- hooks -----------------------------------------------------------------

@_safe
def pre_llm_call(session_id=None, user_message=None, parent_session_id=None, sender_id=None, **_kw):
    # A kanban worker's "user message" is its card, not a person, so Calm never fires inside one.
    if not _hooks_on() or parent_session_id or not isinstance(user_message, str) or os.environ.get("HERMES_KANBAN_TASK"):
        return None
    if not _calm_sender_ok(sender_id):
        return None
    reasons = signals.overload(user_message)
    previous = _remember(session_id or "-", bool(reasons))
    if not signals.calm_due(reasons, previous):
        return None
    ledger.add("calm", "+".join(sorted(set(reasons))), agent="hermes")
    return {"context": CALM_CONTEXT.format(reasons=", ".join(sorted(set(reasons))))}


def allowlist_candidate(pattern_key, surface, choice, decided_by) -> bool:
    """Only a person's own once/session approval of a safe, reversible prompt is a candidate to allowlist.
    Denials, timeouts, cancels, the smart (aux LLM) approver, payments, MCP trust and any wall or
    destructive pattern are never offered: allowlisting those would remove a real wall."""
    if choice not in ("once", "session") or decided_by == "aux_llm" or not pattern_key:
        return False
    if _NO_ALLOWLIST_SURFACE.match(str(surface or "")):
        return False
    return not _WALL_KEY.search(str(pattern_key))


@_safe
def post_approval_response(pattern_key=None, choice=None, decided_by=None, surface=None, **_kw):
    if not _hooks_on() or not pattern_key or decided_by == "aux_llm":
        return
    key = str(pattern_key)[:ledger.APPROVAL_KEY]
    if choice == "always":  # the person allowlisted it by hand: that approval stops interrupting
        ledger.add("fix", f"approval:{key}", note="allowlisted by the human", agent="hermes")
    elif allowlist_candidate(pattern_key, surface, choice, decided_by):
        ledger.add("approval", key, note=f"surface={surface}", agent="hermes")


def lands_on_a_human(reason: str, verdict, kind: str | None = None) -> bool:
    """One routing rule for every block. A declared needs_input or capability kind lands on a person
    (Hermes surfaces both to one). Otherwise an evidenced verdict decides: WALL and HUMAN wait on a
    person, DEPENDENCY and MACHINERY do not, and FAKE does not unless the reason also names a human
    step (a login, an OTP, an approval), which a person still has to do. With no evidence, the
    classifier's default is not a finding, so Selenite's own human-step words decide."""
    if kind in _HUMAN_KINDS:
        return True
    words = bool(_GATE_RE.search(reason)) or "human_gate" in signals.classify(reason)
    if verdict is not None and verdict.evidenced:
        return verdict.cls in (WALL, HUMAN) or (verdict.cls == FAKE and words)
    return words


@_safe
def kanban_task_blocked(task_id=None, reason=None, assignee=None, board=None, **_kw):
    """The one observer for blocked cards: classify once, ledger the fake-gate verdict, and log the
    task on Selenite's ledger when the wait lands on a person. Never keeps the reason text.
    Hermes passes no kind here, so the facet recovers it (see observe_block)."""
    if not _hooks_on() or not task_id:
        return
    reason = reason if isinstance(reason, str) else ""
    verdict, kind = fake_gates.observe_block(task_id=str(task_id), board=board, reason=reason, kind=_kw.get("kind"))
    if (reason or kind) and lands_on_a_human(reason, verdict, kind):
        key = f"kanban:{task_id}"
        ledger.add("blocked", key, note="waiting on a human", agent=str(assignee or "hermes")[:40])
        _blocked_now.add(key)


def _open_badges() -> set[str]:
    try:
        mtime = ledger.LEDGER.stat().st_mtime_ns
    except OSError:
        mtime = 0
    if mtime != _blocked_seen_mtime[0]:
        _blocked_seen_mtime[0] = mtime
        rows = list(ledger.rows(90))
        fixed = ledger.fixed_keys(source=rows)
        _blocked_now.clear()
        _blocked_now.update(r["key"] for r in rows if r["kind"] == "blocked" and r["key"] not in fixed)
    return _blocked_now


def _clear_badge(task_id, note: str) -> None:
    key = f"kanban:{task_id}"
    if key in _blocked_now or key in _open_badges():
        _blocked_now.discard(key)
        ledger.add("fix", key, note=note, agent="hermes")


@_safe
def kanban_task_completed(task_id=None, **_kw):
    if _hooks_on() and task_id:
        _clear_badge(task_id, "task completed")


@_safe
def on_kanban_task_updated(task_id=None, changed_fields=None, **_kw):
    """A status change on a card blocked on a person means someone moved it on (unblocked or archived)."""
    if _hooks_on() and task_id and "status" in (changed_fields or ()):
        _clear_badge(task_id, "task unblocked")


# --- command ---------------------------------------------------------------

def frictionless_command(raw_args: str) -> str:
    raw = (raw_args or "").strip()
    parts = raw.split(None, 1)
    word = parts[0].lower() if parts else ""
    mode = ALIASES.get(word, word) if ALIASES.get(word, word) in MODES else ""
    rest = (parts[1] if len(parts) > 1 else "") if mode else raw
    head = "Load and follow the frictionless skill (skill_view name='selenite:frictionless').\n\n"
    if mode == "evolve":
        return head + (
            "Run Evolve mode: run skills/frictionless/scripts/mine.py and cleanse.py at low priority, "
            "then evolve.py, read the proposal, and draft the accepted changes on a local branch of "
            "the Selenite repo. Opening a PR is the human's decision. Never edit the installed copy directly.\n"
            f"Plugin root: {ROOT}\n" + (f"Focus: {rest}\n" if rest else "")
        )
    if mode == "cleanse":
        return head + (
            "Run Cleanse mode: run skills/frictionless/scripts/cleanse.py (read-only), take the top "
            "finding, and clear it with a reviewable change in the repo that owns that stone.\n"
            f"Plugin root: {ROOT}\n" + (f"Focus: {rest}\n" if rest else "")
        )
    if mode:
        return head + f"Run {mode.capitalize()} mode." + (f"\n\nContext: {rest}" if rest else "")
    return head + ("Pick the mode from the context." + (f"\n\nContext: {rest}" if rest else ""))


# --- tool ------------------------------------------------------------------

LEDGER_SCHEMA = {
    "name": "selenite_ledger",
    "description": (
        "Selenite's ledger and cleanse pass. action=add records one friction event (kind, key, note); "
        "action=summary returns the top recurring frictions; action=cleanse ranks what to clear across "
        "the stack (skills, plugins, hooks, approvals, gates) and returns the top findings with fixes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "summary", "cleanse"]},
            "kind": {"type": "string", "enum": sorted(ledger.KINDS)},
            "key": {"type": "string", "description": "short stable slug, e.g. gh-login"},
            "note": {"type": "string", "description": "no secrets; max 200 chars"},
            "days": {"type": "integer", "default": 30},
        },
        "required": ["action"],
    },
}


def selenite_ledger(args: dict, **_kw) -> str:
    try:
        if args.get("action") == "add":
            row = ledger.add(args["kind"], args["key"], args.get("note", ""), "hermes")
            return json.dumps({"success": True, "row": row})
        if args.get("action") == "cleanse":
            report = cleanse.run(int(args.get("days", 30)))
            cleanse.write(report)
            return json.dumps({"success": True, "findings": report["findings"][:15],
                               "total": len(report["findings"]), "by_stone": report["by_stone"]})
        return json.dumps({"success": True, **ledger.summary(int(args.get("days", 30)))})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# --- registration ----------------------------------------------------------

def register(ctx) -> None:
    global _ctx
    _ctx = ctx
    for name, description in SKILLS.items():
        ctx.register_skill(name, ROOT / "skills" / name / "SKILL.md", description=description)
    ctx.register_command(name="frictionless", handler=frictionless_command,
                         description="Selenite: cleanse the stack, shrink a human step, calm mode, evolve",
                         args_hint="[cleanse|gate|calm|evolve] [context]")
    ctx.register_tool(name="selenite_ledger", toolset="selenite", schema=LEDGER_SCHEMA,
                      handler=selenite_ledger, description=LEDGER_SCHEMA["description"], emoji="🤍")
    for hook in (pre_llm_call, post_approval_response,
                 kanban_task_blocked, kanban_task_completed, on_kanban_task_updated):
        ctx.register_hook(hook.__name__, hook)
    fake_gates.HOOKS_ON = _hooks_on  # one off switch for every hook Selenite runs
    fake_gates.register(ctx)
