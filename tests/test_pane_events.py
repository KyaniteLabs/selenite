"""Agent-to-Desktop events carry bounded hints, never private ledger/report text."""
import json
import os
import sys
from types import ModuleType

import pytest

from conftest import cleanse, evolve, ledger, plugin


@pytest.fixture
def bridge(monkeypatch):
    calls = []
    events = ModuleType("hermes_cli.plugin_events")
    events.broadcast_plugin_event = lambda *args: calls.append(args)
    monkeypatch.setitem(sys.modules, "hermes_cli", ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", events)
    monkeypatch.setitem(sys.modules, "tui_gateway", ModuleType("tui_gateway"))
    monkeypatch.setitem(sys.modules, "tui_gateway.server", ModuleType("tui_gateway.server"))
    return calls


def test_ledger_tool_emits_kind_without_key_or_note(bridge):
    out = json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "private-key",
                                           "note": "private text /home/example/session"}))
    assert out["success"]
    assert bridge == [("selenite", "ledger.updated", {"kind": "gate"})]
    plugin.selenite_ledger({"action": "summary"})
    assert len(bridge) == 1


def test_cleanse_tool_emits_count_not_findings(bridge, monkeypatch):
    report = {"findings": [{"problem": "private text", "where": "/home/example/skill"}], "by_stone": {"skill": 1}}
    monkeypatch.setattr(cleanse, "run", lambda days: report)
    assert json.loads(plugin.selenite_ledger({"action": "cleanse"}))["success"]
    assert bridge == [("selenite", "cleanse.updated", {"count": 1})]


def test_proposal_write_emits_no_filename_or_text(bridge):
    assert evolve.build() is not None
    assert bridge == [("selenite", "proposal.updated", {})]


def test_failed_or_read_only_calls_do_not_emit(bridge, monkeypatch):
    assert not json.loads(plugin.selenite_ledger({"action": "add", "kind": "bad", "key": "x"}))["success"]
    monkeypatch.setattr(ledger, "state_dirs", lambda: [])
    assert not json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "x"}))["success"]
    assert cleanse.write({"findings": []}) is None
    assert bridge == []


@pytest.mark.parametrize("view", ["overview", "load", "totals", "cleanse", "gates", "fake-gates", "evolve", "signals", "ledger"])
def test_show_real_sections(bridge, view):
    out = plugin.selenite_show({"view": view})
    assert view in out and "open and enabled" in out
    assert bridge == [("selenite", "view.set", {"view": view})]


def test_show_focuses_a_short_item_id(bridge):
    assert "kanban:t_1" in plugin.selenite_show({"view": "ledger", "item_id": "kanban:t_1"})
    assert bridge == [("selenite", "view.set", {"view": "ledger", "item_id": "kanban:t_1"})]


@pytest.mark.parametrize("args", [None, [], {}, {"view": "unknown"}, {"view": []}, {"view": "x" * 1000},
    {"view": "gates", "item_id": ""}, {"view": "gates", "item_id": "x" * 81},
    {"view": "ledger", "item_id": "/home/example/private"}, {"view": "ledger", "item_id": "a\nb"},
    {"view": "gates", "item_id": 3}, {"view": "gates", "note": "private"}])
def test_show_rejects_invalid_inputs_without_broadcast(bridge, args):
    assert plugin.selenite_show(args).startswith("Error:")
    assert bridge == []


def test_tools_and_import_work_without_hermes(monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", None)
    from conftest import _load_plugin
    offline = _load_plugin()
    assert json.loads(offline.selenite_ledger({"action": "add", "kind": "gate", "key": "login"}))["success"]
    assert "open and enabled" in offline.selenite_show({"view": "overview"})


def test_broken_bridge_never_breaks_a_write_or_show(bridge, monkeypatch):
    def broken(*args):
        raise RuntimeError("transport down")
    monkeypatch.setattr(sys.modules["hermes_cli.plugin_events"], "broadcast_plugin_event", broken)
    assert json.loads(plugin.selenite_ledger({"action": "add", "kind": "gate", "key": "login"}))["success"]
    assert "open and enabled" in plugin.selenite_show({"view": "gates"})


@pytest.mark.parametrize("event,payload", [("unknown", {}), ("../view.set", {}), ("x" * 129, {}),
    ("ledger.updated", {"kind": "unknown"}), ("ledger.updated", {"kind": "gate", "note": "private"}),
    ("cleanse.updated", {"count": -1}), ("cleanse.updated", {"count": True}),
    ("cleanse.updated", {"count": 1_000_001}), ("proposal.updated", {"text": "private"}),
    ("view.set", {"view": "unknown"}), ("view.set", [])])
def test_event_helper_rejects_unbounded_or_unknown_payloads(bridge, event, payload):
    plugin.pane.broadcast(event, payload)
    assert bridge == []


def test_status_explains_the_persons_enable_step(bridge):
    out = plugin.frictionless_command("status")
    assert "Capabilities -> Plugins" in out and "person" in out and "enabl" in out
    assert bridge == []


@pytest.mark.skipif(not os.environ.get("SELENITE_TEST_HERMES_SOURCE"),
                    reason="real Hermes source is not configured")
def test_broadcast_does_not_load_tui_server_or_replace_stdout():
    import importlib.util
    import hermes_cli.plugin_events  # real Hermes v0.23.0 bridge, never a stub

    pytest.importorskip("ruamel.yaml")
    try:
        available = importlib.util.find_spec("tui_gateway.server") is not None
    except ModuleNotFoundError:
        available = False
    if not available:
        pytest.skip("real tui_gateway source is not installed with this Hermes snapshot")
    assert "tui_gateway.server" not in sys.modules
    stdout = sys.stdout
    plugin.pane.broadcast("ledger.updated", {"kind": "audit"})
    assert sys.stdout is stdout
    assert "tui_gateway.server" not in sys.modules
