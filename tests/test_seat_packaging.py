"""Packaging in the environment Selenite is built for: an agent seat whose home
is read-only. These four defects only show up there, so the fixtures make the
write fail the way a read-only filesystem does (EROFS) instead of assuming the
machine has a read-only mount to test against.

D1 cleanse.py: the report write falls through the state folders and, when none
   takes it, prints one line instead of a traceback and keeps the findings.
D2 install.sh: a read-only or broken target is skipped, every other target is
   still attempted, and the last line is the count.
D3 install.sh --hermes: one Selenite per machine. An existing install is reused
   and a link to a second checkout is repointed, so Hermes never sees two
   plugin sources with the same name.
D4 install.sh --hermes: the Hermes CLI step (which may first complete a code
   update) can neither block nor fail the install, and --no-enable skips it.
"""
import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, cleanse, ledger

INSTALL = REPO / "install.sh"


def deny_writes(monkeypatch, *roots) -> None:
    """Make every write under *roots* fail with EROFS, as a read-only home does.

    chmod only stops a normal user (root ignores permission bits, and CI runs
    as root in a container), so the syscall itself raises the same OSError the
    kernel returns on a read-only filesystem.
    """
    prefixes = tuple(str(r) for r in roots)

    def guard(path) -> None:
        text = str(path)
        if any(text == p or text.startswith(p + os.sep) for p in prefixes):
            raise OSError(errno.EROFS, os.strerror(errno.EROFS), text)

    real_open, real_mkdir = os.open, Path.mkdir

    def open_(path, *a, **kw):
        guard(path)
        return real_open(path, *a, **kw)

    def mkdir_(self, *a, **kw):
        guard(self)
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(os, "open", open_)
    monkeypatch.setattr(Path, "mkdir", mkdir_)


def _install(home: Path, *args, path="/usr/bin:/bin"):
    """Run the installer with a clean environment, so no seat variable leaks in."""
    env = {"HOME": str(home), "PATH": path, "SELENITE_STATE": str(home / "state")}
    return subprocess.run(["sh", str(INSTALL), *args], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=120)


def _last_line(text: str) -> str:
    return text.strip().splitlines()[-1]


# --- D1: cleanse.py, read-only state folder ---------------------------------

def test_cleanse_falls_back_to_a_writable_state_folder(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / ".local/state").mkdir(parents=True)
    monkeypatch.setattr(ledger, "STATE", home / ".local/state/selenite")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    deny_writes(monkeypatch, home)  # the seat: home cannot be written
    monkeypatch.setattr(sys, "argv", ["cleanse"])

    assert cleanse.main() == 0

    out, err = capsys.readouterr()
    assert out.startswith("Selenite cleanse:")
    assert "Traceback" not in err and "Read-only file system" not in err
    written = list((tmp_path / "hermes/plugin-data/selenite").glob("cleanse-*.json"))
    assert len(written) == 1, err
    assert str(written[0]) in err  # the report line points at the folder that took it


def test_cleanse_prints_the_findings_when_no_state_folder_takes_the_write(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    (home / ".local/state").mkdir(parents=True)
    monkeypatch.setattr(ledger, "STATE", home / ".local/state/selenite")
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))  # also read-only: inside the home
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    deny_writes(monkeypatch, home, Path.home())  # the last candidate is the real (test) HOME
    monkeypatch.setattr(sys, "argv", ["cleanse"])

    assert cleanse.main() == 0

    out, err = capsys.readouterr()
    assert out.startswith("Selenite cleanse:")
    assert "state dir not writable, set SELENITE_STATE" in err
    assert "Traceback" not in err


