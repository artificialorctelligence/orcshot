"""The i18n regression guard (i18n phase 1) - fails if any in-scope
file has a string literal reaching a known GTK/Gio text-setting sink
without going through _()/ngettext(), per the sink list in
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md.
Runs as a normal part of the suite, so it's already enforced everywhere
pytest already runs, including debian/rules' own override_dh_auto_test
at package-build time - no new CI/packaging wiring needed.
"""

from pathlib import Path

from tests.unit._i18n_scan import scan_source

_REPO_ROOT = Path(__file__).parent.parent.parent
_IN_SCOPE_FILES = sorted((_REPO_ROOT / "src" / "orcshot" / "ui").glob("*.py")) + [
    _REPO_ROOT / "src" / "orcshot" / "app.py",
]


class TestI18nCoverage:
    def test_no_unwrapped_user_facing_strings_remain(self):
        all_violations = []
        for path in _IN_SCOPE_FILES:
            for violation in scan_source(path.read_text(), filename=str(path)):
                all_violations.append(f"{path.relative_to(_REPO_ROOT)}:{violation.line}: {violation.message}")
        assert all_violations == [], "\n".join(all_violations)
