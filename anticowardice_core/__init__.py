"""anticowardice core: stdlib-only, deterministic detectors for the epistemic-cowardice facet.

No model call anywhere in this package. Walls are the fake-gate facet's one list (antibeaurocracy_core).
"""

from .detect import (  # noqa: F401
    CAVEAT, DEFER, HEDGE, MODES, NARROW, OVERCORRECT, READY, SYCOPHANCY, VAGUE,
    Finding, ToolCall, Turn, analyze, nudge_text,
)

__version__ = "0.6.0"
