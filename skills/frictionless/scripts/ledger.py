#!/usr/bin/env python3
"""Selenite friction ledger: one JSON line per friction event.

  ledger.py add <kind> <key> [--note TEXT] [--agent NAME]
  ledger.py summary [--days N]
  ledger.py state-dir          print the first state folder that accepts a write

kind: gate | calm | audit | cleanse | approval | blocked | miss | fp | fix | reopen
key:  a short stable slug for the friction (e.g. gh-login, npm-otp).
Keys and notes are redacted when written (emails, IPs, tokens, secrets, the
home path) and truncated: keys to 80 characters, notes to 200.

Where state lives: $SELENITE_STATE wins; then $XDG_STATE_HOME/selenite, then
$HERMES_HOME/plugin-data/selenite, then ~/.local/state/selenite. An agent seat
normally has a read-only home and a writable Hermes home, so the third choice is
what keeps it working there. Every write tries each folder in that order and
gives up quietly instead of failing the caller.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path


def _state_from_env() -> Path:
    """The folder Selenite prefers: explicit, then XDG, then the Hermes home, then ~/.local/state."""
    explicit = os.environ.get("SELENITE_STATE")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "selenite"
    hermes = os.environ.get("HERMES_HOME")
    if hermes:
        return Path(hermes).expanduser() / "plugin-data/selenite"
    return Path.home() / ".local/state/selenite"


def state_dirs() -> list[Path]:
    """Every folder Selenite may keep state in, most preferred first.

    The list exists because an agent seat is the product's normal home and its
    home folder is read-only: the preference falls through to a folder that
    takes the write instead of a traceback.
    """
    out = [STATE]
    xdg = os.environ.get("XDG_STATE_HOME")
    hermes = os.environ.get("HERMES_HOME")
    for extra in (Path(xdg).expanduser() / "selenite" if xdg else None,
                  Path(hermes).expanduser() / "plugin-data/selenite" if hermes else None,
                  Path.home() / ".local/state/selenite"):
        if extra is not None and extra not in out:
            out.append(extra)
    return out


def writable_state() -> Path | None:
    """The first state folder that accepts a write, or None when all are read-only."""
    for state in state_dirs():
        try:
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(state, os.W_OK):
            return state
    return None


def newest(pattern: str) -> list[Path]:
    """Files matching ``pattern`` in every state folder, newest first. A write that fell through to a
    fallback folder is still found by every reader."""
    found: list[tuple[float, Path]] = []
    for state in state_dirs():
        try:
            for f in state.glob(pattern):
                try:
                    found.append((f.stat().st_mtime, f))
                except OSError:
                    continue
        except OSError:
            continue
    return [f for _, f in sorted(found, key=lambda t: t[0], reverse=True)]


STATE = _state_from_env()
BLOCKED_DAYS = 90  # how long a blocked-card row keeps its badge: one window for hooks and dashboard
LEDGER = STATE / "ledger.jsonl"
ROTATED = STATE / "ledger.1.jsonl"
ROTATE_BYTES = 4 * 1024 * 1024  # one rotated file is kept; older history is dropped
KINDS = {"gate", "calm", "audit", "cleanse", "approval", "blocked", "miss", "fp", "fix", "reopen"}
APPROVAL_KEY = 71  # approval keys are cut here, so "approval:" + key fits the 80-character key limit

# Redaction runs on every key and note the ledger writes, and on miner samples. Order matters:
# whole secrets first, then the generic long-run rule.
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "<email>"),
    (re.compile(r"://[^/\s:@]+:[^@\s]+@"), "://<cred>@"),
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <token>"),
    (re.compile(r"(?i)\b([\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth)[\w-]*)"
                r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2<secret>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    (re.compile(r"\b(?:sk-proj-|sk-|ghp_|gho_|ghs_|ghu_|github_pat_|xox[abprs]-|glpat-)[A-Za-z0-9_\-]{8,}"), "<token>"),
    (re.compile(r"(?<![\w/+=])(?=[A-Za-z0-9_\-/+=]*\d)(?=[A-Za-z0-9_\-/+=]*[A-Za-z])[A-Za-z0-9_\-/+=]{32,}"), "<token>"),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"), "<ip>"),
    # IPv6: needs "::" or a hex letter, so clock times like 12:30:45 stay readable.
    (re.compile(r"(?i)(?<![\w:.])(?=[0-9a-f:]*(?:::|[a-f]))[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])"), "<ip>"),
]


def redact(text: str) -> str:
    text = str(text).replace(str(Path.home()), "~")
    for pat, sub in _REDACT:
        text = pat.sub(sub, text)
    return text


class _Lock:
    """An advisory lock around rotate-and-append, so two writers never rotate the same file twice."""

    def __init__(self, state: Path | None = None):
        self.state = STATE if state is None else state

    def __enter__(self):
        self.fd = os.open(self.state / ".ledger.lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except (ImportError, OSError):  # no fcntl (Windows): appends are still atomic, rotation is best effort
            pass
        return self

    def __exit__(self, *exc):
        os.close(self.fd)  # closing releases the lock


def _rotate(state: Path | None = None) -> None:
    state = STATE if state is None else state
    ledger, rotated = state / "ledger.jsonl", state / "ledger.1.jsonl"
    try:
        if ledger.stat().st_size >= ROTATE_BYTES:
            os.replace(ledger, rotated)
    except FileNotFoundError:
        pass


def add(kind: str, key: str, note: str = "", agent: str = "") -> dict | None:
    """Append one row to the first state folder that takes it.

    Returns the row, or None when every state folder is read-only. A hook that
    cannot write its own ledger must not fail the agent's turn, so this never
    raises OSError: an agent seat with a read-only home keeps working.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    row = {"ts": time.time(), "kind": kind, "key": redact(key)[:80], "note": redact(note)[:200],
           "agent": redact(agent or os.environ.get("SELENITE_AGENT", ""))[:40]}
    for state in state_dirs():
        try:
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            with _Lock(state):
                _rotate(state)
                fd = os.open(state / "ledger.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, "a") as fh:
                    fh.write(json.dumps(row) + "\n")
            return row
        except OSError:  # read-only home, full disk, no permission: the next folder may take it
            continue
    return None


def rows(days: int = 3650):
    """Yield well-formed rows newer than `days` from every state folder. Malformed lines are skipped."""
    since = time.time() - days * 86400
    for state in state_dirs():
        for path in (state / "ledger.1.jsonl", state / "ledger.jsonl"):
            yield from _read(path, since)


def signature() -> tuple:
    """A cheap fingerprint of every ledger file rows() reads. It changes whenever any of them does,
    so a cache keyed on it never misses rows written to a fallback state folder."""
    sig = []
    for state in state_dirs():
        for path in (state / "ledger.1.jsonl", state / "ledger.jsonl"):
            try:
                st = path.stat()
            except OSError:
                continue
            sig.append((str(path), st.st_mtime_ns, st.st_size, st.st_ino))
    return tuple(sig)


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
    7-day view, and a gate after the fix means the friction came back. An
    `approval` row after an `approval:<key>` fix reopens it the same way.
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
        elif k == "approval":
            akey = "approval:" + key[:APPROVAL_KEY]
            last_gate[akey] = max(last_gate.get(akey, 0.0), ts)
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
    sub.add_parser("state-dir", help="print the first state folder that accepts a write")
    ns = ap.parse_args()
    if ns.cmd == "add":
        print(json.dumps(add(ns.kind, ns.key, ns.note, ns.agent)))
    elif ns.cmd == "state-dir":
        state = writable_state()
        if state is None:
            return 1  # every folder is read-only: the caller prints the one line that fixes it
        print(state)
    else:
        print(json.dumps(summary(ns.days), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
