import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


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
