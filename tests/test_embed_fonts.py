"""tools/embed-fonts.py used to rewrite desktop/plugin.js on every invocation, ``--help`` included
(factory card t_883b6175, premise 2). It had no argument parser, so there was no way to ask what it
does without running it. Every test here works on a throwaway copy of the script and its output."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COPIED = ("tools/embed-fonts.py", "desktop/plugin.js", "desktop/fonts/cp-Medium.woff", "desktop/fonts/cp-SemiBold.woff")
OLD = 1_600_000_000  # 2020-09-13: far enough back that any rewrite today moves the mtime


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in COPIED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, tmp_path / rel)
    os.utime(tmp_path / "desktop/plugin.js", (OLD, OLD))
    return tmp_path


def _run(tree: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / "tools/embed-fonts.py"), *argv],
                          capture_output=True, text=True, cwd=str(tree))


def _untouched(tree: Path) -> bool:
    """Same bytes as the repo, and still stamped OLD: a rewrite would have restamped it."""
    js = tree / "desktop/plugin.js"
    return js.read_bytes() == (REPO / "desktop/plugin.js").read_bytes() and int(js.stat().st_mtime) == OLD


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_writes_nothing(tree, flag):
    proc = _run(tree, flag)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("usage: embed-fonts.py") and "FONTS markers" in proc.stdout
    assert _untouched(tree)


def test_an_unknown_argument_exits_2_and_writes_nothing(tree):
    proc = _run(tree, "--bogus")
    assert proc.returncode == 2
    assert "usage: embed-fonts.py" in proc.stderr and "unrecognized arguments: --bogus" in proc.stderr
    assert proc.stdout == ""
    assert _untouched(tree)


def test_no_arguments_still_rebuilds_the_block(tree):
    """The one run that writes: it restores a stale block to the fonts that ship in the repo."""
    js = tree / "desktop/plugin.js"
    stale, n = re.subn(r"500: '[^']*'", "500: 'STALE'", js.read_text(encoding="utf-8"))
    assert n == 1
    js.write_text(stale, encoding="utf-8")
    proc = _run(tree)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("embedded 2 weights")
    assert js.read_bytes() == (REPO / "desktop/plugin.js").read_bytes()
