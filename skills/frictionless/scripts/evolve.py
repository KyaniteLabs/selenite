#!/usr/bin/env python3
"""Selenite evolve: turn the ledger and miner reports into a reviewable proposal.

Writes $SELENITE_STATE/proposal-<stamp>.md and prints its path. It never
edits the skill. A human or agent turns the proposal into a PR.
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
    from . import ledger
    from .signals import CATEGORIES
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # noqa: E402
    from signals import CATEGORIES  # noqa: E402

KEEP = 10  # proposals kept on disk; older drafts are deleted


def latest_reports(n: int = 10) -> list[dict]:
    files = sorted(ledger.STATE.glob("report-*.json"), key=lambda p: p.stat().st_mtime)[-n:]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            pass
    return out


def build(days: int = 30) -> Path:
    """Write one proposal file and return its path."""
    rows = list(ledger.rows(days))
    reports = latest_reports()
    gates = Counter(r["key"] for r in rows if r["kind"] in ("gate", "blocked"))
    approvals = Counter(r["key"] for r in rows if r["kind"] == "approval")
    misses = [r for r in rows if r["kind"] == "miss"]
    fps = [r for r in rows if r["kind"] == "fp"]
    held = ledger.fixed_keys()
    tried = {r["key"] for r in ledger.rows() if r["kind"] == "fix"}
    fired = Counter()
    for rep in reports:
        fired.update(rep.get("counts", {}))
    fired.update(c for r in rows if r["kind"] == "calm" for c in r["key"].split("+"))
    silent = [c for c in CATEGORIES if fired[c] == 0]

    L = [f"# Selenite evolve proposal ({time.strftime('%Y-%m-%d')})", "",
         f"Window: {days} days, {len(rows)} ledger rows, {len(reports)} miner reports.", ""]
    L += ["## Recurring human gates (eliminate or one-shot these)", ""]
    L += [f"- `{k}` ×{n}" + (" (fixed; no gate since)" if k in held
                             else " (a fix was logged, but the gate came back)" if k in tried else "")
          for k, n in gates.most_common(10)] or ["- none logged"]
    L += ["", "## Repeating approval prompts (allowlist or hook candidates)", ""]
    L += [f"- `{k}` ×{n}" for k, n in approvals.most_common(10)] or ["- none logged"]
    L += ["", "## Signal quality", ""]
    L += [f"- Missed overload (add a pattern): {r['note'] or r['key']}" for r in misses[:10]]
    L += [f"- False positive (narrow a pattern): {r['note'] or r['key']}" for r in fps[:10]]
    L += [f"- Category `{c}` never fired: prune after a second silent cycle" for c in silent]
    if not (misses or fps or silent):
        L.append("- no changes suggested")
    L += ["", "## Miner totals", ""]
    L += [f"- {k}: {n}" for k, n in fired.most_common()] or ["- no reports; run mine.py"]
    L += ["", "Next: turn the accepted items into one PR. Fix the top gate with code first, prose last.", ""]

    ledger.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
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
