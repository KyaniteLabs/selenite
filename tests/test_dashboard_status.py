"""Exercise the dashboard status route without optional HTTP/model dependencies."""
import importlib.util
import sqlite3
import sys
import types

from conftest import HOME, REPO, ledger


def _load_api(monkeypatch):
    fastapi = types.ModuleType("fastapi")

    class Router:
        def get(self, *_args, **_kwargs):
            return lambda fn: fn

        def post(self, *_args, **_kwargs):
            return lambda fn: fn

        def include_router(self, *_args, **_kwargs):
            pass

    fastapi.APIRouter = Router
    fastapi.Query = lambda default=None, **_kwargs: default
    fastapi.HTTPException = type("HTTPException", (Exception,), {"__init__": lambda self, status_code=500, detail="": Exception.__init__(self, detail)})
    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = type("BaseModel", (), {})
    pydantic.Field = lambda default=None, **_kwargs: default
    pydantic.field_validator = lambda *_args, **_kwargs: lambda fn: fn
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)
    spec = importlib.util.spec_from_file_location("selenite_status_api", REPO / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = api
    spec.loader.exec_module(api)
    return api


def test_status_reads_the_configured_kanban_home_before_marking_missing(monkeypatch):
    api = _load_api(monkeypatch)
    hermes_home = HOME / ".hermes"
    kanban_home = HOME / "shared-kanban"
    for db, has_card in ((hermes_home / "kanban.db", False), (kanban_home / "kanban.db", True)):
        db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db)
        con.execute("create table tasks (id text primary key, status text)")
        if has_card:
            con.execute("insert into tasks values ('t_live', 'blocked')")
        con.commit()
        con.close()

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(kanban_home))
    api._status_cache.update(ts=0.0, ids=())
    ledger.add("blocked", "kanban:t_live")
    assert api.status()["blocked_tasks"] == ["t_live"]
