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


def _load_yaml(text: str):
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        pass
    from ruamel.yaml import YAML  # type: ignore  # what Hermes itself ships

    return YAML(typ="safe", pure=True).load(text)


def read(home: Path | None = None) -> tuple[dict, str | None]:
    """``(settings, error)``. ``error`` is None when the config was read, or a short reason."""
    home = Path(home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    path = home / "config.yaml"
    try:
        cfg = _load_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None  # no config yet: every setting is its default
    except ImportError:
        return {}, "no YAML reader (PyYAML or ruamel.yaml) installed"
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
