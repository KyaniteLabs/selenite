"""Selenite's fake-gate view, mounted by plugin_api.py at /api/plugins/selenite/fake-gates/.

One read-only view for the dashboard tab: the board audit (SQLite opened
mode=ro) plus counts from the facet's own ledger. No writes, no network.
The audit is cached for AUDIT_TTL seconds so a polling tab can't rescan every board.
"""
import importlib.util
import json
import logging
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Query

ROOT = Path(__file__).resolve().parent.parent
AUDIT_TTL = 30  # seconds
logger = logging.getLogger(__name__)
_audit_cache: dict = {"ts": 0.0, "home": None, "boards": None}
_audit_lock = threading.Lock()


def _core():
    """Load the bundled core under a private module name so it never shadows anything."""
    name = "antibeaurocracy_dashboard_core"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "antibeaurocracy_core" / "__init__.py",
                                                      submodule_search_locations=[str(ROOT / "antibeaurocracy_core")])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        importlib.import_module(f"{name}.audit")  # submodules aren't attributes until imported
        importlib.import_module(f"{name}.settings")
    return sys.modules[name]


def _settings() -> dict:
    """Selenite's settings from $HERMES_HOME/config.yaml, applied to the classifier and audit so the
    tab counts what the plugin counts (extra_seats, extra_ceremony, min_confidence). A read failure
    shows the defaults and is logged, not hidden."""
    core = _core()
    settings, err = core.settings.read(_home())
    if err:
        logger.warning("selenite settings unreadable, showing defaults: %s", err)
    core.settings.apply(settings)
    return settings


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return Path(get_hermes_home())
    except Exception:
        import os
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _ledger_counts(days: int) -> dict:
    d = _home() / "plugin-data" / "antibeaurocracy"
    since = time.time() - days * 86400
    c: Counter = Counter()
    for path in (d / "ledger.1.jsonl", d / "ledger.jsonl"):  # the rotated file, then the live one
        _count_file(path, since, c)
    return dict(c)


def _count_file(path: Path, since: float, c: Counter) -> None:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ts = rec.get("ts", 0)
                if isinstance(ts, (int, float)) and ts >= since:
                    c[str(rec.get("event", "?"))[:40]] += 1
    except FileNotFoundError:
        pass  # no ledger yet is an empty count, not a fault
    except OSError as exc:
        logger.warning("selenite fake-gate ledger unreadable: %s", exc)


router = APIRouter()


def _boards(settings: dict) -> list:
    home = _home()
    with _audit_lock:
        core = _core()
        plugin = importlib.import_module(f"{core.__name__}.plugin")
        candidates = [Path(db) for db in plugin._kanban_dbs(None)]
        locations = tuple((str(db.resolve()), db.is_file()) for db in candidates)
        dbs = [db for db in candidates if db.is_file()]
        key = (str(home), locations, repr(sorted(settings.items())))
        if _audit_cache["home"] != key or _audit_cache["boards"] is None or time.time() - _audit_cache["ts"] > AUDIT_TTL:
            audit = core.audit
            _audit_cache.update(ts=time.time(), home=key, boards=[audit.audit_board(db) for db in dbs])
        return _audit_cache["boards"]


@router.get("/overview")
def overview(top: int = Query(15, ge=1, le=100), days: int = Query(7, ge=1, le=90)):
    settings = _settings()
    audit = _core().audit
    boards = _boards(settings)
    summary = audit.summarize(boards)
    fakes = sorted((c for b in boards for c in b.get("blocked", []) if audit.is_fake(c)),
                   key=lambda c: (-(c.get("age_h") or 0), -c["verdict"]["confidence"]))
    # Card titles are the tab's point; assignees, per-seat counts, card-id lists and file paths are
    # not shown and so not sent.
    cards = [{"id": c["id"], "title": (c.get("title") or "")[:140],
              "age_h": c.get("age_h"), "label": c["verdict"]["label"], "action": c["verdict"]["action"]}
             for c in fakes[:top]]
    out = audit.counts_only(summary)
    out["headline"] = audit.headline(summary)
    return {"summary": out, "cards": cards, "ledger": _ledger_counts(days), "days": days,
            "mode": _core().settings.mode(settings)}
