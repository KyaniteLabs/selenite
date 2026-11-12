"""Small, optional Desktop hints shared by the agent and dashboard writers."""
import logging
import re
import sys

logger = logging.getLogger(__name__)

VIEWS = ("overview", "load", "totals", "cleanse", "gates", "fake-gates", "evolve", "signals", "ledger")
KINDS = {"gate", "calm", "audit", "cleanse", "approval", "blocked", "miss", "fp", "fix", "reopen"}
ITEM_PATTERN = r"[A-Za-z0-9_:-]{1,80}"
SETUP = ("Check that Selenite is on in Capabilities -> Plugins; enabling the pane is the one step "
         "a person does, then open the Selenite page.")


def valid_view(payload) -> bool:
    return (isinstance(payload, dict) and set(payload) <= {"view", "item_id"}
            and isinstance(payload.get("view"), str) and payload["view"] in VIEWS
            and ("item_id" not in payload or (isinstance(payload["item_id"], str)
                 and re.fullmatch(ITEM_PATTERN, payload["item_id"]) is not None)))


def broadcast(event, payload) -> None:
    """Refuse unknown fields; losing an optional event must never break a write."""
    if "tui_gateway.server" not in sys.modules:
        return  # the Hermes bridge imports the TUI server, which has process-wide stdout effects
    if not isinstance(event, str) or len(event) > 128 or not isinstance(payload, dict):
        return
    if event == "view.set":
        valid = valid_view(payload)
    elif event == "ledger.updated":
        valid = (set(payload) == {"kind"} and isinstance(payload["kind"], str)
                 and payload["kind"] in KINDS)
    elif event == "cleanse.updated":
        valid = set(payload) == {"count"} and type(payload["count"]) is int and 0 <= payload["count"] <= 1_000_000
    else:
        valid = event == "proposal.updated" and not payload
    if not valid:
        return
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
    except ImportError:
        return  # old Hermes, tests or a standalone script
    try:
        broadcast_plugin_event("selenite", event, payload)
    except Exception:
        logger.debug("selenite: Desktop event was not delivered", exc_info=True)