def test_ledger_add_gives_up_quietly_when_every_state_folder_is_read_only(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local/state").mkdir(parents=True)
    monkeypatch.setattr(ledger, "STATE", home / ".local/state/selenite")
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    deny_writes(monkeypatch, home, Path.home())

    assert ledger.add("gate", "no-room") is None  # a hook must never fail the agent's turn


# --- D2: install.sh, read-only and broken targets ---------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits; a read-only home needs a non-root runner")
def test_install_skips_a_read_only_target_and_keeps_going(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".codex").mkdir()
    os.chmod(home / ".claude", 0o500)
    try:
        done = _install(home)
    finally:
        os.chmod(home / ".claude", 0o700)

    assert done.returncode == 0, done.stderr
    assert "read-only" in done.stdout
    assert not (home / ".claude/skills").exists()
    assert (home / ".codex/skills/frictionless").is_symlink()  # the run did not stop at the first target
    assert _last_line(done.stdout).startswith("Selenite install: ")
    assert _last_line(done.stdout).endswith("0 failed.")


def test_install_continues_past_a_failed_link_and_exits_only_at_the_end(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/skills").write_text("a file where the folder should be\n")

    done = _install(home)

    assert done.returncode == 1
    assert "FAIL " in done.stderr and "Could not link:" in done.stderr
    assert (home / ".local/bin/antibeaurocracy").is_symlink()  # work after the failure still ran
    assert _last_line(done.stdout).startswith("Selenite install: ")
    assert "(0 read-only), 3 failed." in done.stdout


# --- D3: one Selenite per machine -------------------------------------------

def test_install_reuses_the_installed_copy_instead_of_a_second_source(tmp_path):
    home = tmp_path / "home"
    installed = home / ".local/share/selenite"
    installed.mkdir(parents=True)
    (installed / "plugin.yaml").write_text("name: selenite\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / "plugin.yaml").write_text("name: selenite\n")
    (home / ".hermes/plugins").mkdir(parents=True)
    (home / ".hermes/plugins/selenite").symlink_to(other)  # the second checkout the dogfood found

    done = _install(home, "--hermes", "--no-enable")

    assert done.returncode == 0, done.stderr
    assert f"reuse {installed}" in done.stdout  # both paths named
    assert "second source breaks Hermes admission" in done.stdout
    assert (home / ".hermes/plugins/selenite").resolve() == installed.resolve()
    assert str(other) not in (home / ".hermes/plugins/selenite").readlink().parent.as_posix()


def test_install_links_a_first_copy_without_naming_a_reuse(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)

    done = _install(home, "--hermes", "--no-enable")

    assert done.returncode == 0, done.stderr
    assert "reuse " not in done.stdout
    assert (home / ".hermes/plugins/selenite").resolve() == REPO.resolve()


# --- D4: the Hermes CLI step is not on the critical path ---------------------

def test_a_failing_hermes_enable_leaves_the_install_intact(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "hermes"
    shim.write_text("#!/bin/sh\necho 'hermes: completing a code update' >&2\nexit 1\n")  # the update that ate 120s
    shim.chmod(0o755)

    done = _install(home, "--hermes", path=f"{bin_dir}:/usr/bin:/bin")

    assert done.returncode == 0, done.stderr
    assert (home / ".hermes/plugins/selenite").is_symlink()
    assert "nothing else in this install depends on it" in done.stderr
    assert "hermes plugins enable selenite" in done.stderr  # the command stays recoverable
    assert _last_line(done.stdout).startswith("Selenite install: ")


def test_no_enable_never_calls_the_hermes_cli(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "hermes-was-run"
    shim = bin_dir / "hermes"
    shim.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    shim.chmod(0o755)

    done = _install(home, "--hermes", "--no-enable", path=f"{bin_dir}:/usr/bin:/bin")

    assert done.returncode == 0, done.stderr
    assert not marker.exists()
    assert "enable: skipped (--no-enable)" in done.stdout
    assert _last_line(done.stdout).startswith("Selenite install: ")


def test_pyproject_does_not_make_hermes_ask_for_dependency_consent():
    """A [build-system] table reads to Hermes as 'installs Python packages', so a
    headless `hermes plugins install` stops at a consent question and stays disabled."""
    tomllib = pytest.importorskip("tomllib")  # 3.11+; the 3.10 CI leg skips
    doc = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert "build-system" not in doc
    assert doc["project"]["dependencies"] == []
    assert not doc["project"].get("optional-dependencies") and "dependency-groups" not in doc
