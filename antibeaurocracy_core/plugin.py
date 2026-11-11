"""Selenite's fake-gate facet: notice agent-to-agent waits as they form, and audit the ones already standing.

Part of Selenite, whose one intent is to take friction off the human. A wait between agents that
is not a real wall ends up on a person's desk as a stale board to untangle, so Selenite treats it
as human friction caught early. Walls always stand (classify.WALLS is the one list).

Selenite's ``register`` calls :func:`register` here. This module adds:
- hooks ``pre_tool_call`` / ``transform_tool_result`` on ``kanban_block`` and a throttled
  ``on_kanban_dispatch_tick`` snapshot. ``kanban_task_blocked`` is not registered here: Selenite
  runs one observer that classifies each block once and calls :func:`on_kanban_task_blocked`;
- tools ``bureaucracy_classify`` and ``bureaucracy_audit`` (counts only);
- ``/antibeaurocracy`` and ``/fake-gate`` slash commands and ``hermes antibeaurocracy`` on the CLI;
- an optional doctrine system-prompt section (off by default);
- the ``antibeaurocracy`` and ``antipedantry`` skills and a weekly audit blueprint (counts only).

It never writes a kanban row. Card actions stay with whoever owns the card. Its ledger stays at
``$HERMES_HOME/plugin-data/antibeaurocracy/ledger.jsonl`` so existing readers keep working.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import FAKE, __version__, classify
from . import audit as _audit
from . import cli as _cli
from . import settings as _settings
from .classify import WALLS_TEXT, wall_family
from .gates import GateState, NudgeBox, RefusalStore, atomic_write, decide

logger = logging.getLogger(__name__)
PLUGIN = "antibeaurocracy"
HERE = Path(__file__).resolve().parent.parent  # the Selenite plugin root
OWNER = "selenite"  # the Hermes plugin these settings and skills live under
LOCAL_SURFACES = frozenset({"cli", "local"})
MODES = ("observe", "nudge", "ask")
# "enforce" was the 0.2 name for the mode that pushed back on a block. It is now "ask".
_MODE_ALIASES = {"enforce": "ask"}
_GATED_TOOLS = frozenset({"kanban_block"})
# The kinds an agent can declare on kanban_block. A declared kind is trusted and ledgered, never argued with.
_DECLARABLE = frozenset({"dependency", "needs_input", "capability", "transient"})
# kanban_task_blocked fires for a block the pre_tool_call hook already ledgered; skip that echo. Each entry
# also keeps the kind the agent declared, because Hermes does not pass the kind to kanban_task_blocked.
_ECHO_WINDOW_S = 60.0
_recent_attempts: dict[str, tuple[float, str]] = {}

DOCTRINE = f"""## Waits between agents (antibeaurocracy plugin)
Before you block a card on another agent, check what the wait is for.
- Still stop for a wall: {WALLS_TEXT}. Also for a machinery fault or a real task dependency.
- Don't stop just to get another agent's OK, relay, ruling or ceremony for a step that is in your scope and can be undone. Do it and note how to undo it.
- If you're unsure which it is, treat it as a wall and ask once: one line, the options, your default."""

_state_lock = threading.Lock()
_nudges = NudgeBox()
_snapshot_at: dict[str, float] = {}
_snapshot_running: set[str] = set()
_tick_extra: list = []  # Selenite's badge reconcile, set by on_tick()
_ctx = None
LEDGER_ROTATE_BYTES = 4 * 1024 * 1024  # same bound as Selenite's own ledger
HOOKS_ON = lambda: True  # Selenite replaces this with its one off switch  # noqa: E731


# ---------------------------------------------------------------- config / storage

def _cfg(key: str, default):
    try:
        val = _ctx.get_config(key, default) if _ctx is not None else default
    except Exception:  # pragma: no cover - host without settings
        val = default
    return default if val is None else val


def _ctx_settings() -> dict:
    """The settings the classifier and audit read, as the plugin context reports them."""
    return {k: _cfg(k, None) for k in ("extra_seats", "extra_ceremony", "min_confidence", "fake_gate_mode")
            if _cfg(k, None) is not None}


