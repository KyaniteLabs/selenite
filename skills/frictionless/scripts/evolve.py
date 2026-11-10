#!/usr/bin/env python3
"""Selenite evolve: sharpen Selenite. Optional; ignoring it degrades nothing.

Reads the ledger, the newest miner report and the newest cleanse report, and
writes $SELENITE_STATE/proposal-<stamp>.md. It keeps one small state file,
evolve-state.json, that counts how many evolve cycles in a row each signal
category stayed silent; a category silent for PRUNE_AFTER cycles is proposed
for the compost. It never edits the skill. A human or agent turns the
proposal into a PR.
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
    from .signals import CATEGORIES
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cleanse  # noqa: E402
    import ledger  # noqa: E402
    from signals import CATEGORIES  # noqa: E402

KEEP = 10  # proposals kept on disk; older drafts are deleted
PRUNE_AFTER = 2  # silent evolve cycles before a category is proposed for the compost
CYCLE_GAP = 86400  # drafts closer together than this count as the same cycle


def latest_report() -> dict | None:
    """The newest miner report only. Reports overlap in time, so summing them double-counts."""
    for f in sorted(ledger.STATE.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return None


def _state_path() -> Path:
    return ledger.STATE / "evolve-state.json"


def advance_cycle(fired: Counter, now: float) -> dict[str, int]:
    """Update and return how many cycles in a row each category stayed silent."""
    try:
        st = json.loads(_state_path().read_text())
        assert isinstance(st, dict) and isinstance(st.get("silent"), dict)
    except (OSError, ValueError, AssertionError):
        st = {"last": 0, "silent": {}}
    silent = {c: int(st["silent"].get(c, 0)) for c in CATEGORIES}
    if now - float(st.get("last", 0)) >= CYCLE_GAP:  # a new cycle, not a re-draft
        silent = {c: 0 if fired[c] else silent[c] + 1 for c in CATEGORIES}
        st = {"last": now, "silent": silent}
        fd = os.open(_state_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(st, fh)
    return silent


def build(days: int = 30) -> Path:
    """Write one proposal file and return its path."""
    ledger.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    rows = list(ledger.rows(days))
    report = latest_report()
    swept = cleanse.latest()
    gates = Counter(r["key"] for r in rows if r["kind"] in ("gate", "blocked"))
    approvals = Counter(r["key"] for r in rows if r["kind"] == "approval")
    misses = [r for r in rows if r["kind"] == "miss"]
    fps = [r for r in rows if r["kind"] == "fp"]
    held = ledger.fixed_keys()
    tried = {r["key"] for r in ledger.rows() if r["kind"] == "fix"}
    fired = Counter((report or {}).get("counts", {}))
    fired.update(c for r in rows if r["kind"] == "calm" for c in r["key"].split("+"))
    silent = advance_cycle(fired, time.time())

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
    L += [f"- Missed overload (add a pattern): {r['note'] or r['key']}" for r in misses[:10]]
    L += [f"- False positive (narrow a pattern): {r['note'] or r['key']}" for r in fps[:10]]
    L += [f"- Category `{c}` silent for {n} cycle(s): " + ("move it to references/compost.md" if n >= PRUNE_AFTER
          else f"prune if still silent after {PRUNE_AFTER}") for c, n in sorted(silent.items()) if n]
    if not (misses or fps or any(silent.values())):
        L.append("- no changes suggested")
    L += ["", "## Miner counts (newest report)", ""]
    L += [f"- {k}: {n}" for k, n in fired.most_common()] or ["- no report; run mine.py"]
    L += ["", "Next: turn the accepted items into one PR. Fix the top item with code first, prose last.", ""]

    out = ledger.STATE / f"proposal-{time.strftime('%Y%m%dT%H%M%S')}.md"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(L))
    for old in sorted(ledger.STATE.glob("proposal-*.md"), key=lambda f: f.stat().st_mtime)[:-KEEP]:
        old.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    print(build(ap.parse_args().days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
