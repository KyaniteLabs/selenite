"""Selenite's settings, read the same way by the plugin, the CLI and the dashboard.

Inside Hermes the plugin gets its settings from ``ctx.get_config``. The CLI and
the dashboard run outside that context, so they read
``plugins.entries.selenite.settings`` from ``$HERMES_HOME/config.yaml``
themselves, without importing Hermes internals. A missing or unreadable config
gives empty settings, and the reason is returned so callers can log it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from . import audit as _audit
from .classify import configure

PLUGIN = "selenite"


def as_list(val) -> list[str]:
    """A list setting given as a list or as one comma-separated string."""
    if isinstance(val, str):
        return [s for s in (x.strip() for x in val.split(",")) if s]
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if x is not None and str(x).strip()]
    return []


def _scalar(raw: str):
    v = raw.strip()
    if v[:1] in "\"'":
        if len(v) < 2 or v[-1] != v[0]:
            raise ValueError("unclosed quote")
        return v[1:-1]
    if v[:1] == "[":
        if not v.endswith("]"):
            raise ValueError("unclosed flow list")
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if v == "{}":
        return {}
    if v[:1] in "{&*!%@`":
        return v  # a flow map, anchor, alias or tag: kept as text, since only Selenite's own entry is used
    low = v.lower()
    if low in ("", "~", "null"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    for kind in (int, float):
        try:
            return kind(v)
        except ValueError:
            pass
    return v


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _mini_yaml(text: str):
    """The block mappings, lists and scalars a Hermes config.yaml uses, for hosts with no YAML library.
    Anything else raises ValueError, so a config it can't read is reported instead of misread."""
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    pending: tuple[int, dict, str] | None = None  # a "key:" whose value is the next, deeper block
    literal = -1  # inside a | or > block scalar opened at this indent; its lines are skipped
    for n, raw in enumerate(text.splitlines(), 1):
        if literal >= 0:
            if not raw.strip() or len(raw) - len(raw.lstrip()) > literal:
                continue
            literal = -1
        line = _strip_comment(raw).rstrip()
        if not line.strip() or line.strip() in ("---", "..."):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ValueError(f"tab indent on line {n}")
        ind = len(line) - len(line.lstrip())
        body = line.strip()
        if pending:
            p_ind, parent, key = pending
            pending = None
            if ind > p_ind:
                parent[key] = [] if body.startswith("- ") or body == "-" else {}
                stack.append((ind, parent[key]))
        while stack and ind < stack[-1][0]:
            stack.pop()
        if not stack or ind != stack[-1][0] and not (ind > stack[-1][0] and stack[-1][0] == -1):
            raise ValueError(f"bad indent on line {n}")
        if stack[-1][0] == -1:
            stack[-1] = (ind, root)
        node = stack[-1][1]
        if body.startswith("- ") or body == "-":
            if not isinstance(node, list):
                raise ValueError(f"list item outside a list on line {n}")
            node.append(_scalar(body[1:]))
            continue
        key, sep, rest = body.partition(":")
        if not sep or not key.strip() or isinstance(node, list) or rest[:1] not in ("", " "):
            raise ValueError(f"not a mapping entry on line {n}")
        key = _scalar(key)
        if rest.strip()[:1] in ("|", ">"):
            node[key], literal = None, ind  # multi-line text, never a Selenite setting
        elif rest.strip():
            node[key] = _scalar(rest)
        else:
            node[key] = None
            pending = (ind, node, key)
    return root


def _load_yaml(text: str):
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        pass
    try:
        from ruamel.yaml import YAML  # type: ignore  # what Hermes itself ships
    except ImportError:
        return _mini_yaml(text)  # the stdlib CLI on a host with neither library
    return YAML(typ="safe", pure=True).load(text)


def read(home: Path | None = None) -> tuple[dict, str | None]:
    """``(settings, error)``. ``error`` is None when the config was read, or a short reason."""
    home = Path(home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    path = home / "config.yaml"
    try:
        cfg = _load_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None  # no config yet: every setting is its default
    except Exception as exc:  # unreadable or not YAML
        return {}, f"{type(exc).__name__} reading {path.name}"
    node = cfg
    for key in ("plugins", "entries", PLUGIN, "settings"):
        node = node.get(key) if isinstance(node, dict) else None
    return (node if isinstance(node, dict) else {}), None


def min_confidence(settings: dict, default: float = 0.6) -> float:
    """The fake threshold, clamped to 0..1; junk, nan or inf give the default."""
    try:
        f = float(settings.get("min_confidence", default))
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):
        return default
    return min(1.0, max(0.0, f))


def apply(settings: dict, extra_seats: Iterable[str] = ()) -> None:
    """Make the classifier and the audit follow the settings. Seats given here add to the configured ones."""
    seats = [*as_list(settings.get("extra_seats")), *as_list(list(extra_seats))]
    configure(seats=seats, ceremony_phrases=as_list(settings.get("extra_ceremony")))
    _audit.FAKE_THRESHOLD = min_confidence(settings)


def mode(settings: dict) -> str:
    """fake_gate_mode, with the 0.2 "enforce" read as "ask"; "nudge" for anything else."""
    m = str(settings.get("fake_gate_mode") or "nudge").strip().lower()
    m = "ask" if m == "enforce" else m
    return m if m in ("observe", "nudge", "ask") else "nudge"