def _mode() -> str:
    m = str(_cfg("fake_gate_mode", "nudge")).strip().lower()
    m = _MODE_ALIASES.get(m, m)
    return m if m in MODES else "nudge"


def _num(key: str, default: float) -> float:
    """A finite float setting; nan, inf, junk or a missing value give ``default``."""
    try:
        f = float(_cfg(key, default))
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


def _count(key: str, default: int, hi: int = 1000) -> int:
    """A whole-number setting clamped to 0..hi."""
    return max(0, min(hi, int(_num(key, default))))


def _whole(text: str, default: int, hi: int = 500) -> int:
    """A positive count typed after a slash command, clamped to 1..hi. "²" passes isdigit but not int()."""
    try:
        return max(1, min(hi, int(text))) if text.isdecimal() else default
    except ValueError:
        return default


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def data_dir(home: Path | None = None) -> Path:
    d = (home or _hermes_home()) / "plugin-data" / PLUGIN
    d.mkdir(parents=True, exist_ok=True)
    return d


def _refusal_store() -> RefusalStore:
    hours = _num("refusal_ttl_hours", 168)
    # 0 or negative would expire every count at once, so ask mode would never fail open: use the default.
    # A TTL under an hour would let counts expire between retries, so ask mode could ask forever.
    return RefusalStore(data_dir() / "refusals.json", ttl_s=(max(1.0, hours) if hours > 0 else 168) * 3600)


def _ledger(event: str, **fields) -> None:
    """Metadata only: event, tool, card id, verdict, confidence, mode, session id. Never reason text."""
    if not _cfg("fake_gate_ledger", True):
        return
    rec = {"ts": round(time.time(), 3), "event": event, **{k: v for k, v in fields.items() if v not in (None, "")}}
    try:
        path = data_dir() / "ledger.jsonl"  # mkdir can fail on a read-only home: inside the guard
        lock = os.open(path.with_name(".ledger.lock"), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            try:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)  # two writers never rotate the same file twice
            except (ImportError, OSError):
                pass
            # Selenite needs no cleansing: past LEDGER_ROTATE_BYTES the ledger becomes ledger.1.jsonl (one kept).
            if path.exists() and path.stat().st_size >= LEDGER_ROTATE_BYTES:
                os.replace(path, path.with_name("ledger.1.jsonl"))
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        finally:
            os.close(lock)
    except OSError as exc:  # never let bookkeeping break a turn
        logger.warning("antibeaurocracy ledger write failed: %s", exc)


# ---------------------------------------------------------------- kanban gate hooks

def _card_id(args: dict) -> str:
    return str(args.get("task_id") or os.environ.get("HERMES_KANBAN_TASK") or "")


def _board(args: dict) -> str:
    return str(args.get("board") or os.environ.get("HERMES_KANBAN_BOARD") or "default")


def _refusal_key(args: dict, session_id: str) -> str:
    """Per card, so a respawned worker on the same card keeps its count. Falls back to the session.

    Counted before Hermes validates the call, so a block that later fails validation still used one
    refusal. That only makes the next attempt fail open sooner."""
    board = _board(args)
    card = _card_id(args)
    return f"{board}:{card}" if card else f"session:{session_id}"


def _nudge_key(tool_name: str, args: dict, session_id: str, tool_call_id: str) -> str:
    return tool_call_id or f"{session_id}:{tool_name}:{_card_id(args)}"


def _explain(v) -> str:
    return (f"antibeaurocracy: this block reads as {v.label} ({v.reason}), a wait on another agent rather than a wall. "
            f"{v.action} If it touches a wall ({WALLS_TEXT}), it is one: stop and ask the person once.")


