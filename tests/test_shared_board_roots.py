"""Audit surfaces must follow Hermes' shared Kanban resolver, not the active profile."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from conftest import REPO

from antibeaurocracy_core import audit
from antibeaurocracy_core import plugin as core_plugin


def _dashboard_api(monkeypatch):
    fastapi = ModuleType("fastapi")
    class Router:
        def get(self, *_args, **_kwargs):
            return lambda fn: fn
    fastapi.APIRouter = Router
    fastapi.Query = lambda default, **_kwargs: default
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    path = REPO / "dashboard" / "fake_gates_api.py"
    spec = importlib.util.spec_from_file_location("selenite_test_fake_gates_api", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_tool_uses_shared_kanban_resolver(monkeypatch, tmp_path):
    shared_db = tmp_path / "shared" / "kanban.db"
    shared_db.parent.mkdir()
    shared_db.touch()
    seen = []
    monkeypatch.setattr(core_plugin, "_kanban_dbs", lambda board: [shared_db])
    monkeypatch.setattr(core_plugin, "_hermes_home", lambda: tmp_path / "active-profile")
    monkeypatch.setattr(audit, "audit_board", lambda db: seen.append(Path(db)) or {"statuses": {}})
    monkeypatch.setattr(audit, "find_boards", lambda roots: [])

    core_plugin._boards()
    assert seen == [shared_db]


def test_dispatch_snapshot_uses_shared_kanban_resolver(monkeypatch, tmp_path):
    shared_db = tmp_path / "shared" / "kanban.db"
    shared_db.parent.mkdir()
    shared_db.touch()
    active_profile = tmp_path / "profiles" / "worker"
    active_profile.mkdir(parents=True)
    monkeypatch.setattr(core_plugin, "_kanban_dbs", lambda board: [shared_db])
    monkeypatch.setattr(audit, "audit_board", lambda db: {"statuses": {"blocked": 1}})
    monkeypatch.setattr(audit, "find_boards", lambda roots: [])

    snapshot = core_plugin._snapshot(active_profile)

    assert snapshot["summary"]["blocked"] == 1
    stored = json.loads((active_profile / "plugin-data" / "antibeaurocracy" / "snapshot.json").read_text())
    assert stored["summary"]["blocked"] == 1


def test_dashboard_uses_shared_boards_and_keys_cache_by_locations(monkeypatch, tmp_path):
    api = _dashboard_api(monkeypatch)
    active_profile = tmp_path / "profiles" / "worker"
    active_profile.mkdir(parents=True)
    monkeypatch.setattr(api, "_home", lambda: active_profile)

    audit_calls = []
    audit_api = SimpleNamespace(
        audit_board=lambda db: audit_calls.append(Path(db)) or {"statuses": {"blocked": 1}}
    )
    core = ModuleType("selenite_test_dashboard_core")
    core.__path__ = []
    core.__name__ = "selenite_test_dashboard_core"
    core.audit = audit_api
    board_module = ModuleType("selenite_test_dashboard_core.plugin")
    first = tmp_path / "shared-a" / "kanban.db"
    second = tmp_path / "shared-b" / "kanban.db"
    locations = [first]
    locations[0].parent.mkdir()
    locations[0].touch()
    board_module._kanban_dbs = lambda board: list(locations)
    monkeypatch.setitem(sys.modules, core.__name__, core)
    monkeypatch.setitem(sys.modules, board_module.__name__, board_module)
    monkeypatch.setattr(api, "_core", lambda: core)

    assert api._boards({})[0]["statuses"]["blocked"] == 1
    locations[0].unlink()
    locations[0].parent.rmdir()
    locations[:] = [second]
    locations[0].parent.mkdir()
    locations[0].touch()
    assert api._boards({})[0]["statuses"]["blocked"] == 1
    assert audit_calls == [first, second]


@pytest.mark.skipif(not os.environ.get("SELENITE_TEST_HERMES_SOURCE"),
                    reason="real Hermes source is not configured")
def test_profile_override_keeps_shared_board_resolution_on_real_hermes(tmp_path):
    from hermes_constants import (
        get_default_hermes_root,
        get_hermes_home,
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    profile = tmp_path / "profiles" / "worker"
    token = set_hermes_home_override(profile)
    try:
        assert get_hermes_home() == profile
        expected = get_default_hermes_root() / "kanban.db"
        assert expected in core_plugin._kanban_dbs(None)
    finally:
        reset_hermes_home_override(token)
