"""Selenite backend routes, mounted by Hermes at /api/plugins/selenite/.

Read-mostly views over the local friction ledger and the latest cleanse
report, for the desktop page and the dashboard tab. The only writes are a
human logging a fix, a missed signal or a false positive, running a cleanse
pass (read-only over the stack; it writes only its own report), and drafting
an evolve proposal. The ledger stays on the host
that runs the agent; clients read it through the Hermes gateway, and these
routes make no other network calls.
"""
import importlib
import importlib.util
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "frictionless" / "scripts"


def _scripts(*names: str):
    """Load the skill's scripts as `selenite_frictionless.<name>`, so generic
    module names never land in sys.modules or sys.path."""
    pkg = "selenite_frictionless"
    if pkg not in sys.modules:
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(pkg, loader=None, is_package=True))
        mod.__path__ = [str(SCRIPTS)]
        sys.modules[pkg] = mod
    return [importlib.import_module(f"{pkg}.{n}") for n in names]


cleanse, evolve, ledger, signals = _scripts("cleanse", "evolve", "ledger", "signals")

router = APIRouter()


def _mount_fake_gates():
    """The fake-gate facet's read-only view lives at /fake-gates, under the same one plugin."""
    spec = importlib.util.spec_from_file_location("selenite_fake_gates_api", Path(__file__).resolve().parent / "fake_gates_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    router.include_router(mod.router, prefix="/fake-gates")
    return mod


_fake_gates = _mount_fake_gates()

GATE_KINDS = ("gate", "blocked")
DAY = 86400
PROPOSAL_CHARS = 20000
DRAFT_COOLDOWN = 10  # seconds: a repeat draft inside this returns the last one
# Any printable key the ledger writes ("<token>", "npm login", Unicode), up to 80; never one that
# starts like a flag or a path, or climbs a directory.
KEY_PATTERN = r"^[^\x00-\x1f\x7f\-./][^\x00-\x1f\x7f]{0,79}$"  # pydantic's regex has no lookahead: ".." is checked below
Days = Query(30, ge=1, le=365)

# --- one read of the ledger per change, shared by every route ----------------
_cache: dict = {"sig": None, "rows": []}
_lock = threading.Lock()


def _all_rows() -> list[dict]:
    """Every well-formed row from every state folder, re-read only when a ledger file changes."""
    sig = ledger.signature()
    if not sig:
        return []
    with _lock:
        if _cache["sig"] != sig:
            _cache["rows"] = list(ledger.rows())
            _cache["sig"] = sig
        return _cache["rows"]


def _window(days: int, now: float) -> list[dict]:
    since = now - days * DAY
    return [r for r in _all_rows() if r["ts"] >= since]


def _load(calm_24h: int, streak: bool) -> str:
    """Load over the last day: clear, rising or high."""
    if streak or calm_24h >= 3:
        return "high"
    return "rising" if calm_24h else "clear"


def _load_of(rows: list[dict], now: float) -> tuple[str, int, float]:
    calm = [r["ts"] for r in rows if r["kind"] == "calm"]
    calm_24h = sum(1 for ts in calm if ts >= now - DAY)
    last = max(calm, default=0.0)
    return _load(calm_24h, streak=bool(last and now - last < 900 and calm_24h >= 2)), calm_24h, last


def _state_dir() -> str:
    """The folder the next ledger row is written to (a fallback when the first is read-only), home as ~."""
    return str(ledger.write_target()).replace(str(Path.home()), "~", 1)


STATUS_TTL = 30  # seconds: a polling chip re-reads card statuses at most this often
_status_cache: dict = {"ts": 0.0, "ids": (), "statuses": {}}


def _card_statuses(ids: list[str]) -> dict[str, str]:
    """Each badged card's status on its board, read-only and cached. Unknown cards are left out."""
    key = tuple(ids)
    with _lock:
        if _status_cache["ids"] == key and time.time() - _status_cache["ts"] < STATUS_TTL:
            return _status_cache["statuses"]
    try:
        core = _fake_gates._core()
        plugin = importlib.import_module(f"{core.__name__}.plugin")
        statuses = core.audit.card_statuses(ids, plugin._kanban_dbs(None), mark_missing=True)
    except Exception:  # a missing or locked board never hides a badge, it just can't clear one
        statuses = {}
    with _lock:
        _status_cache.update(ts=time.time(), ids=key, statuses=statuses)
    return statuses


def _blocked(rows: list[dict], fixed: set[str]) -> list[str]:
    """Cards still waiting on a person: logged blocked, not fixed since, and not since unblocked,
    archived, finished or deleted on the board (Hermes fires no hook for an unblock or an archive)."""
    ids = sorted({r["key"].split(":", 1)[1] for r in rows
                  if r["kind"] == "blocked" and r["key"].startswith("kanban:") and r["key"] not in fixed})
    statuses = _card_statuses(ids) if ids else {}
    return [i for i in ids if statuses.get(i, "blocked") == "blocked"]


def _name_cards(gates: list[dict]) -> list[dict]:
    """Give each ``kanban:<id>`` gate its card title, and drop gates whose card no longer exists.
    A board that can't be read keeps the gate under its key: unknown is not deleted."""
    ids = [g["key"].split(":", 1)[1] for g in gates if g["key"].startswith("kanban:")]
    if not ids:
        return gates
    try:
        core = _fake_gates._core()
        plugin = importlib.import_module(f"{core.__name__}.plugin")
        dbs = plugin._kanban_dbs(None)
        statuses = core.audit.card_statuses(ids, dbs, mark_missing=True)
        titles = core.audit.card_titles(ids, dbs)
    except Exception:
        return gates
    out = []
    for g in gates:
        if g["key"].startswith("kanban:"):
            cid = g["key"].split(":", 1)[1]
            if statuses.get(cid) == core.audit.MISSING:
                continue
            g = {**g, "title": titles.get(cid) or ""}
        out.append(g)
    return out


@router.get("/status")
def status() -> dict:
    """The small, cheap view the status chip and Kanban badges poll."""
    now = time.time()
    rows = _window(30, now)
    fixed = ledger.fixed_keys(source=_all_rows())
    today = {r["key"] for r in rows if r["kind"] in GATE_KINDS and r["ts"] >= now - DAY}
    load, calm_24h, _ = _load_of(rows, now)
    # badges use the same window as the plugin's hooks, not the 30-day load window
    return {"load": load, "calm_24h": calm_24h, "open_today": len(today - fixed),
            "blocked_tasks": _blocked(_window(ledger.BLOCKED_DAYS, now), fixed), "state_dir": _state_dir()}


@router.get("/overview")
def overview(days: int = Days) -> dict:
    now = time.time()
    rows = _window(days, now)
    kinds = Counter(r["kind"] for r in rows)

    gates: dict[str, dict] = {}
    approvals: Counter = Counter()
    calm_reasons: Counter = Counter()
    daily: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        k, key, ts = r["kind"], r["key"], r["ts"]
        daily[time.strftime("%Y-%m-%d", time.localtime(ts))][k] += 1
        if k in GATE_KINDS:
            g = gates.setdefault(key, {"key": key, "n": 0, "last": 0, "first": ts, "note": ""})
            g["n"] += 1
            if ts >= g["last"]:
                g["last"], g["note"] = ts, r.get("note", "")
        elif k == "approval":
            approvals[key] += 1
        elif k == "calm":
            calm_reasons.update(key.split("+"))

    ranked = sorted(gates.values(), key=lambda g: (-g["n"], -g["last"]))
    fixed = ledger.fixed_keys(source=_all_rows())
    for g in ranked:
        g["fixed"] = g["key"] in fixed
    ranked = _name_cards(ranked)
    recurring = [g for g in ranked if g["n"] >= 2]
    series = []
    for i in range(days - 1, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(now - i * DAY))
        c = daily.get(d, Counter())
        series.append({"day": d, "gate": c["gate"] + c["blocked"], "calm": c["calm"], "approval": c["approval"]})
    load, calm_24h, last_calm = _load_of(rows, now)

    return {
        "window_days": days,
        "totals": {"gates": kinds["gate"] + kinds["blocked"], "approvals": kinds["approval"],
                   "calm": kinds["calm"], "fixes": kinds["fix"], "events": len(rows)},
        "load": load,
        "calm_24h": calm_24h,
        "last_calm": last_calm or None,
        "gates": recurring[:25],
        "one_off_gates": len(ranked) - len(recurring),
        "approvals": [{"key": k, "n": n} for k, n in approvals.most_common(10)],
        "signals": {c: calm_reasons.get(c, 0) for c in sorted(signals.OVERLOAD | {"typo_burst"})},
        "categories": sorted(signals.CATEGORIES),
        "series": series,
        "blocked_tasks": _blocked(rows, fixed),
        "has_ledger": bool(ledger.signature()),
        "state_dir": _state_dir(),
    }


@router.get("/events")
def events(limit: int = Query(60, ge=1, le=500), days: int = Days) -> dict:
    rows = _window(days, time.time())[-limit:]
    rows.reverse()
    return {"events": [{k: r.get(k) for k in ("ts", "kind", "key", "note", "agent")} for r in rows]}


class Mark(BaseModel):
    kind: Literal["fix", "reopen", "fp", "miss"]  # what a human may log from the UI
    key: str = Field(min_length=1, max_length=80, pattern=KEY_PATTERN)
    note: str = Field(default="", max_length=200)

    @field_validator("key")
    @classmethod
    def _no_climb(cls, v: str) -> str:
        if ".." in v:
            raise ValueError("key must not contain '..'")
        return v


@router.post("/events")
def mark(body: Mark) -> dict:
    row = ledger.add(body.kind, body.key, body.note, agent="desktop")
    if row is None:   # every state folder refused it (read-only, full or locked): say so, like the tool does
        raise HTTPException(status_code=503, detail="ledger not writable: the row was not recorded")
    return {"row": row}


def _proposal_view(f: Path) -> dict:
    return {"name": f.name, "mtime": f.stat().st_mtime, "text": f.read_text(errors="ignore")[:PROPOSAL_CHARS]}


def _latest_proposal() -> Path | None:
    files = ledger.newest("proposal-*.md")  # every state folder: a fallback draft still shows
    return files[0] if files else None


@router.get("/proposal")
def proposal() -> dict:
    f = _latest_proposal()
    return {"proposal": _proposal_view(f) if f else None}


@router.post("/proposal")
def draft(days: int = Days) -> dict:
    last = _latest_proposal()
    if last and time.time() - last.stat().st_mtime < DRAFT_COOLDOWN:
        return {"proposal": _proposal_view(last), "reused": True}
    out = evolve.build(days)
    if out is None:  # every state folder is read-only: say so instead of a 500
        return {"proposal": None, "reused": False, "error": "No state folder is writable. Set SELENITE_STATE."}
    return {"proposal": _proposal_view(out), "reused": False}


CLEANSE_COOLDOWN = 60  # seconds: a repeat run inside this returns the last report


def _cleanse_view(report: dict | None) -> dict | None:
    if not report:
        return None
    return {"generated": report.get("generated"), "total": len(report.get("findings", [])),
            "by_stone": report.get("by_stone", {}), "findings": report.get("findings", [])[:25],
            "errors": report.get("errors", [])}


@router.get("/cleanse")
def cleanse_latest() -> dict:
    """Clarity: the latest ranked view of what to clear across the stack."""
    return {"cleanse": _cleanse_view(cleanse.latest())}


@router.post("/cleanse")
def cleanse_run(days: int = Days) -> dict:
    files = ledger.newest("cleanse-*.json")
    if files and time.time() - files[0].stat().st_mtime < CLEANSE_COOLDOWN:
        return {"cleanse": _cleanse_view(cleanse.latest()), "reused": True}
    report = cleanse.run(days)
    cleanse.write(report)
    return {"cleanse": _cleanse_view(report), "reused": False}
