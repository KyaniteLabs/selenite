"""Selenite: takes friction off the human, treated as accessibility.

Selenite is the stone used to clear the other stones, and it needs no
cleansing itself: no upkeep, self-trimming state. This Hermes plugin wraps
Selenite's four provider-agnostic facet skills and registers:

  skills   frictionless, antibeaurocracy, antipedantry, anticowardice   (skills/<name>/SKILL.md)
  commands /frictionless [cleanse|gate|calm|evolve|status] [text]
           /antibeaurocracy [audit|check|mode|ledger], /fake-gate <reason>, /anticowardice [<text>|mode]
  tools    selenite_ledger (add, summary, cleanse), selenite_show, bureaucracy_classify, bureaucracy_audit,
           cowardice_check
  hooks    pre_llm_call            -> Calm-mode context on the two-signal rule (never inside a kanban worker)
           post_approval_response  -> a human "once"/"session" on a safe, non-wall prompt logs an approval row;
                                      a human "always" logs that approval as fixed
           kanban_task_blocked     -> one observer: fake-gate verdict, plus a row when the wait lands on a human
           kanban_task_completed,
           on_kanban_task_updated  -> clear that task's blocked badge (and, on the dispatch tick,
                                      any badged card a person unblocked or archived)
           pre_tool_call, transform_tool_result, on_kanban_dispatch_tick
                                   -> the fake-gate facet (antibeaurocracy_core/plugin.py)
           post_llm_call           -> the anticowardice facet (anticowardice_core/plugin.py): ledger the finished
                                      turn's findings and, in cowardice_mode "nudge", hold one note that
                                      pre_llm_call adds to that session's next turn. Never blocks anything.

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
import time
from collections import OrderedDict
from pathlib import Path

try:
    from gateway.session_context import get_session_env
except ImportError:  # Older Hermes installs and local tooling have no gateway context package.
    get_session_env = None

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
pane = ledger.pane

# Hermes and the tests both load this file as a package, so the facet imports relatively.
from .antibeaurocracy_core import FAKE, HUMAN, WALL, WALLS_TEXT  # noqa: E402
from .antibeaurocracy_core import plugin as fake_gates  # noqa: E402
from .anticowardice_core import plugin as cowardice  # noqa: E402

SKILLS = {  # one product, four facets of one intent: fewer steps, waits and checks reach the human
    "frictionless": "Clear and recharge every other tool in the stack so fewer steps reach the human.",
    "antibeaurocracy": "Tell a real wall from a wait between agents that will end up on the human's desk.",
    "antipedantry": "Tell rigor from checks that cannot change the decision but still delay it.",
    "anticowardice": "Tell a real wall from a hedge, caveat or question that avoids a call the agent can already make.",
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
_APPROVAL_WORD = re.compile(r"\b(i|you) (have|need) to approve\b|\bapprov\w*", re.I)
_HUMAN_KINDS = frozenset({"needs_input", "capability"})  # Hermes: both surface to a person
# Kanban keys with an open blocked badge. Completion checks this set, and rereads the ledger only when
# another process (a worker) has written to it since the last read.
_blocked_now: set[str] = set()
_blocked_seen_sig = [None]

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

def _calm_context(session_id, user_message, parent_session_id, sender_id) -> str | None:
    # A kanban worker's "user message" is its card, not a person, so Calm never fires inside one.
    if parent_session_id or not isinstance(user_message, str) or os.environ.get("HERMES_KANBAN_TASK"):
        return None
    if not _calm_sender_ok(sender_id):
        return None
    reasons = signals.overload(user_message)
    previous = _remember(session_id or "-", bool(reasons))
    if not signals.calm_due(reasons, previous):
        return None
    ledger.add("calm", "+".join(sorted(set(reasons))), agent="hermes")
    return CALM_CONTEXT.format(reasons=", ".join(sorted(set(reasons))))


@_safe
def pre_llm_call(session_id=None, user_message=None, parent_session_id=None, sender_id=None, **_kw):
    """Calm-mode context on the two-signal rule, plus the anticowardice note held after this session's
    last turn (only when cowardice_mode is "nudge"). Either, both or neither."""
    if not _hooks_on():
        return None
    notes = [n for n in (_calm_context(session_id, user_message, parent_session_id, sender_id),
                         cowardice.take_nudge(session_id)) if n]
    return {"context": "\n\n".join(notes)} if notes else None


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
    step other than an approval (a login, an OTP, a manual step), which a person still has to do. With no evidence, the
    classifier's default is not a finding, so Selenite's own human-step words decide."""
    if kind in _HUMAN_KINDS:
        return True
    words = bool(_GATE_RE.search(reason)) or "human_gate" in signals.classify(reason)
    if verdict is not None and verdict.evidenced:
        if verdict.cls == FAKE:
            # The verdict already says the approval is one agent waiting on another, so an approval
            # word is not a person's step here; a login, an OTP or a manual step still is.
            rest = _APPROVAL_WORD.sub(" ", reason)
            return bool(_GATE_RE.search(rest)) or "human_gate" in signals.classify(rest)
        return verdict.cls in (WALL, HUMAN)
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
    sig = ledger.signature()  # every state folder: a row in a fallback folder still clears a badge
    if sig != _blocked_seen_sig[0]:
        _blocked_seen_sig[0] = sig
        rows = list(ledger.rows(ledger.BLOCKED_DAYS))
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
    """A status change on a card blocked on a person means someone moved it on (unblocked or archived).
    Hermes sends no status field for those, so any update to a badged card checks the board too."""
    if not (_hooks_on() and task_id):
        return
    if "status" in (changed_fields or ()):
        _clear_badge(task_id, "task unblocked")
    elif f"kanban:{task_id}" in _open_badges():
        reconcile_badges([str(task_id)])


