#!/usr/bin/env python3
"""Selenite friction miner.

Reads agent transcripts (read-only), finds user-authored lines that signal
friction, and writes an aggregate report plus a private sample file.

Adapters: claude-code (~/.claude/projects/**.jsonl), codex
(~/.codex/sessions/**.jsonl), hermes (~/.hermes/state.db, read-only), and
generic (any *.jsonl/*.md/*.txt path passed with --path).

Privacy: the aggregate report holds only counts and category names. Raw
excerpts go to the private samples file under $SELENITE_STATE (default
~/.local/state/selenite), mode 0600, never into the repo.

Stdlib only. Run at low priority:  nice -n 19 python3 mine.py --days 45
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("SELENITE_STATE", HOME / ".local/state/selenite"))

if __package__:  # loaded as selenite_frictionless.mine by a Hermes host
    from .signals import classify
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from signals import classify  # noqa: E402  (shared detector)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") in ("text", "input_text")
        )
    return ""


def iter_claude(root: Path, since: float):
    for f in root.rglob("*.jsonl"):
        if "/subagents/" in str(f) or f.stat().st_mtime < since:
            continue
        with f.open(errors="ignore") as fh:
            for line in fh:
                if '"type":"user"' not in line[:200] and '"type": "user"' not in line[:200]:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "user" or o.get("isMeta") or o.get("toolUseResult"):
                    continue
                msg = o.get("message") or {}
                if msg.get("role") == "user":
                    yield "claude-code", f.parent.name, _text_of(msg.get("content"))


def iter_codex(root: Path, since: float):
    for f in root.rglob("*.jsonl"):
        if f.stat().st_mtime < since:
            continue
        with f.open(errors="ignore") as fh:
            for line in fh:
                if '"role":"user"' not in line and '"user_message"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                p = o.get("payload") or {}
                if p.get("type") == "user_message":
                    yield "codex", "codex", p.get("message", "")
                elif p.get("type") == "message" and p.get("role") == "user":
                    yield "codex", "codex", _text_of(p.get("content"))


def iter_hermes(db: Path, since: float):
    if not db.exists():
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    try:
        for (content,) in con.execute(
            "select content from messages where role='user' and timestamp>=?", (since,)
        ):
            yield "hermes", "hermes", content or ""
    finally:
        con.close()


def iter_generic(path: Path, since: float):
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.suffix in (".jsonl", ".md", ".txt")]
    for f in files:
        if f.stat().st_mtime < since:
            continue
        for line in f.open(errors="ignore"):
            yield "generic", f.parent.name, line


def _write_private(path: Path, text: str) -> None:
    """Create the file 0600 from the start; samples quote private transcripts."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--path", action="append", default=[], help="extra generic source")
    ap.add_argument("--host", default=os.uname().nodename)
    ap.add_argument("--samples", type=int, default=8, help="private samples per category")
    ap.add_argument("--out", type=Path, default=STATE)
    a = ap.parse_args()

    since = time.time() - a.days * 86400
    sources = [
        iter_claude(HOME / ".claude/projects", since),
        iter_codex(HOME / ".codex/sessions", since),
        iter_hermes(HOME / ".hermes/state.db", since),
        *[iter_generic(Path(p).expanduser(), since) for p in a.path],
    ]
    counts: Counter = Counter()
    by_agent: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list] = defaultdict(list)
    seen = 0
    for src in sources:
        try:
            for agent, scope, text in src:
                seen += 1
                for cat in classify(text):
                    counts[cat] += 1
                    by_agent[agent][cat] += 1
                    if len(samples[cat]) < a.samples:
                        samples[cat].append({"agent": agent, "scope": scope, "text": text[:300]})
        except (OSError, sqlite3.Error) as e:
            print(f"selenite-mine: skipped a source: {e}", file=sys.stderr)

    a.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    report = {
        "schema": "selenite.friction-report/1",
        "host": a.host, "generated": stamp, "window_days": a.days,
        "user_messages_scanned": seen,
        "counts": dict(counts.most_common()),
        "by_agent": {k: dict(v) for k, v in by_agent.items()},
    }
    _write_private(a.out / f"report-{a.host}-{stamp}.json", json.dumps(report, indent=2))
    sp = a.out / f"samples-{a.host}-{stamp}.json"
    _write_private(sp, json.dumps(samples, indent=2))
    print(json.dumps(report, indent=2))
    print(f"private samples: {sp}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
