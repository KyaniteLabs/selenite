#!/usr/bin/env python3
"""Selenite cleanse: clear and recharge every other tool in the stack.

Selenite is the stone used to clear the other stones. This pass inventories
the rest of the stack (the skills, plugins, hooks, approvals and runbooks
your agents use), finds what makes them hand work back to the human, and
ranks it: measured interruptions first, then structural faults by how often
they bite. Every finding carries the fix that would clear it. Nothing is
changed: the fixes are proposals for a reviewable change.

  cleanse.py                    scan every agent home found on this machine
  cleanse.py --path DIR         also scan runbooks (*.md) under DIR
  cleanse.py --json             print the report as JSON
  cleanse.py --days N           window for ledger-measured findings (default 30)

Read-only apart from its own report under $SELENITE_STATE (0600, newest 10
kept) and, when run from the command line, one ledger row with the finding
count. Paths in the report are shown with the home prefix as ~. Stdlib only.

Stones are checked by small adapters in CHECKS. The fake-gate facet keeps
its own metadata ledger; it is read as one more stone, by counts only.
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

if __package__:  # loaded as selenite_frictionless.cleanse by a Hermes host
    from . import ledger
    from .signals import COMPILED
else:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # noqa: E402
    from signals import COMPILED  # noqa: E402

HOME = Path.home()
SELF_SKILL = Path(__file__).resolve().parent.parent
SELF_SKILLS = ("frictionless", "antibeaurocracy", "antipedantry")  # Selenite's three facets, side by side
KEEP = 10
DESC_LIMIT = 1024  # Agent Skills spec: description is at most 1024 characters
APPROVAL_REPEAT = 3  # the same approval this often in the window is an allowlist candidate
GATE_REPEAT = 2

# Severity of structural faults, as "how often does this hand work back".
EVERY_CALL, EVERY_USE, SOMETIMES, DRIFT = 4, 3, 2, 1
SEVERITY_NAME = {EVERY_CALL: "every call", EVERY_USE: "every use", SOMETIMES: "sometimes", DRIFT: "drift"}


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or HOME / ".hermes")


def skill_roots() -> dict[str, Path]:
    return {
        "claude-code": HOME / ".claude/skills",
        "agents": HOME / ".agents/skills",
        "codex": HOME / ".codex/skills",
        "opencode": HOME / ".config/opencode/skills",
        "hermes": hermes_home() / "skills",
    }


def tilde(p: Path | str) -> str:
    s = str(p)
    h = str(HOME)
    return "~" + s[len(h):] if s == h or s.startswith(h + os.sep) else s


def finding(stone: str, where, check: str, problem: str, fix: str, *, n: int = 0, severity: int = 0) -> dict:
    return {"stone": stone, "where": tilde(where), "check": check, "problem": problem, "fix": fix,
            "interruptions": n, "severity": severity}


# --- frontmatter (no YAML dependency: top-level scalar keys only) -----------

_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def frontmatter(text: str) -> dict[str, str] | None:
    m = _FM.match(text)
    if not m:
        return None
    out: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        top = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if top:
            key, val = top.group(1), top.group(2).strip()
            out[key] = "" if val in (">", "|", ">-", "|-") else val.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


# --- stone adapters ---------------------------------------------------------

def check_skills(ctx: dict) -> list[dict]:
    out: list[dict] = []
    seen: dict[str, set[str]] = {}
    for agent, root in skill_roots().items():
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.name.startswith("."):
                continue
            if d.is_symlink() and not d.exists():
                out.append(finding("skill", d, "dangling-link", f"{agent} links a skill that no longer exists",
                                   "Remove the link or reinstall the skill.", severity=EVERY_USE))
                continue
            if not d.is_dir():
                continue
            out += _check_one_skill(d, agent)
            seen.setdefault(d.name, set()).add(str(d.resolve()))
    for name, targets in sorted(seen.items()):
        if len(targets) > 1:
            out.append(finding("skill", f"{len(targets)} copies of {name}", "drift",
                               f"Agents load {len(targets)} different copies of `{name}`, so they follow different rules",
                               "Keep one source and link it into each agent.", severity=DRIFT))
    return out


def _check_one_skill(d: Path, agent: str) -> list[dict]:
    f = d / "SKILL.md"
    if not f.exists():
        return []  # a folder of other things, not a skill
    text = f.read_text(errors="ignore")
    fm = frontmatter(text)
    if fm is None or not fm.get("name") or not fm.get("description"):
        return [finding("skill", f, "no-frontmatter", "No name or description, so agents can't tell when to load it",
                        "Add frontmatter with `name` and a `description` that says when to use it.", severity=EVERY_USE)]
    out = []
    if fm["name"] != d.name:
        out.append(finding("skill", f, "name-mismatch", f"Named `{fm['name']}` in a folder called `{d.name}`",
                           "Make the folder and the `name` field match.", severity=SOMETIMES))
    if len(fm["description"]) > DESC_LIMIT:
        out.append(finding("skill", f, "long-description",
                           f"Description is {len(fm['description'])} characters; loaders cut it at {DESC_LIMIT}",
                           "Shorten it to the triggers that route the skill.", severity=SOMETIMES))
    for ref in sorted(set(re.findall(r"`((?:references|scripts|assets)/[\w./-]+)`", text))):
        if not (d / ref).exists():
            out.append(finding("skill", f, "broken-reference", f"Points at `{ref}`, which isn't in the skill folder",
                               "Restore the file or drop the reference.", severity=DRIFT))
    return out


def check_plugins(ctx: dict) -> list[dict]:
    out: list[dict] = []
    root = hermes_home() / "plugins"
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if d.name.startswith("."):
            continue
        if d.is_symlink() and not d.exists():
            out.append(finding("plugin", d, "dangling-link", "Hermes links a plugin that no longer exists",
                               "Remove the link or reinstall the plugin.", severity=EVERY_USE))
            continue
        if not d.is_dir():
            continue
        man = next((d / n for n in ("plugin.yaml", "plugin.yml") if (d / n).exists()), None)
        if man is None:
            if (d / "plugin.json").exists() or (d / ".claude-plugin").is_dir():
                continue  # another harness's plugin format; not Hermes's to judge
            if not any(d.iterdir()):
                out.append(finding("plugin", d, "empty-plugin", "An empty plugin folder",
                                   "Remove it.", severity=DRIFT))
            else:
                out.append(finding("plugin", d, "no-manifest", "No plugin.yaml, so Hermes can't load it",
                                   "Add a manifest or remove the folder.", severity=EVERY_USE))
            continue
        keys = {m.group(1) for m in re.finditer(r"^([A-Za-z_]\w*):", man.read_text(errors="ignore"), re.M)}
        if "manifest_version" not in keys:
            out.append(finding("plugin", man, "old-manifest", "No `manifest_version`, so newer Hermes treats it as legacy",
                               "Add `manifest_version: 2` and declare settings in `config_schema`.", severity=DRIFT))
    return out


def _hook_commands(settings: dict):
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    yield event, h["command"]


def check_hooks(ctx: dict) -> list[dict]:
    out: list[dict] = []
    for f in (HOME / ".claude/settings.json", HOME / ".claude/settings.local.json"):
        try:
            settings = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for event, cmd in _hook_commands(settings):
            for tok in re.findall(r"(?:~|\$HOME|/)[\w./@+-]+", cmd):
                path = Path(tok.replace("$HOME", str(HOME))).expanduser()
                if path.suffix in (".sh", ".py", ".js", ".mjs", ".ts") and not path.exists():
                    out.append(finding("hook", f, "missing-hook-script",
                                       f"The {event} hook runs `{tilde(path)}`, which isn't there, so it fails on every call",
                                       "Restore the script or remove the hook.", severity=EVERY_CALL))
    return out


def check_ledger(ctx: dict) -> list[dict]:
    out: list[dict] = []
    rows = list(ledger.rows(ctx["days"]))
    fixed = ledger.fixed_keys()
    approvals = Counter(r["key"] for r in rows if r["kind"] == "approval")
    for key, n in approvals.most_common():
        if n >= APPROVAL_REPEAT and f"approval:{key}" not in fixed:
            out.append(finding("approval", key, "repeat-approval", f"The human approved `{key}` {n} times",
                               "Allowlist it if it is safe and reversible, or add a hook that decides it.", n=n))
    gates = Counter(r["key"] for r in rows if r["kind"] in ("gate", "blocked"))
    for key, n in gates.most_common():
        if n >= GATE_REPEAT and key not in fixed:
            out.append(finding("gate", key, "repeat-gate", f"The same human step came back {n} times",
                               "Run Gate mode: eliminate it, automate it, or make it one self-checking command.", n=n))
    return out


# Runbooks are scanned only for imperative human steps. The chat signals also
# match words like "2fa", "otp" or "friction-free", which a runbook mentions
# without telling anyone to do anything.
RUNBOOK_SKIP = ("2fa", "otp", "friction")


def check_runbooks(ctx: dict) -> list[dict]:
    out: list[dict] = []
    pats = [p for p in COMPILED.get("human_gate", []) if not any(w in p.pattern for w in RUNBOOK_SKIP)]
    for root in ctx["paths"]:
        files = [root] if root.is_file() else sorted(root.rglob("*.md"))
        for f in files[:2000]:
            if any(part in ("node_modules", ".git") for part in f.parts):
                continue
            try:
                lines = f.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            hits = sum(1 for ln in lines if any(p.search(ln) for p in pats))
            if hits:
                out.append(finding("runbook", f, "manual-steps", f"{hits} manual step(s) a human is told to do",
                                   "Turn each into one idempotent command that prints PASS or FAIL, or automate it.",
                                   severity=SOMETIMES))
    return out


FAKE_EVENTS = ("block_attempt", "blocked_observed")  # a card blocked or about to be; not asks or declarations
CLEARS = ("asked", "declared")  # the agent answered the question, or Hermes declared a real kind: not a fake wait
FAKE_MIN_CONF = 0.6  # the facet's own nudge floor: under it the classifier is guessing, not finding


def check_fake_gates(ctx: dict) -> list[dict]:
    """The fake-gate facet's metadata ledger: distinct cards whose block read as agent bureaucracy."""
    out: list[dict] = []
    d = hermes_home() / "plugin-data/antibeaurocracy"
    since = time.time() - ctx["days"] * 86400
    last: dict[str, bool] = {}  # card -> is its latest event a fake wait
    for f in (d / "ledger.1.jsonl", d / "ledger.jsonl"):  # oldest first, so later events win
        if f.exists():
            _fake_cards(f, since, last)
    cards = [c for c, fake in last.items() if fake]
    if cards:
        out.append(finding("fake-gate", "kanban", "fake-waits",
                           f"{len(cards)} card(s) waited on another agent with no real wall",
                           "Run `antibeaurocracy audit` and clear the shared cause it names.", n=len(cards)))
    return out


