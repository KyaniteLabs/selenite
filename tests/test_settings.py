"""The plugin, the CLI and the dashboard read one set of Selenite settings, without Hermes internals."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from antibeaurocracy_core import audit, cli, settings

C = sys.modules["antibeaurocracy_core.classify"]  # the package exports the function under the same name

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True, params=["library", "stdlib"])
def reader(request, monkeypatch):
    """Every test runs with a YAML library and again on a bare host with neither PyYAML nor ruamel."""
    if request.param == "stdlib":
        for mod in ("yaml", "ruamel", "ruamel.yaml"):
            monkeypatch.setitem(sys.modules, mod, None)  # import raises ImportError
    yield request.param
    settings.apply({})  # leave the classifier and audit at their defaults for other tests


HERMES_LIKE = """# a config shaped like the one Hermes writes
model:
  default: some-model
  prompt: |
    multi-line text: with a colon
      - and a dash
  extra: {a: 1}
plugins:
  enabled:
    - selenite
  entries:
    other: {}
    selenite:
      settings:
        fake_gate_mode: "ask"   # a comment
        min_confidence: 0.75
        extra_seats:
          - quartermaster
          - 'scribe'
        extra_ceremony: [attestation bundle, sign-off pack]
        hooks: false
"""


def test_a_hermes_shaped_config_reads_the_same_either_way(tmp_path):
    _config(tmp_path, HERMES_LIKE)
    assert settings.read(tmp_path) == ({"fake_gate_mode": "ask", "min_confidence": 0.75,
                                        "extra_seats": ["quartermaster", "scribe"],
                                        "extra_ceremony": ["attestation bundle", "sign-off pack"],
                                        "hooks": False}, None)


@pytest.mark.parametrize("bad", ["plugins:\n   b: 1\n  c: 2\n", "plugins:\n\tkey: 1\n", "plugins: 'open\n",
                                 "plugins:\n  - top\n  key: 1\n"])
def test_a_config_it_cannot_read_is_reported(tmp_path, bad):
    _config(tmp_path, bad)
    got, err = settings.read(tmp_path)
    assert got == {} and err


def test_a_list_of_mappings_elsewhere_does_not_hide_the_settings(tmp_path):
    """A real Hermes config has `custom_providers: [- name: ...]`; the stdlib reader must not give up on it."""
    _config(tmp_path, "custom_providers:\n  - name: a\n    base_url: http://x\n  - name: b\n" + HERMES_LIKE)
    got, err = settings.read(tmp_path)
    assert err is None and got["fake_gate_mode"] == "ask" and got["extra_seats"] == ["quartermaster", "scribe"]


def _config(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body)


def test_missing_config_is_defaults_not_an_error(tmp_path):
    assert settings.read(tmp_path) == ({}, None)


def test_corrupt_config_is_defaults_with_a_reason(tmp_path):
    _config(tmp_path, "plugins: [unclosed\n  : :")
    got, err = settings.read(tmp_path)
    assert got == {} and err and "config.yaml" in err and str(tmp_path) not in err


def test_wrong_shape_config_is_defaults(tmp_path):
    _config(tmp_path, "plugins: 3\n")
    assert settings.read(tmp_path) == ({}, None)


def test_settings_are_read_from_the_plugin_entry(tmp_path):
    _config(tmp_path, "plugins:\n  entries:\n    selenite:\n      settings:\n        min_confidence: 0.8\n")
    assert settings.read(tmp_path) == ({"min_confidence": 0.8}, None)


@pytest.mark.parametrize("raw,want", [(0.8, 0.8), ("0.7", 0.7), (5, 1.0), (-1, 0.0), ("junk", 0.6),
                                      (float("nan"), 0.6), (float("inf"), 0.6), (None, 0.6)])
def test_min_confidence_is_clamped(raw, want):
    assert settings.min_confidence({"min_confidence": raw}) == want


@pytest.mark.parametrize("raw,want", [("observe", "observe"), ("ENFORCE", "ask"), ("bogus", "nudge"), (None, "nudge")])
def test_mode(raw, want):
    assert settings.mode({"fake_gate_mode": raw}) == want


def _args(*argv):
    p = argparse.ArgumentParser()
    cli.add_arguments(p)
    return p.parse_args(list(argv))


def test_cli_seat_adds_to_configured_seats(tmp_path, monkeypatch, capsys):
    _config(tmp_path, "plugins:\n  entries:\n    selenite:\n      settings:\n        extra_seats: quartermaster\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert cli.handle(_args("audit", "--seat", "scribe", "--root", str(tmp_path), "--no-rules", "--counts")) == 0
    assert set(C._extra_seats) == {"quartermaster", "scribe"}


def test_cli_reads_min_confidence_and_warns_on_a_bad_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _config(tmp_path, "plugins:\n  entries:\n    selenite:\n      settings:\n        min_confidence: 0.9\n")
    cli.handle(_args("classify", "x"))
    assert audit.FAKE_THRESHOLD == 0.9
    _config(tmp_path, "plugins:\n  entries: {{{not yaml\n   bad: indent\n")
    cli.handle(_args("classify", "x"))
    assert audit.FAKE_THRESHOLD == 0.6 and "unreadable" in capsys.readouterr().err


def test_dashboard_follows_min_confidence_without_a_stale_cache(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="backend tests need FastAPI: pip install -r requirements-test.txt")
    from test_fake_gate_audit_plugin import _board
    _board(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("ab_dash_settings", ROOT / "dashboard" / "fake_gates_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = mod.overview(top=15, days=7)
    _config(tmp_path, "plugins:\n  entries:\n    selenite:\n      settings:\n"
                      "        min_confidence: 1.0\n        fake_gate_mode: observe\n")
    strict = mod.overview(top=15, days=7)  # inside the 30 s cache window, so only the settings key re-audits
    assert base["cards"] and not strict["cards"], json.dumps(strict, default=str)
    assert strict["mode"] == "observe"
