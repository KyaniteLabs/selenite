"""Selenite: a Hermes plugin wrapping the provider-agnostic `frictionless` skill.

Registers:
  skill    selenite:frictionless   (skills/frictionless/SKILL.md)
  command  /frictionless [gate|audit|calm|evolve] [text]
  tool     selenite_ledger         (add / summary of friction events)
  hooks    pre_llm_call            -> Calm-mode context when overload shows
           pre_approval_request    -> logs repeating approval prompts
           post_approval_response  -> logs the human's choice
           kanban_task_blocked     -> logs tasks blocked on a human

Hooks only observe and add context. They never block, approve or edit.
Set SELENITE_HOOKS=0 to disable them.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT / "skills" / "frictionless"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import ledger  # noqa: E402
import signals  # noqa: E402

MODES = ("gate", "audit", "calm", "evolve")

CALM_CONTEXT = (
    "[selenite] Overload signals in the human's message ({reasons}). Use the "
    "frictionless skill's Calm mode: find and fix the skipped rule first, ask no "
    "clarifying questions, pick the sensible default and act, reply with a "
    "one-line result plus one next action, and verify against live state."
)

_GATE_WORDS = ("human", "approval", "approve", "login", "log in", "token", "2fa",
               "otp", "credential", "manual", "owner", "ceo", "needs ")

_streak: dict[str, int] = {}


def _hooks_on() -> bool:
    return os.environ.get("SELENITE_HOOKS", "1") != "0"


def _safe(fn):
    def wrapped(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # a friction plugin must never add friction
            logger.debug("selenite hook %s failed: %s", fn.__name__, exc)
            return None
    wrapped.__name__ = fn.__name__
    return wrapped


# --- hooks -----------------------------------------------------------------

@_safe
def pre_llm_call(session_id=None, user_message=None, parent_session_id=None, **_kw):
    if not _hooks_on() or parent_session_id or not isinstance(user_message, str):
        return None
    reasons = signals.overload(user_message)
    key = session_id or "-"
    if not reasons:
        _streak.pop(key, None)
        return None
    _streak[key] = _streak.get(key, 0) + 1
    ledger.add("calm", "+".join(sorted(reasons)), agent="hermes")
    ctx = CALM_CONTEXT.format(reasons=", ".join(reasons))
    if _streak[key] >= 2:
        ctx += " Second signal in a row: stop explaining and only act."
    return {"context": ctx}


@_safe
def pre_approval_request(pattern_key=None, surface=None, **_kw):
    if _hooks_on():
        ledger.add("approval", str(pattern_key or "unknown"), note=f"surface={surface}", agent="hermes")


@_safe
def post_approval_response(pattern_key=None, choice=None, **_kw):
    # "always" means the human just did the allowlisting by hand: a fix candidate.
    if _hooks_on() and choice in ("once", "session"):
        ledger.add("approval", f"{pattern_key}:{choice}", agent="hermes")


@_safe
def kanban_task_blocked(task_id=None, reason=None, assignee=None, **_kw):
    if not _hooks_on() or not reason:
        return
    low = reason.lower()
    if any(w in low for w in _GATE_WORDS) or "human_gate" in signals.classify(reason):
        ledger.add("blocked", f"kanban:{task_id}", note=reason[:200], agent=assignee or "hermes")


# --- command ---------------------------------------------------------------

def frictionless_command(raw_args: str) -> str:
    parts = (raw_args or "").strip().split(None, 1)
    mode = parts[0].lower() if parts and parts[0].lower() in MODES else ""
    rest = parts[1] if mode and len(parts) > 1 else ("" if mode else (raw_args or "").strip())
    head = "Load and follow the frictionless skill (skill_view name='selenite:frictionless').\n\n"
    if mode == "evolve":
        return head + (
            "Run Evolve mode: run skills/frictionless/scripts/mine.py at low priority, "
            "then evolve.py, read the proposal, and open one PR against the Selenite repo "
            "with the accepted changes. Never edit the installed copy directly.\n"
            f"Plugin root: {ROOT}\n" + (f"Focus: {rest}\n" if rest else "")
        )
    if mode:
        return head + f"Run {mode.capitalize()} mode." + (f"\n\nContext: {rest}" if rest else "")
    return head + ("Pick the mode from the context." + (f"\n\nContext: {rest}" if rest else ""))


# --- tool ------------------------------------------------------------------

LEDGER_SCHEMA = {
    "name": "selenite_ledger",
    "description": (
        "Log or summarize friction events for the Selenite frictionless skill. "
        "action=add records one event (kind, key, note); action=summary returns the top recurring frictions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "summary"]},
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
        return json.dumps({"success": True, **ledger.summary(int(args.get("days", 30)))})
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# --- registration ----------------------------------------------------------

def register(ctx) -> None:
    ctx.register_skill("frictionless", SKILL_DIR / "SKILL.md",
                       description="Remove friction between a human and their agents.")
    ctx.register_command(name="frictionless", handler=frictionless_command,
                         description="Selenite: shrink human steps, audit friction, calm mode, evolve",
                         args_hint="[gate|audit|calm|evolve] [context]")
    ctx.register_tool(name="selenite_ledger", toolset="selenite", schema=LEDGER_SCHEMA,
                      handler=selenite_ledger, description=LEDGER_SCHEMA["description"], emoji="🌙")
    for hook in (pre_llm_call, pre_approval_request, post_approval_response, kanban_task_blocked):
        ctx.register_hook(hook.__name__, hook)