def _question(v) -> str:
    """Ask mode: the block is returned once with a question, not a verdict. Any declared kind is trusted.
    The kinds are Hermes's own (tools/kanban_tools_schemas.py)."""
    return (f"antibeaurocracy: before this card blocks, say what kind of wait it is. It reads like {v.label} "
            f"({v.reason}), a wait on another agent, but the check is a pattern match and you know the work.\n"
            f"- A person has to answer or decide (a wall: {WALLS_TEXT}): call kanban_block again with "
            "kind=needs_input and name the wall in the reason.\n"
            "- A hard wall no agent can get past (no access, missing credentials, an action no agent can do): "
            "kind=capability.\n"
            "- Another task has to land first: kind=dependency, with its task id in the reason.\n"
            "- A fault that should clear on its own (rate limit, outage, flaky tool): kind=transient.\n"
            f"- None of these: it is only another agent's OK, relay, ruling or ceremony. {v.action}\n"
            "Whatever kind you declare goes through and is recorded as you declared it.")


def on_pre_tool_call(tool_name: str = "", args: dict | None = None, session_id: str = "",
                     tool_call_id: str = "", **_kw):
    """Hermes vetoes the tool call if a pre_tool_call hook raises, so any error here fails open."""
    if tool_name not in _GATED_TOOLS or not HOOKS_ON():
        return None
    try:
        return _gate(tool_name, args if isinstance(args, dict) else {}, str(session_id or ""), str(tool_call_id or ""))
    except Exception as exc:
        logger.warning("antibeaurocracy gate failed open on %s: %s", tool_name, exc)
        return None


def _gate(tool_name: str, args: dict, session_id: str, tool_call_id: str):
    reason = str(args.get("reason") or "")
    kind = str(args.get("kind") or "").strip().lower()
    v = classify(reason, kind=kind or None)
    mode = _mode()
    over = v.cls == FAKE and v.evidenced and v.confidence >= _settings.min_confidence(_ctx_settings())
    card = _card_id(args)
    declared = kind if kind in _DECLARABLE else None
    _ledger("block_attempt", tool=tool_name, task=card, verdict=v.label, conf=v.confidence,
            mode=mode, session=session_id, declared=declared)
    max_ask = _count("max_refusals", 1)
    if declared:
        # The agent declared what the wait is. Trust it in every mode: no question and no nudge. Ledger it
        # next to the verdict so the audit can show where declarations and the classifier disagree.
        _ledger("declared", tool=tool_name, task=card, declared=kind, verdict=v.label, mode=mode, session=session_id)
        mode = "observe"
    elif mode == "ask" and wall_family(reason):
        # A wall-family word (money, infra, deletion, credentials, publishing, legal, freezes, a person's
        # role; agent and seat names are not counted) means no question at all, only the nudge.
        mode = "nudge"
    if mode == "ask" and over:
        state, n = _refusal_store().transition(_refusal_key(args, session_id), lambda p: decide(mode, over, p, max_ask))
    else:
        state, n = decide(mode, over, 0, max_ask)
    if state is GateState.ASK:
        _ledger("asked", tool=tool_name, task=card, verdict=v.label, attempt=n)
        return {"action": "block", "message": _question(v)}
    if card:  # the block goes through, so kanban_task_blocked will echo it; remember to skip that echo
        with _state_lock:
            now = time.time()
            for k in [k for k, (t, _) in _recent_attempts.items() if now - t > _ECHO_WINDOW_S]:
                del _recent_attempts[k]
            _recent_attempts[str(card)] = (now, declared or "")
    if state is GateState.FAIL_OPEN:
        _ledger("fail_open", tool=tool_name, task=card, verdict=v.label)
    elif state is GateState.NUDGE:
        _nudges.put(_nudge_key(tool_name, args, session_id, tool_call_id), _explain(v))
    return None


def _rejected(obj) -> bool:
    """Hermes's tool_error shape: {"error": ...}. A rejected block never reaches kanban_task_blocked."""
    return isinstance(obj, dict) and bool(obj.get("error"))


