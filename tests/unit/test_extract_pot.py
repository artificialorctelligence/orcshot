import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent

# extract_pot.sh is deliberately dev-only tooling (see its own
# docstring / docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md's
# "Extraction tooling" section) - not part of the packaged build, so
# it's never copied into dh_auto_test's pybuild build tree (hatchling
# only bundles the orcshot/ package itself, not scripts/). This test
# can only meaningfully run against a real source checkout.
pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "scripts" / "extract_pot.sh").exists(),
    reason="extract_pot.sh is dev-only tooling, not present in a built package tree",
)


class TestExtractPot:
    def test_the_script_produces_a_non_empty_pot_file(self):
        result = subprocess.run(
            [str(REPO_ROOT / "scripts" / "extract_pot.sh")],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        pot_path = REPO_ROOT / "po" / "orcshot.pot"
        assert pot_path.exists()
        assert pot_path.stat().st_size > 0
