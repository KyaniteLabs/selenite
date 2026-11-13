"""Selenite's anticowardice facet: notice a hedged, deferential or announce-only reply after the turn,
and cue the agent on its next turn.

Selenite's ``register`` calls :func:`register` here. This module adds:
- the ``post_llm_call`` hook: read the finished turn, run the deterministic detectors, ledger the modes
  (counts only, never message text) and, in ``cowardice_mode`` "nudge", hold one context note for that
  session's next ``pre_llm_call`` (Selenite's own pre_llm_call collects it with :func:`take_nudge`);
- the ``cowardice_check`` tool and the ``/anticowardice`` slash command, for checking a text by hand.

It never blocks a tool call, never edits a card or file, and any error fails open. Walls stand: the
detectors drop a sentence that names a known wall or hold, or sits next to one (see ``detect``). It also
runs inside kanban workers on purpose: a worker announcing a step instead of doing it is the case it exists for. Its ledger is
``$HERMES_HOME/plugin-data/anticowardice/ledger.jsonl`` (0600, rotating at 4 MB).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from . import MODES, Finding, ToolCall, Turn, analyze, nudge_text

logger = logging.getLogger(__name__)
PLUGIN = "anticowardice"
OWNER = "selenite"
OBSERVE, NUDGE = "observe", "nudge"
HOOKS_ON = lambda: True  # Selenite replaces this with its one off switch  # noqa: E731
LEDGER_ROTATE_BYTES = 4 * 1024 * 1024  # same bound as Selenite's own ledger
PENDING_MAX = 256       # sessions with a held nudge
TRANSCRIPT_CHARS = 20_000  # earlier transcript text kept for the "already answered" check
_ctx = None
_lock = threading.Lock()
_ledger_lock = threading.Lock()
_pending: "OrderedDict[str, str]" = OrderedDict()


def _cfg(key: str, default):
    try:
        val = _ctx.get_config(key, default) if _ctx is not None else default
    except Exception:  # pragma: no cover - host without settings
        val = default
    return default if val is None else val


def mode() -> str:
    """observe (the default: ledger only) or nudge. There is no mode that blocks."""
    m = str(_cfg("cowardice_mode", OBSERVE)).strip().lower()
    return m if m in (OBSERVE, NUDGE) else OBSERVE


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def data_dir() -> Path:
    d = _hermes_home() / "plugin-data" / PLUGIN
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger(event: str, **fields) -> None:
    """Metadata only: event, detector mode, session id. Never message text."""
    if not _cfg("cowardice_ledger", True):
        return
    rec = {"ts": round(time.time(), 3), "event": event, **{k: v for k, v in fields.items() if v not in (None, "")}}
    try:
        path = data_dir() / "ledger.jsonl"
        with _ledger_lock:  # rotation and append together, so two sessions cannot drop a row
            if path.exists() and path.stat().st_size >= LEDGER_ROTATE_BYTES:  # needs no cleansing: one rotated file kept
                os.replace(path, path.with_name("ledger.1.jsonl"))
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
    except OSError as exc:  # never let bookkeeping break a turn
        logger.warning("anticowardice ledger write failed: %s", exc)


# ---------------------------------------------------------------- reading a turn from Hermes history

def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def turn_from_history(user_message, assistant_response, history) -> Turn:
    """Build a Turn from the gateway's conversation history (OpenAI-style messages). The turn starts at the
    user message the host reports (Hermes adds its own user-role prompts mid-turn, so the last user row is
    not always the start); everything after it is this turn's tool traffic. Without a user row there is no
    way to tell this turn from earlier ones, so no tool traffic is assumed."""
    msgs = [m for m in (history if isinstance(history, (list, tuple)) else []) if isinstance(m, dict)]
    user = _text(user_message).strip()
    user_idx = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
    # The live row may carry a platform note or a prefix, so match by containment, latest row first.
    start = next((i for i in reversed(user_idx) if user and user in _text(msgs[i].get("content"))),
                 user_idx[-1] if user_idx else -1)
    this_turn = msgs[start + 1:] if start >= 0 else []
    before = msgs[:max(start, 0)]
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    for m in this_turn:
        try:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                    cid = str(tc.get("id") or len(order))
                    calls[cid] = ToolCall(str(fn.get("name", "")), str(fn.get("arguments", "")), "")
                    order.append(cid)
            elif m.get("role") == "tool":
                cid = str(m.get("tool_call_id", ""))
                old = calls.get(cid, ToolCall(str(m.get("name", ""))))
                calls[cid] = ToolCall(old.name, old.args, _text(m.get("content")))
                if cid not in order:
                    order.append(cid)
        except Exception:  # one malformed entry must not hide the rest of the turn
            continue
    prev = next((_text(m.get("content")) for m in reversed(before) if m.get("role") == "assistant" and _text(m.get("content")).strip()), "")
    # Only the user's own earlier words answer or hold a question; the agent's earlier words do not.
    context = "\n".join(_text(m.get("content")) for m in before if m.get("role") == "user")[-TRANSCRIPT_CHARS:]
    if not user and start >= 0:
        user = _text(msgs[start].get("content"))
    return Turn(assistant=str(assistant_response or ""), user=user, tools=[calls[c] for c in order],
                previous_assistant=prev, context=context)


# ---------------------------------------------------------------- hooks

def _key(session_id) -> str:
    return str(session_id or "-")  # the full id routes the note; only the ledger display is shortened


def take_nudge(session_id) -> str | None:
    """The held note for this session, once. Selenite's pre_llm_call adds it to the next turn's context.
    A note held before the mode went back to observe is dropped, not delivered."""
    with _lock:
        note = _pending.pop(_key(session_id), None)
    return note if note and mode() == NUDGE else None


def on_post_llm_call(session_id=None, user_message=None, assistant_response=None, conversation_history=None,
                     **_kw):
    try:
        if not HOOKS_ON() or not isinstance(assistant_response, str) or not assistant_response.strip():
            return None
        if str(_kw.get("platform") or "").lower() == "cron":  # nobody reads a nudge held for a cron session
            return None
        findings = analyze(turn_from_history(user_message, assistant_response, conversation_history))
        if not findings:
            return None
        sid = _key(session_id)[:64] if session_id else ""
        for f in findings:
            _ledger("finding", mode_id=f.mode, setting=mode(), session=sid)
        if mode() == NUDGE:
            with _lock:
                _pending.pop(_key(session_id), None)
                _pending[_key(session_id)] = nudge_text(findings)
                while len(_pending) > PENDING_MAX:
                    _pending.popitem(last=False)
    except Exception as exc:  # a friction plugin must never add friction, so it fails open, loudly
        logger.warning("anticowardice hook failed open: %s", exc)
    return None


# ---------------------------------------------------------------- tool and command

CHECK_SCHEMA = {
    "name": "cowardice_check",
    "description": ("Check one reply for epistemic cowardice: hedging where the evidence is clear, announcing a step instead of "
                    "taking it, ending on a fixable caveat, a narrow reading of a broad instruction, a question the context "
                    "already answers, flipping a claim after criticism, sycophantic agreement, or vague status. Deterministic, "
                    "advice only. A sentence that names a known wall or hold is left alone. Lexical and English only."),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The reply to check."},
            "user_message": {"type": "string", "description": "The instruction it answered, if known."},
            "previous_assistant": {"type": "string", "description": "The agent's message before the user's criticism, if any (needed for over-correction)."},
        },
        "required": ["text"],
    },
}


def _fmt(findings: list[Finding]) -> list[dict]:
    return [{"mode": f.mode, "phrase": f.phrase, "advice": f.advice} for f in findings]


def tool_check(args: dict | None = None, **_kw) -> str:
    args = args if isinstance(args, dict) else {}
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return json.dumps({"success": False, "error": "text is required"})
    user = args.get("user_message")
    prev = args.get("previous_assistant")
    found = analyze(Turn(assistant=text, user=user if isinstance(user, str) else "",
                         previous_assistant=prev if isinstance(prev, str) else ""))
    return json.dumps({"success": True, "findings": _fmt(found), "modes": list(MODES)})


HELP = """/anticowardice: does this reply hedge where it could commit?
  /anticowardice <text>   check one reply (no tools or context, so only text-only modes can fire)
  /anticowardice mode     show whether findings only go to the ledger (observe) or also nudge the agent"""


def slash(raw_args: str = "", **_kw) -> str:
    raw = str(raw_args or "").strip()
    if not raw or raw.lower() in ("help", "-h", "--help"):
        return HELP
    if raw.lower() == "mode":
        return f"anticowardice mode: {mode()} (set cowardice_mode to observe or nudge; it never blocks)"
    found = analyze(Turn(assistant=raw))
    if not found:
        return "No cowardice found in that text (a sentence that names a known wall or hold is left alone)."
    return "\n".join(f"{f.mode}: \"{f.phrase}\" -> {f.advice}" for f in found)


def register(ctx) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_tool(name="cowardice_check", toolset=OWNER, schema=CHECK_SCHEMA, handler=tool_check,
                      description=CHECK_SCHEMA["description"], emoji="🪨")
    ctx.register_command(PLUGIN, handler=slash, description="Does this reply hedge where it could commit?",
                         args_hint="[<text>|mode]")
    # Skills are registered once, by Selenite's register, for all four facets.
