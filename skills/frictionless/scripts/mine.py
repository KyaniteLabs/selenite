#!/usr/bin/env python3
"""Selenite friction miner.

Reads agent transcripts (read-only), finds user-authored lines that signal
friction, and writes an aggregate report plus a private sample file.

Adapters: claude-code (~/.claude/projects/**.jsonl), codex
(~/.codex/sessions/**.jsonl), hermes ($HERMES_HOME/state.db, read-only), and
generic (--path): *.jsonl rows whose role is "user", or a single text file
you name directly, which is then read as your own words line by line.

Privacy: the aggregate report holds only counts and category names, and no
host name. Report and excerpts go to the Selenite state folder ($SELENITE_STATE,
else $XDG_STATE_HOME/selenite, else $HERMES_HOME/plugin-data/selenite, else
~/.local/state/selenite: the first that takes a write), mode 0600, never into the repo. Samples
are redacted by ledger.redact (emails, IPv4 and IPv6, URLs with credentials,
key=value secrets, bearer and prefixed tokens, long token runs, the home path)
and only the newest SAMPLE_KEEP files are kept.

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
SAMPLE_KEEP = 3
REPORT_KEEP = 10

if __package__:  # loaded as selenite_frictionless.mine by a Hermes host
    from . import ledger
    from .ledger import redact
    from .signals import classify
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # noqa: E402  (one state-folder chain for every Selenite script)
    from ledger import redact  # noqa: E402  (one redaction rule for the ledger and the samples)
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
        with f.open(encoding="utf-8", errors="ignore") as fh:
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
        with f.open(encoding="utf-8", errors="ignore") as fh:
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
    con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=2)  # as_uri escapes ?, # and %
    try:
        for (content,) in con.execute(
            "select content from messages where role='user' and timestamp>=?", (since,)
        ):
            yield "hermes", "hermes", content or ""
    finally:
        con.close()


def iter_generic(path: Path, since: float):
    """Generic source. A folder yields only *.jsonl rows marked role=user; a
    text file named directly is read as the human's own words."""
    if path.is_file() and path.suffix != ".jsonl":
        if path.stat().st_mtime >= since:
            for line in path.open(encoding="utf-8", errors="ignore"):
                yield "generic", path.parent.name, line
        return
    files = [path] if path.is_file() else sorted(path.rglob("*.jsonl"))
    for f in files:
        if f.stat().st_mtime < since:
            continue
        for line in f.open(encoding="utf-8", errors="ignore"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict) and o.get("role") == "user":
                yield "generic", f.parent.name, _text_of(o.get("content"))


def _write_private(path: Path, text: str) -> None:
    """Create the file 0600 from the start; samples quote private transcripts."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _prune(folder: Path, pattern: str, keep: int) -> None:
    for old in sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime)[:-keep]:
        old.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--path", action="append", default=[], help="extra generic source")
    ap.add_argument("--samples", type=int, default=8, help="private samples per category")
    ap.add_argument("--hermes-home", type=Path, default=None,
                    help="Hermes home to mine (default: $HERMES_HOME or ~/.hermes). On a shared host, "
                         "point this at your own profile so the report shows YOUR loop, not the host's.")
    ap.add_argument("--out", type=Path, default=None, help="report folder (default: the first writable state folder)")
    a = ap.parse_args()

    since = time.time() - a.days * 86400
    hermes_home = a.hermes_home or Path(os.environ.get("HERMES_HOME") or HOME / ".hermes")
    sources = [
        iter_claude(HOME / ".claude/projects", since),
        iter_codex(HOME / ".codex/sessions", since),
        iter_hermes(hermes_home / "state.db", since),
        *[iter_generic(Path(p).expanduser(), since) for p in a.path],
    ]
    counts: Counter = Counter()
    by_agent: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list] = defaultdict(list)
    per_agent = max(1, a.samples // 2)  # one busy agent must not eat the whole sample budget
    seen = 0
    for src in sources:
        try:
            for agent, scope, text in src:
                seen += 1
                for cat in classify(text):
                    counts[cat] += 1
                    by_agent[agent][cat] += 1
                    if len(samples[cat]) < a.samples and \
                            sum(1 for s in samples[cat] if s["agent"] == agent) < per_agent:
                        samples[cat].append({"agent": agent, "text": redact(text[:300])})
        except (OSError, sqlite3.Error) as e:
            print(f"selenite-mine: skipped a source: {e}", file=sys.stderr)

    if a.out is None:
        a.out = ledger.writable_state()
        if a.out is None:
            print("selenite-mine: no state folder is writable; set SELENITE_STATE or pass --out", file=sys.stderr)
            return 1
    try:
        a.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        print(f"selenite-mine: cannot write {redact(str(a.out))}: {e.strerror}", file=sys.stderr)
        return 1
    stamp = time.strftime("%Y%m%dT%H%M%S")
    report = {
        "schema": "selenite.friction-report/1",
        "generated": stamp, "window_days": a.days,
        "user_messages_scanned": seen,
        "counts": dict(counts.most_common()),
        "by_agent": {k: dict(v) for k, v in by_agent.items()},
    }
    _write_private(a.out / f"report-{stamp}.json", json.dumps(report, indent=2))
    sp = a.out / f"samples-{stamp}.json"
    _write_private(sp, json.dumps(samples, indent=2))
    _prune(a.out, "samples-*.json", SAMPLE_KEEP)
    _prune(a.out, "report-*.json", REPORT_KEEP)
    print(json.dumps(report, indent=2))
    # The user's own file on their own terminal: shorten the home, don't redact the name into "<token>".
    print(f"private samples: {str(sp).replace(str(Path.home()), '~', 1)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
