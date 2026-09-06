"""BACKLOG #196: `debian/orcshot.user.service` had `PartOf=` and
`WantedBy=graphical-session.target` but no `After=` - neither of the
first two orders a *start* against the target, only pull-in and
stop-propagation. Live-reproduced on every real Wayland test session:
systemd started the unit racing ahead of `graphical-session.target`
actually being active, before DISPLAY/WAYLAND_DISPLAY were importable,
causing a `cannot open display` failure on first launch every time
(masked by `Restart=on-failure` succeeding 2 seconds later). This test
guards the fix - see #196's own BACKLOG entry for the live evidence.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SERVICE_FILE = REPO_ROOT / "debian" / "orcshot.user.service"

# debian/ is packaging metadata, never copied into dh_auto_test's pybuild
# build tree (same reasoning as test_extract_pot.py's own skip) - this
# test can only meaningfully run against a real source checkout.
pytestmark = pytest.mark.skipif(
    not SERVICE_FILE.exists(),
    reason="debian/ is packaging metadata, not present in a built package tree",
)


def _parse_unit_file(path: Path) -> dict:
    section = None
    parsed: dict = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            parsed.setdefault(section, {})
            continue
        if "=" in line and section is not None:
            key, _, value = line.partition("=")
            parsed[section][key.strip()] = value.strip()
    return parsed


class TestOrcshotUserServiceOrdering:
    def test_starts_after_graphical_session_target_is_reached(self):
        unit = _parse_unit_file(SERVICE_FILE)
        assert unit["Unit"]["After"] == "graphical-session.target"

    def test_still_stops_when_the_graphical_session_ends(self):
        # PartOf= alone doesn't order a start, but it's still needed for
        # correct teardown - the fix must not have dropped it.
        unit = _parse_unit_file(SERVICE_FILE)
        assert unit["Unit"]["PartOf"] == "graphical-session.target"

    def test_still_pulled_in_by_the_graphical_session(self):
        unit = _parse_unit_file(SERVICE_FILE)
        assert unit["Install"]["WantedBy"] == "graphical-session.target"
