"""antibeaurocracy core: stdlib-only classifier and read-only auditor shared by the CLI and the Hermes plugin."""

from .classify import (  # noqa: F401
    ACK, ACTIONS, CEREMONY, DEPENDENCY, FAKE, HUMAN, LIMBO, MACHINERY, PARKING, RELAY, STALE, WALL,
    Verdict, classify, configure,
)

__version__ = "0.5.0"