def on_transform_tool_result(tool_name: str = "", args: dict | None = None, result=None, session_id: str = "",
                             tool_call_id: str = "", **_kw):
    if tool_name not in _GATED_TOOLS:
        return None
    args = args if isinstance(args, dict) else {}
    note = _nudges.pop(_nudge_key(tool_name, args, session_id, tool_call_id))
    try:
        obj = json.loads(result) if isinstance(result, str) else None
    except ValueError:
        obj = None
    if _rejected(obj):  # no echo is coming, so a real block on this card a moment later must still be ledgered
        with _state_lock:
            _recent_attempts.pop(_card_id(args), None)
        return None
    if not note or not isinstance(result, str):
        return None
    if isinstance(obj, dict):
        obj["antibeaurocracy"] = note
        return json.dumps(obj)
    return result + "\n\n" + note


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _kanban_dbs(board: str | None) -> list[Path]:
    """Where Hermes keeps kanban.db, from its documented layout (no private imports): HERMES_KANBAN_DB
    pins one file; otherwise the root is HERMES_KANBAN_HOME or the Hermes home, the default board's DB
    is <root>/kanban.db and a named board's is <root>/kanban/boards/<slug>/kanban.db. The named board
    comes first, then every other board, since task ids are unique across boards."""
    pin = os.environ.get("HERMES_KANBAN_DB", "").strip()
    if pin:
        return [Path(pin).expanduser()]
    root = Path(os.environ.get("HERMES_KANBAN_HOME", "").strip() or _hermes_home()).expanduser()
    slug = str(board or os.environ.get("HERMES_KANBAN_BOARD") or "default").strip().lower()
    first = []
    if slug == "default":
        first = [root / "kanban.db"]
    elif _SLUG.match(slug):
        first = [root / "kanban" / "boards" / slug / "kanban.db"]
    rest = [db for db in _audit.find_boards([root]) if db not in first]
    return first + rest


def _stored_kind(task_id: str, board: str | None) -> str | None:
    """The block_kind Hermes stored on the card, read-only. Hermes does not pass it to the hook."""
    for db in _kanban_dbs(board)[:32]:
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
            try:
                row = con.execute("SELECT block_kind FROM tasks WHERE id = ?", (str(task_id),)).fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if row:
            return row[0] if row[0] in _DECLARABLE else None
    return None


def card_statuses(task_ids, board: str | None = None) -> dict[str, str]:
    """Current status of each card, read-only, across the boards this home can see."""
    return _audit.card_statuses(task_ids, _kanban_dbs(board)[:32])


def on_tick(fn) -> None:
    """Selenite's own housekeeping (badge reconcile) rides the one dispatch tick this facet registers."""
    _tick_extra[:] = [fn]


def observe_block(task_id: str = "", board: str | None = None, reason: str | None = None, kind: str | None = None):
    """Classify one block once and ledger its verdict, never the reason text. Returns ``(verdict, kind)``
    so Selenite's single ``kanban_task_blocked`` observer can route it. The kind is the one passed in,
    else the one the agent declared on its kanban_block call a moment ago, else the card's stored
    block_kind. A block the pre_tool_call hook saw in the last minute is classified but not ledgered
    twice. Raises nothing it can avoid; the caller still guards it."""
    key = str(task_id)  # task ids are unique across boards; the board name differs between surfaces
    with _state_lock:
        t, echoed_kind = _recent_attempts.pop(key, (0.0, ""))
    seen = time.time() - t <= _ECHO_WINDOW_S
    if kind not in _DECLARABLE:
        # Hermes may re-kind the block when it stores it (a dependency with no open parent is
        # parked as needs_input), so the stored kind wins over the kind the agent echoed.
        kind = (_stored_kind(key, board) if task_id else None) or (echoed_kind if seen and echoed_kind else None)
    v = classify(str(reason or ""), kind=kind)
    if not seen:
        _ledger("blocked_observed", task=task_id, board=board, verdict=v.label, conf=v.confidence, declared=kind)
    return v, kind


# ---------------------------------------------------------------- dispatcher snapshot

def _snapshot(home: Path) -> dict:
    res = _audit.run(roots=[home], rule_paths=[])
    out = {"ts": time.time(), "summary": _audit.counts_only(res["summary"])}
    atomic_write(data_dir(home) / "snapshot.json", json.dumps(out, indent=2, default=str))
    return out


