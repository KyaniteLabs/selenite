"""Read-only audit: kanban boards and instruction files.

Never writes to any board or file it reads. SQLite is opened with ``mode=ro`` URIs.

Every blocked card lands in exactly one bucket:
- ``auto_blocked``: the dispatcher parked it after repeated worker failures (a ``gave_up`` event);
  counted as MACHINERY.
- ``created_blocked``: created straight into blocked, with no block reason of its own.
- otherwise the classifier's class (WALL, HUMAN, DEPENDENCY, MACHINERY, or a FAKE subtype).

The headline counts a card as bureaucracy only when a phrase in its reason supports the verdict
(``evidenced``) and the confidence clears the threshold. Defaults (empty reasons, age alone) are
shown separately as ``unclear``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .classify import ACTIONS, FAKE, MACHINERY, WALL, classify

FAKE_THRESHOLD = 0.6

# Root causes that recur across many cards: one fix unblocks the whole group. Generic only.
_SHARED_CAUSES = [
    ("repo-write-permission", re.compile(r"push=false|HTTP 403|READ permission|permission denied \(publickey|cannot (resolve|access) [\w.-]+/[\w.-]+|404.*(clone|repo)", re.I)),
    ("package-registry-credentials", re.compile(r"ENEEDAUTH|npm whoami|\.npmrc|twine upload|401 .{0,20}registry", re.I)),
    ("read-only-filesystem", re.compile(r"read-?only (file ?system|fs)|errno ?30", re.I)),
    ("no-gpu-on-host", re.compile(r"no gpu|no (cuda|rocm|vulkan) devices?|gpu not found", re.I)),
    ("rate-limit", re.compile(r"rate[- ]limit|too many requests|\b429\b", re.I)),
    ("worker-crash-loop", re.compile(r"crash(ed)?|gave up|timed? ?out|spawn fail", re.I)),
    ("pr-relay", re.compile(r"relay|PR-?create (by|via)", re.I)),
    ("missing-tool-action", re.compile(r"no (such |supported )?action|executor has no|unsupported (action|operation)", re.I)),
]

_GATE_WORDS = re.compile(
    r"\b(ACK|sign-?off|approv\w*|authori[sz]\w*|gate[sd]?|HOLD|freeze|FROZEN|must ask|wait(ing)? (for|on)|escalat\w*|"
    r"ratif\w*|countersign\w*|ruling|relay|attest\w*)\b", re.I)
_ANTI_GATE = re.compile(r"(no (seat|agent) is an approval gate|never create cards to review|don't block on|do not block on|act autonomously|proceed directly)", re.I)


def _ro(path: Path) -> sqlite3.Connection:
    # as_uri escapes ?, # and % in a home path, so sqlite always opens this file, read-only
    con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


def card_statuses(task_ids: Iterable[str], dbs: Iterable[Path]) -> dict[str, str]:
    """Each card's current status (blocked, ready, archived...), read-only. Hermes fires no hook when a
    person unblocks or archives a card, so a badge is checked against the board itself. Ids missing
    from every board are left out: unknown is not cleared."""
    want = {str(t) for t in task_ids if t}
    out: dict[str, str] = {}
    for db in dbs:
        todo = sorted(want - out.keys())
        if not todo:
            break
        if not Path(db).is_file():
            continue
        try:
            con = _ro(Path(db))
            try:
                for i in range(0, len(todo), 500):
                    part = todo[i:i + 500]
                    q = f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' * len(part))})"
                    out.update({str(r["id"]): str(r["status"]) for r in con.execute(q, part) if r["status"]})
            finally:
                con.close()
        except sqlite3.Error:
            continue
    return out


def find_boards(roots: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        root = Path(root).expanduser()
        cands = [root / "kanban.db", *sorted((root / "kanban" / "boards").glob("*/kanban.db"))]
        for c in cands:
            if c.is_file() and "_archived" not in c.parts and c not in out:
                out.append(c)
    return out


def default_roots() -> list[Path]:
    env = os.environ.get("HERMES_HOME")
    roots = [Path(env)] if env else []
    for q in sorted(Path.home().glob(".hermes*")):
        if q.is_dir() and q not in roots:
            roots.append(q)
    return roots


def _bucket(v: dict, auto: bool, created: bool) -> str:
    if auto:
        return "auto_blocked"
    if created:
        return "created_blocked"
    return v["label"] if v["cls"] == FAKE else v["cls"]


def audit_board(db: Path, now: float | None = None) -> dict:
    now = now or time.time()
    try:
        con = _ro(db)
        try:
            cols = {r[1] for r in con.execute("pragma table_info(tasks)")}
            if "status" not in cols:
                return {"board": str(db), "error": "not a kanban board (no tasks table)"}
            kind_col = "t.block_kind" if "block_kind" in cols else "NULL"
            err_col = "t.last_failure_error" if "last_failure_error" in cols else "NULL"
            rows = con.execute(f"""
                with lb as (select task_id, max(id) mid from task_events where kind in ('blocked','gave_up') group by task_id)
                select t.id, t.title, t.assignee, t.created_at, {kind_col} as block_kind, {err_col} as fail_err,
                       e.kind as ev_kind, e.payload, e.created_at as blocked_at
                from tasks t left join lb on lb.task_id=t.id left join task_events e on e.id=lb.mid
                where t.status='blocked'""").fetchall()
            statuses = dict(con.execute("select status, count(*) from tasks group by status").fetchall())
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {"board": str(db), "error": str(exc)}

    cards = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        auto = r["ev_kind"] == "gave_up" or ("trigger_outcome" in payload and not payload.get("reason"))
        reason = str(payload.get("reason") or "")
        created = reason == "initial_status"
        if auto:
            reason = str(payload.get("error") or r["fail_err"] or payload.get("trigger_outcome") or "worker gave up")
        since = r["blocked_at"] or r["created_at"] or now
        try:
            age_h = max(0.0, (now - float(since)) / 3600)
        except (TypeError, ValueError):
            age_h = 0.0
        if auto:
            v = classify(reason)
            vd = v.to_dict()
            if v.cls != MACHINERY:  # the dispatcher's own verdict: the worker kept failing
                vd.update(cls=MACHINERY, subtype="", label=MACHINERY, reason="dispatcher auto-block after worker failures",
                          action=ACTIONS[MACHINERY], confidence=0.8)
        else:
            vd = classify("" if created else reason, kind=r["block_kind"] or payload.get("kind"),
                          age_hours=age_h, created_blocked=created).to_dict()
        causes = [name for name, pat in _SHARED_CAUSES if pat.search(reason)]
        cards.append({
            "id": r["id"], "title": (r["title"] or "")[:90], "assignee": r["assignee"],
            "age_h": round(age_h, 1), "reason": "" if created else reason[:400],
            "bucket": _bucket(vd, auto, created), "verdict": vd, "shared_causes": causes,
        })
    return {"board": str(db), "statuses": statuses, "blocked": cards}


def is_fake(card: dict, threshold: float | None = None) -> bool:
    """None reads FAKE_THRESHOLD at call time, so min_confidence set after import still applies."""
    threshold = FAKE_THRESHOLD if threshold is None else threshold
    v = card["verdict"]
    return (v["cls"] == FAKE and bool(v.get("matched")) and v["confidence"] >= threshold
            and card.get("bucket") not in ("auto_blocked", "created_blocked"))


def summarize(boards: list[dict], threshold: float | None = None) -> dict:
    threshold = FAKE_THRESHOLD if threshold is None else threshold
    by_bucket: Counter = Counter()
    by_seat: dict[str, Counter] = defaultdict(Counter)
    causes: dict[str, list[str]] = defaultdict(list)
    errors = []
    running = blocked = fake = unclear = 0
    for b in boards:
        if b.get("error"):
            errors.append({"board": b["board"], "error": b["error"]})
            continue
        st = b.get("statuses", {})
        running += st.get("running", 0)
        blocked += st.get("blocked", 0)
        for c in b.get("blocked", []):
            bucket = c.get("bucket") or _bucket(c["verdict"], False, False)
            by_bucket[bucket] += 1
            by_seat[c["assignee"] or "?"][bucket] += 1
            if is_fake(c, threshold):
                fake += 1
            elif c["verdict"]["cls"] == FAKE and bucket not in ("auto_blocked", "created_blocked"):
                unclear += 1
            for cause in c["shared_causes"]:
                causes[cause].append(c["id"])
    return {
        "running": running, "blocked": blocked, "fake": fake, "unclear": unclear,
        "created_blocked": by_bucket.get("created_blocked", 0), "auto_blocked": by_bucket.get("auto_blocked", 0),
        "fake_share": round(fake / blocked, 2) if blocked else 0.0,
        "by_label": dict(by_bucket.most_common()),
        "by_seat": {s: dict(c.most_common()) for s, c in sorted(by_seat.items(), key=lambda kv: -sum(kv[1].values()))},
        "shared_causes": {k: v for k, v in sorted(causes.items(), key=lambda kv: -len(kv[1])) if len(v) >= 2},
        "errors": errors,
    }


def counts_only(summary: dict) -> dict:
    """The summary with nothing that names a card or a person."""
    keep = ("running", "blocked", "fake", "unclear", "created_blocked", "auto_blocked", "fake_share", "by_label")
    out = {k: summary.get(k) for k in keep}
    out["shared_causes"] = {k: len(v) for k, v in summary.get("shared_causes", {}).items()}
    out["board_errors"] = len(summary.get("errors", []))
    return out


def headline(s: dict) -> str:
    line = (f"{s['blocked']} blocked vs {s['running']} running. {s['fake']} of the blocked "
            f"({int(s['fake_share'] * 100)}%) wait on agent bureaucracy, by the reasons they give.")
    extra = []
    if s.get("unclear"):
        extra.append(f"{s['unclear']} give no clear reason")
    if s.get("created_blocked"):
        extra.append(f"{s['created_blocked']} were created blocked")
    if s.get("auto_blocked"):
        extra.append(f"{s['auto_blocked']} were auto-blocked after worker failures")
    if s.get("errors"):
        extra.append(f"{len(s['errors'])} board(s) could not be read")
    return line + (" " + "; ".join(extra) + "." if extra else "")


# Selenite's own skills describe gates in order to clear them; scoring them would make Selenite a finding.
SELF_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def audit_rules(paths: Iterable[Path]) -> list[dict]:
    out = []
    for p in paths:
        p = Path(p).expanduser()
        if not p.is_file() or p.resolve().is_relative_to(SELF_SKILLS):
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError as exc:
            out.append({"path": str(p), "words": 0, "gate_lines": 0, "gate_density_per_1k": 0.0,
                        "has_anti_gate_clause": False, "examples": [], "error": type(exc).__name__})
            continue
        lines = text.splitlines()
        gate_lines = [(i + 1, ln.strip()[:200]) for i, ln in enumerate(lines) if _GATE_WORDS.search(ln)]
        words = max(1, len(text.split()))
        out.append({
            "path": str(p), "words": words, "gate_lines": len(gate_lines),
            "gate_density_per_1k": round(1000 * len(gate_lines) / words, 1),
            "has_anti_gate_clause": bool(_ANTI_GATE.search(text)),
            "examples": gate_lines[:8],
        })
    return sorted(out, key=lambda r: -r["gate_density_per_1k"])


def default_rule_paths() -> list[Path]:
    home = Path.home()
    pats = [
        "~/.claude/CLAUDE.md", "~/.claude/rules/*.md", "~/AGENTS.md", "~/.codex/AGENTS.md", "~/.gemini/GEMINI.md",
        "~/.agents/rules/*.md", "~/.config/kilo/AGENTS.md",
    ]
    for root in default_roots():  # every Hermes home: its persona, rules and per-profile personas
        r = str(root)
        pats += [f"{r}/SOUL.md", f"{r}/AGENTS.md", f"{r}/profiles/*/SOUL.md"]
    out: list[Path] = []
    for pat in pats:
        base = Path(pat.replace("~", str(home), 1)) if pat.startswith("~") else Path(pat)
        out.extend(sorted(base.parent.glob(base.name)) if "*" in base.name else [base])
    seen: set[Path] = set()
    return [p for p in out if p.is_file() and not (p in seen or seen.add(p))]


def skill_paths() -> list[Path]:
    home = Path.home()
    roots = [home / ".claude/skills", home / ".agents/skills", home / ".codex/skills"]
    for h in default_roots():
        roots += [h / "skills", *sorted((h / "profiles").glob("*/skills"))]
    return sorted({p for r in roots if r.is_dir() for p in r.rglob("SKILL.md")})


def render_markdown(summary: dict, boards: list[dict], rules: list[dict], top: int = 12) -> str:
    s = summary
    L = ["# antibeaurocracy audit", "", f"**{headline(s)}**", ""]
    if s["by_label"]:
        L.append("## What the blocked cards are")
        notes = {"auto_blocked": ACTIONS[MACHINERY], "created_blocked": "Created straight into blocked. Give it an owner and an expiry, or move it to triage."}
        for k, n in s["by_label"].items():
            L.append(f"- **{k}** × {n} — {notes.get(k) or ACTIONS.get(k) or ACTIONS[WALL]}")
        L.append("")
    if s["shared_causes"]:
        L.append("## One fix, many cards")
        for cause, ids in s["shared_causes"].items():
            L.append(f"- `{cause}` blocks {len(ids)} cards: {', '.join(ids[:8])}{' …' if len(ids) > 8 else ''}")
        L.append("")
    fakes = [c for b in boards for c in b.get("blocked", []) if is_fake(c)]
    fakes.sort(key=lambda c: (-c["age_h"], -c["verdict"]["confidence"]))
    if fakes:
        L.append(f"## Oldest {min(top, len(fakes))} fake gates")
        for c in fakes[:top]:
            v = c["verdict"]
            L.append(f"- `{c['id']}` ({c['assignee'] or 'unassigned'}, {c['age_h']:.0f}h) **{v['label']}** — {c['title']}")
            L.append(f"  - do: {v['action']}")
        L.append("")
    if s.get("errors"):
        L.append("## Boards that could not be read")
        for e in s["errors"]:
            L.append(f"- {e['board']}: {e['error']}")
        L.append("")
    if rules:
        L.append("## Rule files by gate language (lines per 1k words)")
        for r in rules[:top]:
            flag = " · also has an anti-gate clause" if r["has_anti_gate_clause"] and r["gate_lines"] >= 5 else ""
            flag += f" · could not be read ({r['error']})" if r.get("error") else ""
            L.append(f"- {r['gate_density_per_1k']:>5} · {r['gate_lines']} lines · {r['path']}{flag}")
        L.append("")
    return "\n".join(L)


def run(roots: Iterable[Path] | None = None, rule_paths: Iterable[Path] | None = None) -> dict:
    boards = [audit_board(db) for db in find_boards(roots or default_roots())]
    rules = audit_rules(rule_paths if rule_paths is not None else default_rule_paths())
    summary = summarize(boards)
    return {"summary": summary, "boards": boards, "rules": rules,
            "markdown": render_markdown(summary, boards, rules)}
