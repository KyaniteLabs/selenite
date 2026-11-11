"""Provider-agnostic CLI: ``antibeaurocracy classify|audit|rules``. Works with any agent that can run a shell."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from . import audit as _audit
from . import judge as _judge
from . import settings as _settings
from .classify import FAKE, classify


def add_arguments(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("classify", help="classify one block or wait reason (text or stdin)")
    c.add_argument("text", nargs="*")
    c.add_argument("--kind", choices=["dependency", "needs_input", "capability", "transient"])
    c.add_argument("--age-hours", type=float)
    a = sub.add_parser("audit", help="read-only audit of kanban boards + instruction files")
    a.add_argument("--root", action="append", type=Path, help="Hermes home(s); default: the active home ($HERMES_HOME, else ~/.hermes)")
    a.add_argument("--all-homes", action="store_true", help="scan every ~/.hermes* directory, not just the active home")
    a.add_argument("--rules", action="append", type=Path, help="instruction files to score (default: known agent rule files)")
    a.add_argument("--no-rules", action="store_true")
    a.add_argument("--skills", action="store_true", help="also score every SKILL.md under the known skill directories")
    a.add_argument("--top", type=int, default=12)
    a.add_argument("--counts", action="store_true", help="counts only: no card titles, reasons or assignees")
    a.add_argument("--judge", metavar="CMD", help="optional second opinion: a command (e.g. an LLM CLI) that reads a prompt "
                   "on stdin and prints WALL/HUMAN/MACHINERY/DEPENDENCY/FAKE. Sends each fake card's reason to it. Off by default.")
    a.add_argument("--judge-max", type=int, default=20, help="most cards to send to --judge (oldest first)")
    a.add_argument("--judge-timeout", type=float, default=60.0, help="seconds per --judge call")
    for sp in (c, a):
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--seat", action="append", default=[], help="a seat or agent-role name your team uses (repeatable)")


def handle(args: argparse.Namespace, settings: dict | None = None) -> int:
    """``settings`` comes from the plugin context inside Hermes; outside it, from $HERMES_HOME/config.yaml.
    --seat adds to the configured extra_seats."""
    if settings is None:
        settings, err = _settings.read()
        if err:
            print(f"antibeaurocracy: Selenite settings unreadable ({err}); using defaults.", file=sys.stderr)
    _settings.apply(settings, extra_seats=getattr(args, "seat", None) or ())
    if args.cmd == "classify":
        text = " ".join(args.text) if args.text else sys.stdin.read()
        if not re.search(r"\w", text):
            print("antibeaurocracy: nothing to classify (pass the reason as text or on stdin).", file=sys.stderr)
            return 2
        v = classify(text, kind=args.kind, age_hours=args.age_hours)
        d = v.to_dict()
        # Same bar the audit uses: a FAKE below min_confidence (or with no matched phrase) is not acted on.
        d["low_confidence"] = v.cls == FAKE and not _audit.is_fake({"verdict": d})
        if args.json:
            print(json.dumps(d, indent=2))
        elif d["low_confidence"]:
            print(f"{v.label} ({v.confidence}) — low confidence, no action. Read the card yourself.")
        else:
            print(f"{v.label} ({v.confidence}) — {v.action}")
        return 0
    if args.cmd == "audit":
        boards = [_audit.audit_board(db) for db in _audit.find_boards(args.root or _audit.default_roots(args.all_homes))]
        paths = [] if args.no_rules else list(args.rules or _audit.default_rule_paths(args.all_homes))
        if args.skills:
            paths += _audit.skill_paths(args.all_homes)
        rules = _audit.audit_rules(paths)
        summary = _audit.summarize(boards)
        if args.judge and args.counts:
            print("--judge sends card reasons to a command, so it can't be combined with --counts.", file=sys.stderr)
            return 2
        opinion = (_judge.second_opinion(boards, _judge.runner(args.judge, args.judge_timeout), args.judge_max)
                   if args.judge else None)
        if args.counts:
            print(json.dumps(_audit.counts_only(summary), indent=2))
            for e in summary.get("errors", []):  # counts stay name-free on stdout; say which board failed on stderr
                board = str(e["board"]).replace(str(Path.home()), "~", 1)
                print(f"antibeaurocracy: could not read {board}: {e['error']}", file=sys.stderr)
            return 0
        if args.json:
            out = {"summary": summary, "boards": boards, "rules": rules}
            if opinion is not None:
                out["second_opinion"] = opinion
            print(json.dumps(out, indent=2, default=str))
        else:
            print(_audit.render_markdown(summary, boards, rules, top=args.top))
            if opinion is not None:
                print(_judge.render(opinion))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="antibeaurocracy", description="Find and dissolve fake gates in agent work.")
    p.add_argument("--version", action="version", version=f"antibeaurocracy {__version__}")
    add_arguments(p)
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 2
    return handle(args)


if __name__ == "__main__":
    raise SystemExit(main())