def on_kanban_dispatch_tick(dry_run: bool = False, **_kw):
    if dry_run or not HOOKS_ON():
        return None
    for fn in _tick_extra:
        try:
            fn()
        except Exception as exc:  # never let housekeeping break the dispatcher
            logger.warning("selenite tick housekeeping failed: %s", exc)
    home = _hermes_home()  # resolved on the hook's thread, before handing off
    key = str(home)
    interval = max(1.0, _num("snapshot_minutes", 60)) * 60  # at least a minute, so 0 or junk never runs every tick
    with _state_lock:
        if key in _snapshot_running or time.time() - _snapshot_at.get(key, 0.0) < interval:
            return None
        _snapshot_at[key] = time.time()
        _snapshot_running.add(key)

    def _work():
        try:
            snap = _snapshot(home)
            if _ctx is not None:
                s = snap["summary"]
                _ctx.emit("snapshot", {"blocked": s["blocked"], "fake": s["fake"], "fake_share": s["fake_share"]})
        except Exception as exc:  # pragma: no cover
            logger.warning("antibeaurocracy snapshot failed: %s", exc)
        finally:
            with _state_lock:
                _snapshot_running.discard(key)

    threading.Thread(target=_work, name="antibeaurocracy-snapshot", daemon=True).start()
    return None


# ---------------------------------------------------------------- tools

CLASSIFY_SCHEMA = {
    "name": "bureaucracy_classify",
    "description": ("Before you block a card on another agent, classify the reason. Returns WALL (stop and ask the "
                    "person once), HUMAN (a question for a person; leave it to them), MACHINERY (fix or reroute), "
                    "DEPENDENCY (fine, auto-resumes) or FAKE with a subtype and how to check whether you can "
                    "proceed. It is a pattern heuristic: if in doubt, treat the wait as a wall."),
    "parameters": {"type": "object", "properties": {
        "text": {"type": "string", "description": "The block or wait reason."},
        "kind": {"type": "string", "enum": ["dependency", "needs_input", "capability", "transient"]},
        "age_hours": {"type": "number", "description": "How long it has been waiting, if known."},
    }, "required": ["text"]},
}

AUDIT_SCHEMA = {
    "name": "bureaucracy_audit",
    "description": ("Read-only counts for this Hermes home's kanban boards: blocked vs running, how the blocked cards "
                    "classify, and shared causes where one fix clears several cards. Returns counts only, no card "
                    "titles, reasons or assignees. Never changes a card."),
    "parameters": {"type": "object", "properties": {}},
}


def tool_classify(args: dict, **_kw) -> str:
    text = str(args.get("text") or "")
    return json.dumps(classify(text, kind=args.get("kind"), age_hours=args.get("age_hours")).to_dict())


def _boards(home: Path | None = None) -> list[dict]:
    return [_audit.audit_board(db) for db in _audit.find_boards([home or _hermes_home()])]


def tool_audit(args: dict | None = None, **_kw) -> str:
    return json.dumps(_audit.counts_only(_audit.summarize(_boards())))


# ---------------------------------------------------------------- slash + CLI

HELP = """/antibeaurocracy: find agent-to-agent fake gates
  /antibeaurocracy                 counts for this home's blocked cards
  /antibeaurocracy audit [N]       full audit, top N fake gates (local surfaces only)
  /antibeaurocracy check <text>    classify one block/wait reason
  /antibeaurocracy mode            show the gate mode (observe | nudge | ask)
  /antibeaurocracy ledger [N]      last N ledger events (local surfaces only)"""


