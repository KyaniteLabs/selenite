"""The CLI's help must describe the CLI it ships.

``cli.py`` line 1 once named a ``rules`` subcommand that argparse never implemented
(factory card t_883b6175, premise 1). The rule files were never a subcommand: they
are ``audit --rules`` / ``--no-rules``.
"""
import re
import subprocess
import sys
from pathlib import Path

from antibeaurocracy_core import cli

REPO = Path(__file__).resolve().parent.parent


def _cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "bin/antibeaurocracy"), *argv],
                          capture_output=True, text=True, cwd=str(REPO))


def _offered() -> list[str]:
    """The subcommands ``--help`` offers, read from its usage line."""
    proc = _cli("--help")
    assert proc.returncode == 0, proc.stderr
    (usage,) = [line for line in proc.stdout.splitlines() if line.startswith("usage:")]
    (choices,) = re.findall(r"\{([^{}]+)\}", usage)
    return choices.split(",")


def test_the_docstring_names_the_subcommands_that_exist() -> None:
    (named,) = re.findall(r"``antibeaurocracy ([^`]+)``", cli.__doc__)
    assert named.split("|") == _offered() == ["classify", "audit"]


def test_help_does_not_offer_rules_and_rules_still_fails() -> None:
    proc = _cli("--help")
    assert proc.returncode == 0 and "rules" not in proc.stdout
    proc = _cli("rules")
    assert proc.returncode == 2 and "invalid choice: 'rules'" in proc.stderr


def test_rule_files_stay_on_audit() -> None:
    proc = _cli("audit", "--help")
    assert proc.returncode == 0 and "--rules RULES" in proc.stdout and "--no-rules" in proc.stdout