_MOVED_ON = {"archived": "task archived", "done": "task completed"}
RECONCILE_EVERY_S = 60.0
_reconciled_at = [0.0]


def reconcile_badges(task_ids=None) -> int:
    """Clear the badge of every card a person has since unblocked or archived. Hermes fires no hook
    for either, so this reads each badged card's status from its board, read-only. A card missing
    from every board keeps its badge: unknown is not cleared. Returns how many it cleared."""
    ids = list(task_ids) if task_ids is not None else [
        k.split(":", 1)[1] for k in sorted(_open_badges()) if k.startswith("kanban:")]
    if not ids:
        return 0
    statuses = fake_gates.card_statuses(ids)
    cleared = 0
    for tid in ids:
        st = statuses.get(tid)
        if st and st != "blocked":
            _clear_badge(tid, _MOVED_ON.get(st, "task unblocked"))
            cleared += 1
    return cleared


def _tick_reconcile() -> None:
    """On the dispatcher tick, at most once a minute."""
    now = time.time()
    if now - _reconciled_at[0] < RECONCILE_EVERY_S:
        return
    _reconciled_at[0] = now
    if _hooks_on():
        reconcile_badges()


# --- command ---------------------------------------------------------------

def frictionless_command(raw_args: str, *, session_key: str | None = None) -> str:
    """Hand the request to the agent as a user turn; the reply to the human says what happened.

    A slash command's return value is printed to the human, never sent to the agent, so the
    agent-facing instructions travel through ``ctx.inject_message``. Where no agent turn can be
    started (an old host, or a gateway without injection allowed), the human gets the text to send.
    """
    if (raw_args or "").strip().lower() == "status":
        return "Selenite updates its Desktop page through local events when open and enabled. " + pane.SETUP
    mode, prompt = frictionless_prompt(raw_args)
    what = f"{mode.capitalize()} mode" if mode else "your request"
    inject = getattr(_ctx, "inject_message", None)
    try:
        if not session_key:
            session_key = get_session_env("HERMES_SESSION_KEY", "") if get_session_env else os.environ.get("HERMES_SESSION_KEY")
        sent = bool(inject(prompt, session_key=session_key or None)) if inject else False
    except Exception as exc:  # noqa: BLE001 - a failed hand-off must still answer the human
        logger.warning("frictionless: could not start an agent turn: %s", exc)
        sent = False
    if sent:
        return f"Selenite: handed {what} to your agent. It loads the frictionless skill and reports back here."
    return ("Selenite could not start an agent turn from this surface. Send this to your agent:\n\n"
            + prompt)


