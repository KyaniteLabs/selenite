#!/usr/bin/env python3
"""Selenite friction ledger: one JSON line per friction event.

  ledger.py add <kind> <key> [--note TEXT] [--agent NAME]
  ledger.py summary [--days N]

kind: gate | calm | audit | approval | blocked | miss | fp | fix
key:  a short stable slug for the friction (e.g. gh-login, npm-otp).
Notes must not contain secrets; they are truncated to 200 characters.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

STATE = Path(os.environ.get("SELENITE_STATE", Path.home() / ".local/state/selenite"))
LEDGER = STATE / "ledger.jsonl"
KINDS = {"gate", "calm", "audit", "approval", "blocked", "miss", "fp", "fix"}


def add(kind: str, key: str, note: str = "", agent: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    STATE.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "kind": kind, "key": key[:80], "note": note[:200],
           "agent": agent or os.environ.get("SELENITE_AGENT", ""), "host": os.uname().nodename}
    new = not LEDGER.exists()
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    if new:
        os.chmod(LEDGER, 0o600)
    return row


def rows(days: int = 3650):
    since = time.time() - days * 86400
    if not LEDGER.exists():
        return
    for line in LEDGER.open(errors="ignore"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("ts", 0) >= since:
            yield r


def summary(days: int) -> dict:
    by = Counter((r["kind"], r["key"]) for r in rows(days))
    return {"window_days": days, "top": [{"kind": k, "key": key, "n": n} for (k, key), n in by.most_common(25)]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("kind"); a.add_argument("key")
    a.add_argument("--note", default=""); a.add_argument("--agent", default="")
    s = sub.add_parser("summary"); s.add_argument("--days", type=int, default=30)
    ns = ap.parse_args()
    if ns.cmd == "add":
        print(json.dumps(add(ns.kind, ns.key, ns.note, ns.agent)))
    else:
        print(json.dumps(summary(ns.days), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
