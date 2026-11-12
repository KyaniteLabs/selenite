"""Every test runs against a throwaway HOME and state folder, set before any
Selenite module is imported (the modules read their paths at import time)."""
import atexit
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Permission-bit tests need a real non-root user: root ignores read-only folders. CI runs them as one.
NON_ROOT_ONLY = pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                                   reason="root ignores permission bits; needs a non-root runner")

REPO = Path(__file__).resolve().parent.parent
_HERMES_SOURCE = os.environ.get("SELENITE_TEST_HERMES_SOURCE")
if _HERMES_SOURCE and (Path(_HERMES_SOURCE) / "hermes_constants.py").is_file():
    sys.path.insert(0, _HERMES_SOURCE)
_BASE = Path(tempfile.mkdtemp(prefix="selenite-tests-"))
HOME = _BASE / "home"
STATE = _BASE / "state"
HOME.mkdir()
atexit.register(shutil.rmtree, _BASE, True)
os.environ.update(HOME=str(HOME), SELENITE_STATE=str(STATE), SELENITE_HOME=str(HOME / ".config/selenite"),
                  HERMES_HOME=str(HOME / ".hermes"))
os.environ.pop("SELENITE_HOOKS", None)
for _k in [k for k in os.environ if k.startswith("HERMES_KANBAN_")]:
    os.environ.pop(_k, None)


def _load_plugin():
    spec = importlib.util.spec_from_file_location("selenite_plugin", REPO / "__init__.py",
                                                  submodule_search_locations=[str(REPO)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["selenite_plugin"] = mod
    spec.loader.exec_module(mod)
    return mod


plugin = _load_plugin()
cleanse, ledger, signals = plugin.cleanse, plugin.ledger, plugin.signals
evolve, mine = (importlib.import_module(f"selenite_frictionless.{n}") for n in ("evolve", "mine"))


@pytest.fixture(autouse=True)
def fresh():
    """No state folder (Selenite creates its own) and an empty HOME for every test."""
    shutil.rmtree(STATE, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)
    HOME.mkdir()
    plugin._streak.clear()
    plugin._ctx = None
    plugin.cowardice._ctx = None
    plugin.cowardice._pending.clear()
    yield