def frictionless_prompt(raw_args: str) -> tuple[str, str]:
    """(mode, the agent-facing instruction) for ``/frictionless`` arguments."""
    raw = (raw_args or "").strip()
    parts = raw.split(None, 1)
    word = parts[0].lower() if parts else ""
    mode = ALIASES.get(word, word) if ALIASES.get(word, word) in MODES else ""
    rest = (parts[1] if len(parts) > 1 else "") if mode else raw
    head = "Load and follow the frictionless skill (skill_view name='selenite:frictionless').\n\n"
    if mode == "evolve":
        return mode, head + (
            "Run Evolve mode: run skills/frictionless/scripts/mine.py and cleanse.py at low priority, "
            "then evolve.py, read the proposal, and draft the accepted changes on a local branch of "
            "the Selenite repo. Opening a PR is the human's decision. Never edit the installed copy directly.\n"
            f"Plugin root: {ROOT}\n" + (f"Focus: {rest}\n" if rest else "")
        )
    if mode == "cleanse":
        return mode, head + (
            "Run Cleanse mode: run skills/frictionless/scripts/cleanse.py (read-only), take the top "
            "finding, and clear it with a reviewable change in the repo that owns that stone.\n"
            f"Plugin root: {ROOT}\n" + (f"Focus: {rest}\n" if rest else "")
        )
    if mode:
        return mode, head + f"Run {mode.capitalize()} mode." + (f"\n\nContext: {rest}" if rest else "")
    return "", head + ("Pick the mode from the context." + (f"\n\nContext: {rest}" if rest else ""))


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

SHOW_SCHEMA = {
    "name": "selenite_show",
    "description": "Ask the open, enabled Selenite Desktop page to show a section and optionally focus an item.",
    "parameters": {
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": list(pane.VIEWS), "maxLength": 16},
            "item_id": {"type": "string", "maxLength": 80, "pattern": "^" + pane.ITEM_PATTERN + "$",
                        "description": "Optional short gate/ledger key, fake-gate card id, cleanse check id or signal id; no paths or private text."},
        },
        "required": ["view"],
        "additionalProperties": False,
    },
}


def selenite_show(args: dict | None = None, **_kw) -> str:
    if not pane.valid_view(args):
        return ("Error: view must be one of " + ", ".join(pane.VIEWS)
                + "; optional item_id must be 1-80 letters, digits, underscores, colons or hyphens.")
    pane.broadcast("view.set", args)
    item = f", item {args['item_id']}" if "item_id" in args else ""
    return f"Asked Selenite to show {args['view']}{item}; the Desktop page must be open and enabled."


def selenite_ledger(args: dict, **_kw) -> str:
    action = args.get("action")
    if not action:
        return json.dumps({"success": False, "error": "action is required"})
    if action not in LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"]:
        return json.dumps({"success": False, "error": f"unknown action: {action}"})
    try:
        if action == "add":
            for field in ("kind", "key"):
                if not str(args.get(field) or "").strip():
                    return json.dumps({"success": False, "error": f"{field} is required"})
            row = ledger.add(args["kind"], args["key"], args.get("note", ""), "hermes")
            if row is None:   # no writable state destination: nothing was recorded, so do not say it was
                return json.dumps({"success": False, "row": None,
                                   "error": "ledger not writable: the row was not recorded"})
            return json.dumps({"success": True, "row": row})
        if action == "cleanse":
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
                         args_hint="[cleanse|gate|calm|evolve|status] [context]")
    ctx.register_tool(name="selenite_ledger", toolset="selenite", schema=LEDGER_SCHEMA,
                      handler=selenite_ledger, description=LEDGER_SCHEMA["description"], emoji="🤍")
    ctx.register_tool(name="selenite_show", toolset="selenite", schema=SHOW_SCHEMA,
                      handler=selenite_show, description=SHOW_SCHEMA["description"], emoji="🤍")
    for hook in (pre_llm_call, post_approval_response,
                 kanban_task_blocked, kanban_task_completed, on_kanban_task_updated):
        ctx.register_hook(hook.__name__, hook)
    fake_gates.HOOKS_ON = _hooks_on  # one off switch for every hook Selenite runs
    cowardice.HOOKS_ON = _hooks_on
    fake_gates.on_tick(_tick_reconcile)
    fake_gates.register(ctx)
    cowardice.register(ctx)
