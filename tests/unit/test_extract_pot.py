"""Guards `scripts/extract_pot.sh` and the committed `po/orcshot.pot`.

BACKLOG #204: this test used to run the script with no arguments, which wrote
straight into the committed `po/orcshot.pot`. Every `pytest` run - including
the one RELEASING.md step 2 tells you to do first - therefore left the working
tree dirty with a diff that was pure noise (a new POT-Creation-Date plus source
line-number churn), and it had to be reverted by hand twice during the 0.3.0
release to keep step 8's `git add` honest. The script now takes an optional
output path, so extraction here goes to a temp file.

That seam also lets this test assert something it never did before: that the
committed .pot is actually *current*. The old version only checked the script
exited 0 and produced a non-empty file, so a contributor could add a `_("...")`
string, never re-extract, and nothing would notice - even though TRANSLATING.md
points translators at that file as the template to work from.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "extract_pot.sh"
COMMITTED_POT = REPO_ROOT / "po" / "orcshot.pot"

# extract_pot.sh is deliberately dev-only tooling (see its own docstring /
# docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
# "Extraction tooling" section) - not part of the packaged build, so it's never
# copied into dh_auto_test's pybuild build tree (hatchling only bundles the
# orcshot/ package itself, not scripts/). This test can only meaningfully run
# against a real source checkout, with xgettext installed.
pytestmark = pytest.mark.skipif(
    not SCRIPT.exists() or shutil.which("xgettext") is None,
    reason="extract_pot.sh is dev-only tooling and needs xgettext; not present in a built package tree",
)


def _unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s.startswith('"') and s.endswith('"') else s


def _msgids(pot: Path) -> set[str]:
    """Every msgid in the file, with multi-line ones joined into one entry.

    A naive `grep '^msgid'` is not good enough: a msgid split across
    continuation lines starts as a bare `msgid ""`, so 25 distinct entries in
    this file would collapse into one indistinguishable empty string and
    changes inside them would go unnoticed.
    """
    found: set[str] = set()
    parts: list[str] = []
    collecting = False
    for raw in pot.read_text().splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            if collecting:
                found.add("".join(parts))
            collecting, parts = True, [_unquote(line[len("msgid "):])]
        elif collecting and line.startswith('"'):
            parts.append(_unquote(line))
        elif collecting:
            # msgstr, msgid_plural, a comment or a blank line all end it
            found.add("".join(parts))
            collecting, parts = False, []
    if collecting:
        found.add("".join(parts))
    return found


class TestExtractPot:
    def test_the_script_produces_a_non_empty_pot_file(self, tmp_path):
        out = tmp_path / "orcshot.pot"
        result = subprocess.run(
            [str(SCRIPT), str(out)], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert out.exists()
        assert out.stat().st_size > 0

    def test_the_script_leaves_the_committed_pot_alone(self, tmp_path):
        """The whole point of #204 - extracting must not touch the real file."""
        before = COMMITTED_POT.read_bytes()
        subprocess.run(
            [str(SCRIPT), str(tmp_path / "orcshot.pot")],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        assert COMMITTED_POT.read_bytes() == before, (
            "running extract_pot.sh with an explicit output path rewrote po/orcshot.pot"
        )

    def test_the_committed_pot_is_up_to_date(self, tmp_path):
        """Every translatable string in the source is in the committed template.

        Compares msgids only, deliberately: POT-Creation-Date and the `#:`
        source-line references change on every extraction and mean nothing to a
        translator, so comparing whole files would fail constantly for no
        reason.
        """
        out = tmp_path / "orcshot.pot"
        subprocess.run(
            [str(SCRIPT), str(out)],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        fresh, committed = _msgids(out), _msgids(COMMITTED_POT)
        missing = fresh - committed
        stale = committed - fresh
        assert not missing, (
            f"po/orcshot.pot is out of date - re-run scripts/extract_pot.sh. "
            f"Strings in the source but not the template: {sorted(missing)[:5]}"
        )
        assert not stale, (
            f"po/orcshot.pot has strings no longer in the source - re-run "
            f"scripts/extract_pot.sh. Examples: {sorted(stale)[:5]}"
        )
