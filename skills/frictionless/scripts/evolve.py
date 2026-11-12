#!/usr/bin/env python3
"""Selenite evolve: sharpen Selenite. Optional; ignoring it degrades nothing.

Reads the ledger, the newest miner report and the newest cleanse report, and
writes $SELENITE_STATE/proposal-<stamp>.md. It keeps one small state file,
evolve-state.json, that counts how many evolve cycles in a row each signal
category stayed silent; a category silent for PRUNE_AFTER cycles is proposed
for the compost. Silence only counts when it was measured: every category
when a new miner report arrived since the last cycle, and the Calm
categories when the ledger holds Calm rows. It never edits the skill. An
agent may draft the accepted changes on a local branch; opening a PR is the
human's decision.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

if __package__:  # loaded as selenite_frictionless.evolve by a Hermes host
    from . import cleanse, ledger
    from .signals import CATEGORIES, OVERLOAD
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cleanse  # noqa: E402
    import ledger  # noqa: E402
    from signals import CATEGORIES, OVERLOAD  # noqa: E402

KEEP = 10  # proposals kept on disk; older drafts are deleted
PRUNE_AFTER = 2  # silent evolve cycles before a category is proposed for the compost
CYCLE_GAP = 86400  # drafts closer together than this count as the same cycle


def _newest_report() -> tuple[dict | None, float]:
    """The newest readable miner report and its mtime. Reports overlap in time, so summing them double-counts."""
    for f in ledger.newest("report-*.json"):
        try:
            rep = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(rep, dict):
            return rep, f.stat().st_mtime
    return None, 0.0


def latest_report() -> dict | None:
    return _newest_report()[0]


def _state_path() -> Path:
    """The cycle state: the newest copy in any state folder, else where the next write lands."""
    found = ledger.newest("evolve-state.json")
    return found[0] if found else (ledger.writable_state() or ledger.STATE) / "evolve-state.json"


def _load_state() -> tuple[float, float, dict[str, int]]:
    """(last cycle, last report consumed, silence per category). Any damage resets it."""
    try:
        st = json.loads(_state_path().read_text())
        return (float(st.get("last", 0)), float(st.get("report", 0)),
                {c: max(0, int(st["silent"].get(c, 0))) for c in CATEGORIES})
    except Exception:  # missing, unreadable, not JSON, wrong shape, bad numbers: start over
        return 0.0, 0.0, {c: 0 for c in CATEGORIES}


def advance_cycle(fired: Counter, now: float, report_mtime: float = 0.0, calm: bool = False) -> dict[str, int]:
    """Update and return how many cycles in a row each category stayed silent.

    Only measured categories move: all of them when a miner report arrived
    since the last cycle, the Calm ones when the ledger holds Calm rows. A
    category nobody looked at keeps its count instead of drifting toward the
    compost."""
    last, consumed, silent = _load_state()
    if now - last >= CYCLE_GAP:  # a new cycle, not a re-draft
        measured = (set(CATEGORIES) if report_mtime and report_mtime != consumed else set()) \
            | (set(OVERLOAD) if calm else set())
        silent = {c: (0 if fired[c] else silent[c] + 1) if c in measured else silent[c] for c in CATEGORIES}
        st = {"last": now, "report": report_mtime or consumed, "silent": silent}
        target = ledger.writable_state()
        if target is not None:  # every folder read-only: the proposal still drafts, the cycle just isn't saved
            fd = os.open(target / "evolve-state.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(st, fh)
    return silent


def build(days: int = 30) -> Path | None:
    """Write one proposal file to the first state folder that takes it and return its path, or None
    when every state folder is read-only."""
    state = ledger.writable_state()
    if state is None:
        return None
    rows = list(ledger.rows(days))
    report, report_mtime = _newest_report()
    swept = cleanse.latest()
    gates = Counter(r["key"] for r in rows if r["kind"] in ("gate", "blocked"))
    approvals = Counter(r["key"] for r in rows if r["kind"] == "approval")
    misses = [r for r in rows if r["kind"] == "miss"]
    fps = [r for r in rows if r["kind"] == "fp"]
    held = ledger.fixed_keys()
    tried = {r["key"] for r in ledger.rows() if r["kind"] == "fix"}
    counts = (report or {}).get("counts", {})
    fired = Counter({k: n for k, n in counts.items() if isinstance(n, int)} if isinstance(counts, dict) else {})
    calm = [r for r in rows if r["kind"] == "calm"]
    fired.update(c for r in calm for c in r["key"].split("+"))
    silent = advance_cycle(fired, time.time(), report_mtime, bool(calm))

    L = [f"# Selenite evolve proposal ({time.strftime('%Y-%m-%d')})", "",
         f"Window: {days} days, {len(rows)} ledger rows, "
         f"{'one miner report' if report else 'no miner report'}, "
         f"{'one cleanse report' if swept else 'no cleanse report'}.", ""]
    L += ["## Clear next (from the latest cleanse)", ""]
    L += [f"- [{f['stone']}] {f['problem']} ({f['where']}). Fix: {f['fix']}"
          for f in (swept or {}).get("findings", [])[:10]] or ["- no cleanse report; run cleanse.py"]
    L += ["", "## Recurring human gates (eliminate or one-shot these)", ""]
    L += [f"- `{k}` ×{n}" + (" (fixed; no gate since)" if k in held
                             else " (a fix was logged, but the gate came back)" if k in tried else "")
          for k, n in gates.most_common(10)] or ["- none logged"]
    L += ["", "## Repeating approval prompts (allowlist or hook candidates)", ""]
    L += [f"- `{k}` ×{n}" for k, n in approvals.most_common(10)] or ["- none logged"]
    L += ["", "## Sharpen Selenite (signal quality)", ""]
    L += [f"- Missed overload (add a pattern): {ledger.redact(r['note'] or r['key'])}" for r in misses[:10]]
    L += [f"- False positive (narrow a pattern): {ledger.redact(r['note'] or r['key'])}" for r in fps[:10]]
    L += [f"- Category `{c}` silent for {n} cycle{'' if n == 1 else 's'}: " + ("move it to references/compost.md" if n >= PRUNE_AFTER
          else f"prune if still silent after {PRUNE_AFTER}") for c, n in sorted(silent.items()) if n]
    if not (misses or fps or any(silent.values())):
        L.append("- no changes suggested")
    L += ["", "## Miner counts (newest report)", ""]
    L += [f"- {k}: {n}" for k, n in fired.most_common()] or ["- no report; run mine.py"]
    L += ["", "Next: draft the accepted items on a local branch, code first and prose last. "
          "Opening a PR is the human's decision.", ""]

    out = state / f"proposal-{time.strftime('%Y%m%dT%H%M%S')}.md"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(L))
    for old in sorted(state.glob("proposal-*.md"), key=lambda f: f.stat().st_mtime)[:-KEEP]:
        old.unlink(missing_ok=True)
    ledger.pane.broadcast("proposal.updated", {})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    out = build(ap.parse_args().days)
    if out is None:
        print("no state folder is writable; set SELENITE_STATE", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
