"""Selenite: takes friction off the human, treated as accessibility.

Selenite is the stone used to clear the other stones, and it needs no
cleansing itself: no upkeep, self-trimming state. This Hermes plugin wraps
Selenite's three provider-agnostic facet skills and registers:

  skills   frictionless, antibeaurocracy, antipedantry   (skills/<name>/SKILL.md)
  commands /frictionless [cleanse|gate|calm|evolve] [text]
           /antibeaurocracy [audit|check|mode|ledger], /fake-gate <reason>
  tools    selenite_ledger (add, summary, cleanse), bureaucracy_classify, bureaucracy_audit
  hooks    pre_llm_call            -> Calm-mode context on the two-signal rule
           pre_approval_request    -> one row per human approval prompt
           post_approval_response  -> a human "always" logs that approval as fixed
           kanban_task_blocked     -> one observer: fake-gate verdict, plus a row when the wait lands on a human
           kanban_task_completed   -> clears that task's blocked badge
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
from .antibeaurocracy_core import HUMAN, WALL  # noqa: E402
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
    "frictionless skill's Calm mode: find and fix the skipped rule first, ask no "
    "clarifying questions, pick the sensible default and act, reply with a "
    "one-line result plus one next action, and verify against live state. "
    "Authority walls still stand: spending, deleting, publishing, changing "
    "visibility and new credentials still need explicit approval."
)

# A blocked Kanban task counts as waiting on a human only on these whole words.
_GATE_RE = re.compile(
    r"\b(human|approv(al|e|ed)|log ?in|sign ?in|2fa|otp|credentials?|api key|"
    r"manual(ly)?|needs? (the )?(owner|user|operator|ceo))\b", re.I)

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
    if not _hooks_on() or parent_session_id or not isinstance(user_message, str):
        return None
    if not _calm_sender_ok(sender_id):
        return None
    reasons = signals.overload(user_message)
    previous = _remember(session_id or "-", bool(reasons))
    if not signals.calm_due(reasons, previous):
        return None
    ledger.add("calm", "+".join(sorted(set(reasons))), agent="hermes")
    return {"context": CALM_CONTEXT.format(reasons=", ".join(sorted(set(reasons))))}


@_safe
def pre_approval_request(pattern_key=None, surface=None, coalesced=False, **_kw):
    # One row per prompt a human actually sees: the smart approver and
    # follower prompts folded into another one are not human interruptions.
    if not _hooks_on() or coalesced or surface == "smart":
        return
    ledger.add("approval", str(pattern_key or "unknown")[:80], note=f"surface={surface}", agent="hermes")


@_safe
def post_approval_response(pattern_key=None, choice=None, decided_by=None, **_kw):
    # A human "always" allowlisted it by hand: that approval stops interrupting.
    if _hooks_on() and choice == "always" and decided_by != "aux_llm" and pattern_key:
        ledger.add("fix", f"approval:{str(pattern_key)[:70]}", note="allowlisted by the human", agent="hermes")


def lands_on_a_human(reason: str, verdict) -> bool:
    """One routing rule for every block. An evidenced verdict decides: WALL and HUMAN wait on a person,
    FAKE, DEPENDENCY and MACHINERY do not (a fake gate is an agent's job to dissolve). With no evidence,
    the classifier's default is not a finding, so Selenite's own human-step words decide."""
    if verdict is not None and verdict.evidenced:
        return verdict.cls in (WALL, HUMAN)
    return bool(_GATE_RE.search(reason)) or "human_gate" in signals.classify(reason)


@_safe
def kanban_task_blocked(task_id=None, reason=None, assignee=None, board=None, **_kw):
    """The one observer for blocked cards: classify once, ledger the fake-gate verdict, and log the
    task on Selenite's ledger when the wait lands on a person. Never keeps the reason text."""
    if not _hooks_on() or not task_id:
        return
    reason = reason if isinstance(reason, str) else ""
    verdict = fake_gates.observe_block(task_id=str(task_id), board=board, reason=reason, kind=_kw.get("kind"))
    if reason and lands_on_a_human(reason, verdict):
        ledger.add("blocked", f"kanban:{task_id}", note="waiting on a human", agent=str(assignee or "hermes")[:40])


@_safe
def kanban_task_completed(task_id=None, **_kw):
    if not _hooks_on() or not task_id:
        return
    key = f"kanban:{task_id}"
    if any(r["kind"] == "blocked" and r["key"] == key for r in ledger.rows(90)):
        ledger.add("fix", key, note="task completed", agent="hermes")


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
            "then evolve.py, read the proposal, and open one PR against the Selenite repo "
            "with the accepted changes. Never edit the installed copy directly.\n"
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
    for hook in (pre_llm_call, pre_approval_request, post_approval_response,
                 kanban_task_blocked, kanban_task_completed):
        ctx.register_hook(hook.__name__, hook)
    fake_gates.HOOKS_ON = _hooks_on  # one off switch for every hook Selenite runs
    fake_gates.register(ctx)
