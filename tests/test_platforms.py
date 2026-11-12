"""S2: the catalog entry lists macOS, and the README says how it runs there."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_catalog_lists_linux_and_macos_but_not_windows():
    entry = (REPO / "catalog" / "selenite.yaml").read_text(encoding="utf-8")
    platforms = re.search(r"^platforms: \[([^\]]*)\]", entry, re.M)
    assert platforms, "catalog/selenite.yaml has no platforms line"
    names = {p.strip() for p in platforms.group(1).split(",")}
    assert names == {"linux", "macos"}, names  # install.sh is POSIX sh: Windows stays out


def test_readme_has_a_macos_note():
    assert "macOS" in (REPO / "README.md").read_text(encoding="utf-8")
