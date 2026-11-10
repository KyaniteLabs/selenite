#!/usr/bin/env python3
"""Selenite friction ledger: one JSON line per friction event.

  ledger.py add <kind> <key> [--note TEXT] [--agent NAME]
  ledger.py summary [--days N]

kind: gate | calm | audit | cleanse | approval | blocked | miss | fp | fix | reopen
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
ROTATED = STATE / "ledger.1.jsonl"
ROTATE_BYTES = 4 * 1024 * 1024  # one rotated file is kept; older history is dropped
KINDS = {"gate", "calm", "audit", "cleanse", "approval", "blocked", "miss", "fp", "fix", "reopen"}


def _rotate() -> None:
    try:
        if LEDGER.stat().st_size >= ROTATE_BYTES:
            os.replace(LEDGER, ROTATED)
    except FileNotFoundError:
        pass


def add(kind: str, key: str, note: str = "", agent: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    _rotate()
    row = {"ts": time.time(), "kind": kind, "key": key[:80], "note": note[:200],
           "agent": agent or os.environ.get("SELENITE_AGENT", "")}
    fd = os.open(LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def rows(days: int = 3650):
    """Yield well-formed rows newer than `days`. Malformed lines are skipped."""
    since = time.time() - days * 86400
    for path in (ROTATED, LEDGER):
        yield from _read(path, since)


def _read(path: Path, since: float):
    if not path.exists():
        return
    with path.open(errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not (isinstance(r, dict) and isinstance(r.get("kind"), str) and isinstance(r.get("key"), str)):
                continue
            ts = r.get("ts")
            if not isinstance(ts, (int, float)) or isinstance(ts, bool):
                continue
            if ts >= since:
                yield r


def fixed_keys(gate_last: dict[str, float] | None = None, source=None) -> set[str]:
    """Keys whose latest fix/reopen is a fix, and which no gate has hit since.

    Reads all history, not a window: a fix logged 40 days ago still counts in a
    7-day view, and a gate after the fix means the friction came back.
    `source` is an optional iterable of already-read rows (all history).
    """
    latest: dict[str, tuple[float, str]] = {}
    last_gate: dict[str, float] = dict(gate_last or {})
    for r in (rows() if source is None else source):
        k, key, ts = r["kind"], r["key"], r["ts"]
        if k in ("fix", "reopen"):
            if ts >= latest.get(key, (-1.0, ""))[0]:
                latest[key] = (ts, k)
        elif k in ("gate", "blocked"):
            last_gate[key] = max(last_gate.get(key, 0.0), ts)
    return {key for key, (ts, k) in latest.items() if k == "fix" and ts >= last_gate.get(key, 0.0)}


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
