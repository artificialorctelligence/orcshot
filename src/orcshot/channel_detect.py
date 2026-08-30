"""Detecting which packaging channel this running process is inside of
(plain .deb, Flatpak, or Snap), and - for the two sandboxed channels,
which can't write to the system-wide GNOME Shell extensions path the
way .deb's own dh_install does - copying this project's bundled
extension files into the real per-user extensions path on first run.

A .deb install needs neither: dh_install already places every bundled
extension system-wide at package-install time (see
debian/orcshot.install), so detect_channel() returning "deb" is this
module's signal to the caller (ui/first_run_setup.py) to do nothing at
all - not a channel this module has any work to do for.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def detect_channel(env: dict | None = None) -> str:
    """"snap" if $SNAP/$SNAP_NAME are set (Snap's own, always-present
    env vars for a running snap); "flatpak" if $FLATPAK_ID is set or
    /.flatpak-info exists (Flatpak sets the env var for GUI apps
    launched via its own portal-aware launcher, but the file is the
    more universally-present signal - present for every Flatpak
    process regardless of launch path); "deb" otherwise. env defaults
    to os.environ, injectable for tests.
    """
    if env is None:
        env = dict(os.environ)
    if env.get("SNAP") and env.get("SNAP_NAME"):
        return "snap"
    if env.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
        return "flatpak"
    return "deb"


def install_bundled_extension_if_needed(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool:
    """Copies bundled_dir's contents to dest_parent/uuid/ if not already
    present there. Returns True on success (including the
    already-installed case, which is left untouched rather than
    overwritten), False if the copy failed - a PermissionError is the
    expected real-world failure mode (Snap's personal-files interface
    not yet connected; see channel_detect.py's own module docstring
    and the Snap channel design spec for why $SNAP_REAL_HOME, not
    $HOME, must be what the caller resolves dest_parent from).
    """
    dest = dest_parent / uuid
    if dest.exists():
        return True
    try:
        dest_parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_dir, dest)
        return True
    except OSError:
        return False
