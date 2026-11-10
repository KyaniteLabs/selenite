"""Regressions for the 2026-11-10 growth-comms dogfood findings (D1-D4).

D1/D2: install.sh must survive an unwritable agent dir, link the others, and
       exit nonzero with a FAIL summary instead of aborting silently.
D3:   cleanse.py must not traceback on an unwritable state folder; it prints
       the findings, hints SELENITE_STATE, and exits 2.
D4:   the classifier must not misroute real walls to F6: catalog/marketplace
       entries are publishing walls, and "needs the CEO to approve" is a
       person's approval.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from antibeaurocracy_core import FAKE, HUMAN, WALL, classify

ROOT = Path(__file__).resolve().parent.parent


def test_catalog_entry_is_a_publishing_wall():
    v = classify("Needs Simon to approve the catalog entry before we submit")
    assert v.cls == WALL
    assert v.subtype == "publish"
    assert v.confidence >= 0.9


def test_marketplace_submission_is_a_publishing_wall():
    v = classify("Blocked until we submit the marketplace listing")
    assert v.cls == WALL
    assert v.subtype == "publish"


def test_role_to_approve_is_a_person():
    v = classify("Needs the CEO to approve the copy change")
    assert v.cls == HUMAN
    assert v.confidence >= 0.7


def test_waiting_on_owner_to_sign_off_is_a_person():
    v = classify("Waiting on the owner to sign off on the pricing page")
    assert v.cls == HUMAN


def test_ordinary_wait_stays_stale_not_wall():
    v = classify("Waiting on the build to finish before we can test")
    assert v.cls == FAKE  # still the low-confidence stale default, never a wall
    assert v.confidence < 0.6  # below the action threshold


def test_product_name_is_not_a_person():
    # "Sol" is a model, not a person: proper names must not match the role list.
    v = classify("Waiting on Sol to finish the render")
    assert v.cls != HUMAN


def _run_install(home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(ROOT / "install.sh")],
        env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True, timeout=120,
    )


def test_install_survives_readonly_agent_dir(tmp_path):
    home = tmp_path / "home"
    (home / ".codex" / "skills").mkdir(parents=True)
    ro = home / ".claude" / "skills"
    ro.mkdir(parents=True)
    ro.chmod(0o555)  # like a read-only mount: the dir exists but refuses links
    res = _run_install(home)
    if os.access(ro, os.W_OK):  # e.g. tests running as root
        pytest.skip("cannot simulate a read-only dir as root")
    assert "FAIL" in res.stderr
    assert "failure(s)" in res.stderr
    assert res.returncode == 1, "a partial install must not exit 0"
    assert (home / ".codex" / "skills" / "frictionless").is_symlink(), \
        "one bad agent dir must not stop the others (D2)"


def test_install_clean_home_exits_zero(tmp_path):
    home = tmp_path / "home2"
    (home / ".codex").mkdir(parents=True)
    res = _run_install(home)
    assert res.returncode == 0
    assert (home / ".local" / "bin" / "antibeaurocracy").is_symlink()


def test_cleanse_reports_unwritable_state_without_traceback(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so the state dir cannot be created")
    state = blocker / "state"  # NotADirectoryError is an OSError
    monkeypatch.setenv("SELENITE_STATE", str(state))
    monkeypatch.setattr(sys, "argv", ["cleanse.py"])
    from skills.frictionless.scripts import cleanse
    rc = cleanse.main()
    out = capsys.readouterr()
    assert rc == 2
    assert "SELENITE_STATE" in out.err
    assert "Traceback" not in out.err
    assert "finding(s)" in out.out, "the run is not wasted: findings still print (D3)"