def slash(raw_args: str = "", *, platform: str | None = None) -> str:
    argv = (raw_args or "").strip().split(maxsplit=1)
    sub = argv[0].lower() if argv else ""
    rest = argv[1] if len(argv) > 1 else ""
    local = str(platform or "").lower() in LOCAL_SURFACES
    if sub in ("help", "-h", "--help"):
        return HELP
    if sub in ("check", "classify"):
        if not rest:
            return "Usage: /antibeaurocracy check <reason text>"
        v = classify(rest)
        return f"{v.label} ({v.confidence}): {v.action}"
    if sub == "mode":
        return f"antibeaurocracy {__version__}: gate mode is {_mode()}. Change it in plugins.entries.{OWNER}.settings.fake_gate_mode."
    boards = _boards()
    s = _audit.summarize(boards)
    if not local:  # remote chat surfaces get counts, never card titles or reasons
        return _audit.headline(s) + " Run /antibeaurocracy audit locally or `hermes antibeaurocracy audit` for the list."
    if sub == "audit":
        top = _whole(rest, 12)
        return _audit.render_markdown(s, boards, [], top=top)
    if sub == "ledger":
        n = _whole(rest, 15)
        p = data_dir() / "ledger.jsonl"
        lines = p.read_text().splitlines()[-n:] if p.exists() else []
        return "\n".join(lines) or "Ledger is empty."
    return _audit.render_markdown(s, boards, [], top=5)


def slash_fake_gate(raw_args: str = "", *, platform: str | None = None) -> str:
    if not (raw_args or "").strip():
        return "Usage: /fake-gate <reason text>. Tells you whether a wait is a real wall or agent bureaucracy."
    return slash("check " + raw_args, platform=platform)


def _setup_cli(parser) -> None:
    _cli.add_arguments(parser)


def _cli_handler(args) -> int:
    if not getattr(args, "cmd", None):
        print(HELP)
        return 2
    return _cli.handle(args, settings=_ctx_settings())


# ---------------------------------------------------------------- register

def register(ctx) -> None:
    global _ctx
    _ctx = ctx
    _settings.apply(_ctx_settings())
    if str(_cfg("fake_gate_mode", "")).strip().lower() == "enforce":
        logger.warning("antibeaurocracy: mode 'enforce' is now called 'ask'; treating it as 'ask'.")
    if _mode() == "ask":
        logger.info("antibeaurocracy ask mode: a block that reads as agent bureaucracy is returned up to %s time(s) "
                    "per card with a question; any declared kind goes through.", _count("max_refusals", 1))

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("transform_tool_result", on_transform_tool_result)
    ctx.register_hook("on_kanban_dispatch_tick", on_kanban_dispatch_tick)

    ctx.register_tool(name="bureaucracy_classify", toolset=OWNER, schema=CLASSIFY_SCHEMA, handler=tool_classify, emoji="🧾")
    ctx.register_tool(name="bureaucracy_audit", toolset=OWNER, schema=AUDIT_SCHEMA, handler=tool_audit, emoji="🔎")

    ctx.register_command(PLUGIN, handler=slash, description="Find agent-to-agent fake gates on the kanban board",
                         args_hint="[audit|check <text>|mode|ledger]")
    ctx.register_command("fake-gate", handler=slash_fake_gate, description="Is this wait a real wall or agent bureaucracy?",
                         args_hint="<reason>")
    ctx.register_cli_command(name=PLUGIN, help="Audit and classify fake gates (read-only)",
                             setup_fn=_setup_cli, handler_fn=_cli_handler,
                             description="Find blocked work that waits on agent bureaucracy, not a real wall.")

    if _cfg("doctrine_section", False):
        try:
            ctx.register_system_prompt_section(f"{PLUGIN}.doctrine", DOCTRINE, max_chars=1500)
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("antibeaurocracy doctrine section not registered: %s", exc)

    # Skills are registered once, by Selenite's register, for all three facets.

    if hasattr(ctx, "register_automation_blueprint"):
        ctx.register_automation_blueprint(
            "weekly-audit", title="Weekly fake-gate counts",
            description="Every week: blocked vs running, how the blocked cards classify, and shared causes. Counts only.",
            schedule_template="{minute} {hour} * * 1",
            prompt_template=("Run the bureaucracy_audit tool. Reply with one line: blocked vs running and the "
                             "evidence-backed fake share. Then list each shared cause that blocks 2+ cards, with its "
                             "card count. Report counts only; do not name cards or people, and do not change any card."),
            category="ops",
            slots=[{"name": "time", "type": "time", "label": "What time on Monday?", "default": "09:00"},
                   {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "local",
                    "options": ("local", "origin"), "strict": True}],
            skills=(f"{OWNER}:{PLUGIN}",), tags=("kanban", "governance"),
        )
