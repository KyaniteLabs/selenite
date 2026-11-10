#!/usr/bin/env python3
"""Selenite evolve: turn the ledger and miner reports into a reviewable proposal.

Writes $SELENITE_STATE/proposal-<stamp>.md and prints its path. It never
edits the skill. A human or agent turns the proposal into a PR.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
from signals import CATEGORIES  # noqa: E402


def latest_reports(n: int = 10) -> list[dict]:
    files = sorted(ledger.STATE.glob("report-*.json"), key=lambda p: p.stat().st_mtime)[-n:]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()

    rows = list(ledger.rows(a.days))
    reports = latest_reports()
    gates = Counter(r["key"] for r in rows if r["kind"] in ("gate", "blocked"))
    approvals = Counter(r["key"] for r in rows if r["kind"] == "approval")
    misses = [r for r in rows if r["kind"] == "miss"]
    fps = [r for r in rows if r["kind"] == "fp"]
    fixed = {r["key"] for r in rows if r["kind"] == "fix"}
    fired = Counter()
    for rep in reports:
        fired.update(rep.get("counts", {}))
    fired.update(c for r in rows if r["kind"] == "calm" for c in r["key"].split("+"))
    silent = [c for c in CATEGORIES if fired[c] == 0]

    L = [f"# Selenite evolve proposal ({time.strftime('%Y-%m-%d')})", "",
         f"Window: {a.days} days, {len(rows)} ledger rows, {len(reports)} miner reports.", ""]
    L += ["## Recurring human gates (eliminate or one-shot these)", ""]
    L += [f"- `{k}` ×{n}" + (" (a fix is logged; check it held)" if k in fixed else "")
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

    ledger.STATE.mkdir(parents=True, exist_ok=True)
    out = ledger.STATE / f"proposal-{time.strftime('%Y%m%dT%H%M%S')}.md"
    out.write_text("\n".join(L))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