def _fake_cards(f: Path, since: float, last: dict[str, bool]) -> None:
    """Track each card's latest event. A fake block marks it; an ask or a
    declared kind clears it; a fail-open leaves it as it was. A row that
    carries a declared kind is Hermes's own wall, never a fake wait."""
    with f.open(errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not (isinstance(r, dict) and isinstance(r.get("ts"), (int, float)) and r["ts"] >= since):
                continue
            card = str(r.get("task") or f"row{len(last)}")
            event, conf = r.get("event"), r.get("conf")
            if event in CLEARS:
                last[card] = False
            elif event in FAKE_EVENTS:
                last[card] = (not r.get("declared")
                              and bool(re.match(r"(FAKE|F[1-6])\b", str(r.get("verdict", "")).upper()))
                              and isinstance(conf, (int, float)) and not isinstance(conf, bool)
                              and conf >= FAKE_MIN_CONF)


def needs_no_cleansing() -> list[dict]:
    """Selenite needs no cleansing: this must return []. CI runs it on every
    change, so a dirty Selenite never ships and never shows up as the human's
    finding. The runtime sweep skips nothing: if Selenite ever drifts on a
    machine, it shows up there like any other stone."""
    return [f for name in SELF_SKILLS for f in _check_one_skill(SELF_SKILL.parent / name, name)]


CHECKS = [check_ledger, check_fake_gates, check_hooks, check_skills, check_plugins, check_runbooks]


def rank(findings: list[dict]) -> list[dict]:
    """Clarity: measured interruptions first, then structural faults by how often they bite."""
    return sorted(findings, key=lambda f: (-f["interruptions"], -f["severity"], f["stone"], f["where"]))


def run(days: int = 30, paths: list[Path] | None = None) -> dict:
    ctx = {"days": days, "paths": paths or []}
    found: list[dict] = []
    errors: list[str] = []
    for check in CHECKS:
        try:
            found += check(ctx)
        except Exception as exc:  # one broken adapter must not hide the others
            errors.append(f"{check.__name__}: {type(exc).__name__}")
    ranked = rank(found)
    return {"schema": "selenite.cleanse/1", "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "window_days": days, "findings": ranked, "by_stone": dict(Counter(f["stone"] for f in ranked)),
            "errors": errors}


def write(report: dict) -> Path:
    ledger.STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    out = ledger.STATE / f"cleanse-{time.strftime('%Y%m%dT%H%M%S')}.json"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(report, fh, indent=2)
    for old in sorted(ledger.STATE.glob("cleanse-*.json"), key=lambda f: f.stat().st_mtime)[:-KEEP]:
        old.unlink(missing_ok=True)
    return out


def latest() -> dict | None:
    files = sorted(ledger.STATE.glob("cleanse-*.json"), key=lambda f: f.stat().st_mtime)
    for f in reversed(files):
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return None


def render(report: dict, top: int = 15) -> str:
    fs = report["findings"]
    lines = [f"Selenite cleanse: {len(fs)} finding(s) across {len(report['by_stone'])} kind(s) of stone."]
    for i, f in enumerate(fs[:top], 1):
        weight = f"×{f['interruptions']}" if f["interruptions"] else SEVERITY_NAME.get(f["severity"], "")
        lines.append(f"{i}. [{f['stone']}, {weight}] {f['problem']} ({f['where']})\n   fix: {f['fix']}")
    if len(fs) > top:
        lines.append(f"... {len(fs) - top} more in the report.")
    if report["errors"]:
        lines.append("Checks that failed: " + ", ".join(report["errors"]))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--path", action="append", default=[], help="runbook file or folder to scan")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    report = run(a.days, [Path(p).expanduser() for p in a.path])
    path = None
    try:
        path = write(report)
        ledger.add("cleanse", "run", note=f"{len(report['findings'])} findings")
    except OSError as exc:
        print(f"Selenite: cannot write the state folder ({exc}). "
              f"Point SELENITE_STATE at a writable folder and re-run; the findings follow anyway:",
              file=sys.stderr)
    print(json.dumps(report, indent=2) if a.json else render(report))
    if path is None:
        print("report: not saved (state folder unwritable)", file=sys.stderr)
        return 2
    print(f"report: {tilde(path)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
