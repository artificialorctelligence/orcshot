"""The i18n regression guard (i18n phase 1) - fails if any in-scope
file has a string literal reaching a known GTK/Gio text-setting sink
without going through _()/ngettext(), per the sink list in
docs/superpowers/specs/2026-08-23-i18n-phase1-gettext-infrastructure-design.md.
Runs as a normal part of the suite, so it's already enforced everywhere
pytest already runs, including debian/rules' own override_dh_auto_test
at package-build time - no new CI/packaging wiring needed.
"""

from pathlib import Path

import orcshot

from tests.unit._i18n_scan import scan_source

# Resolved from the installed orcshot package's own location, not a
# hardcoded src/orcshot path relative to this test file - same reason
# resources.py's RESOURCES_DIR does this: dh_auto_test runs pytest
# against pybuild's build tree, where hatchling has already flattened
# src/orcshot/ down to a plain orcshot/ package (the src/ layout is a
# source-tree convention, not part of the built distribution), so a
# path relative to this test file's own position in the source tree
# doesn't exist there. Resolving via orcshot.__file__ finds the real
# package directory correctly in a dev checkout, a pybuild build tree,
# or an installed .deb alike.
_PACKAGE_ROOT = Path(orcshot.__file__).parent
_IN_SCOPE_FILES = sorted((_PACKAGE_ROOT / "ui").glob("*.py")) + [
    _PACKAGE_ROOT / "app.py",
]


class TestI18nCoverage:
    def test_no_unwrapped_user_facing_strings_remain(self):
        all_violations = []
        for path in _IN_SCOPE_FILES:
            for violation in scan_source(path.read_text(), filename=str(path)):
                all_violations.append(f"{path.relative_to(_PACKAGE_ROOT)}:{violation.line}: {violation.message}")
        assert all_violations == [], "\n".join(all_violations)
