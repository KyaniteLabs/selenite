"""Wave 2: redaction cost bound (S3), Desktop mark 503 on an unwritable ledger (S5), bounded lock
waits (S8) and a reduced-motion rule in the Desktop file (S9)."""
import importlib.util
import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

try:
    import fcntl
except ImportError:  # Windows: no cross-process file lock to test
    fcntl = None
from conftest import REPO, STATE, ledger  # noqa: E402
from test_fake_gate_audit_plugin import _load_plugin  # noqa: E402


# --- S3
def test_s3_redact_of_a_long_unbroken_run_is_fast():
    text = "a1" * 50000
    t0 = time.perf_counter()
    ledger.redact(text)
    assert time.perf_counter() - t0 < 0.05


def test_s3_redact_still_redacts_an_email_and_bounds_its_local_part():
    assert ledger.redact("mail ann.lee+x@example.co.uk now") == "mail <email> now"
    assert "<email>" in ledger.redact("a" * 70 + "@example.com")   # the tail is still caught


# --- S5
def _app():
    spec = importlib.util.spec_from_file_location("selenite_api_w2", REPO / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/plugins/selenite")
    return TestClient(app)


def test_s5_desktop_mark_is_503_when_the_ledger_is_not_writable(monkeypatch):
    monkeypatch.setattr(ledger, "state_dirs", lambda: [])        # no folder takes the row
    r = _app().post("/api/plugins/selenite/events", json={"kind": "fix", "key": "x"})
    assert r.status_code == 503
    assert "not writable" in r.json()["detail"]


# --- S8
def _bounded(fn, seconds=3):
    err = []

    def run():
        try:
            fn()
        except BaseException as e:  # noqa: BLE001
            err.append(e)
    t = threading.Thread(target=run, daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(seconds)
    return (not t.is_alive()), err, time.monotonic() - t0


@pytest.mark.skipif(fcntl is None, reason='no fcntl on Windows')
def test_s8_ledger_lock_gives_up_at_the_deadline(tmp_path, monkeypatch):
    fd = os.open(tmp_path / ".ledger.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(ledger, "LOCK_TIMEOUT_S", 0.2, raising=False)

        def enter():
            with ledger._Lock(tmp_path):
                pass
        done, err, _ = _bounded(enter)
        assert done and err and isinstance(err[0], TimeoutError)
    finally:
        os.close(fd)


@pytest.mark.skipif(fcntl is None, reason='no fcntl on Windows')
def test_s8_ledger_add_does_not_hang_on_a_held_lock(monkeypatch):
    STATE.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE / ".ledger.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(ledger, "LOCK_TIMEOUT_S", 0.2, raising=False)
        done, err, _ = _bounded(lambda: ledger.add("fix", "held-lock"))
        assert done and not err        # add() never raises: it moves on or returns None
    finally:
        os.close(fd)


@pytest.mark.skipif(fcntl is None, reason='no fcntl on Windows')
def test_s8_fake_gate_ledger_write_gives_up_at_the_deadline(tmp_path, monkeypatch):
    mod, _ = _load_plugin(tmp_path, monkeypatch)
    d = mod.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / ".ledger.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        monkeypatch.setattr(mod, "LEDGER_LOCK_TIMEOUT_S", 0.2, raising=False)
        done, err, _ = _bounded(lambda: mod._ledger("probe", tool="t"))
        assert done and not err        # logged, never raised into the turn
        assert not (d / "ledger.jsonl").exists()
    finally:
        os.close(fd)


# --- S9
def test_s9_desktop_file_has_a_reduced_motion_rule():
    js = (REPO / "desktop" / "plugin.js").read_text()
    assert js.count("prefers-reduced-motion") >= 1


# --- wave 3: X-SHLEX ------------------------------------------------------------------------
def test_judge_command_keeps_windows_backslash_paths():
    from antibeaurocracy_core import judge
    argv = judge.split_command(r'judge.exe --repo "C:\Program Files\x" --other C:\tmp\y', windows=True)
    assert argv == ["judge.exe", "--repo", r"C:\Program Files\x", "--other", r"C:\tmp\y"]


def test_judge_command_posix_quoting_is_unchanged():
    from antibeaurocracy_core import judge
    assert judge.split_command("judge --repo 'a b' --x \"c d\"", windows=False) == ["judge", "--repo", "a b", "--x", "c d"]
