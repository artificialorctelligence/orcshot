"""BACKLOG #203: `debian/orcshot.config` and `debian/orcshot.postinst` both
pick a user by walking `loginctl list-users` and taking the first one with a
graphical (wayland/x11) session. Neither filtered out system accounts, so on a
machine sitting at the login screen the display manager's own greeter - `gdm`,
which has a real uid, a real wayland session and a real session bus - matched
first and won.

Live-observed on the Ubuntu 24.04 VM during the 0.3.0 release (2026-09-07):
installing the .deb with nobody logged in left `/usr/bin/python3
/usr/bin/orcshot` running as the `gdm` user, and `orcshot.service` enabled for
that account persistently. The real account's own unit was correctly enabled
but inactive, so the intended behavior worked - it just also fired for the
greeter.

The `break` after the first graphical session is deliberate and stays (see
orcshot.config's own comment about fast user switching); the bug was only ever
that a greeter could be the one it stopped at.

These are static assertions on shell source, the same approach and for the same
reason as test_orcshot_user_service.py: debian/ is packaging metadata and these
scripts can't be executed standalone (both source /usr/share/debconf/confmodule,
which re-execs outside a real dpkg run). The behavioral proof is a real install
on a real VM in three states - at the login screen, logged in, and both at once.
This test exists to stop the guard being silently dropped later.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
CONFIG = REPO_ROOT / "debian" / "orcshot.config"
POSTINST = REPO_ROOT / "debian" / "orcshot.postinst"

pytestmark = pytest.mark.skipif(
    not CONFIG.exists() or not POSTINST.exists(),
    reason="debian/ is packaging metadata, not present in a built package tree",
)

SCRIPTS_THAT_PICK_A_SESSION = pytest.mark.parametrize(
    "script", [pytest.param(CONFIG, id="config"), pytest.param(POSTINST, id="postinst")]
)


@SCRIPTS_THAT_PICK_A_SESSION
def test_reads_uid_min_from_login_defs(script: Path):
    """The threshold must come from /etc/login.defs, not be assumed."""
    text = script.read_text()
    assert "UID_MIN" in text, f"{script.name} does not consult UID_MIN"
    assert "/etc/login.defs" in text, f"{script.name} does not read /etc/login.defs"


@SCRIPTS_THAT_PICK_A_SESSION
def test_skips_uids_below_uid_min(script: Path):
    """Every candidate uid is compared against the threshold and skipped when
    below it - this is what keeps gdm/lightdm/sddm out."""
    text = script.read_text()
    guard = re.search(
        r'\[\s*"\$uid"\s*-ge\s*"\$uid_min"\s*\]\s*(2>/dev/null\s*)?\|\|\s*continue', text
    )
    assert guard, f"{script.name} has no uid_min guard on each candidate uid"


@SCRIPTS_THAT_PICK_A_SESSION
def test_falls_back_when_login_defs_has_no_uid_min(script: Path):
    """A missing or UID_MIN-less /etc/login.defs must not make the guard
    compare against an empty string, which would be a shell syntax error under
    `set -e` and abort the install."""
    text = script.read_text()
    assert re.search(r'uid_min=1000', text), (
        f"{script.name} has no literal 1000 fallback for uid_min"
    )


def test_postinst_missing_bus_skips_only_that_user():
    """A user with no session bus socket must be skipped, not abort the whole
    search. `|| break` here meant one such user hid every user after them."""
    text = POSTINST.read_text()
    assert re.search(r'\[\s*-S\s*"\$bus"\s*\]\s*\|\|\s*continue', text), (
        "postinst still aborts the loop when a session bus socket is missing"
    )
