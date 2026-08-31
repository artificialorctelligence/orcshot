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

import json
import os
import shutil
import tempfile
from pathlib import Path


def detect_channel(env: dict | None = None, path_exists=os.path.exists) -> str:
    """"snap" if $SNAP/$SNAP_NAME are set (Snap's own, always-present
    env vars for a running snap); "flatpak" if $FLATPAK_ID is set or
    /.flatpak-info exists (Flatpak sets the env var for GUI apps
    launched via its own portal-aware launcher, but the file is the
    more universally-present signal - present for every Flatpak
    process regardless of launch path); "deb" otherwise. env defaults
    to os.environ, path_exists to os.path.exists - both injectable for
    tests (BACKLOG #191: a global os.path.exists monkeypatch is a
    blunter instrument than this, matching the same env-injection
    pattern this function already used).
    """
    if env is None:
        env = dict(os.environ)
    if env.get("SNAP") and env.get("SNAP_NAME"):
        return "snap"
    if env.get("FLATPAK_ID") or path_exists("/.flatpak-info"):
        return "flatpak"
    return "deb"


def _metadata_version(extension_dir: Path) -> float:
    """The version field from an extension's own metadata.json, 0 if
    the file is missing, unreadable, or carries no version field at
    all - so an extension bundled/installed before this field existed
    (orcshot-tray's own, historically) always compares as needing an
    upgrade rather than as permanently up to date."""
    try:
        return json.loads((extension_dir / "metadata.json").read_text()).get("version", 0)
    except (OSError, json.JSONDecodeError):
        return 0


def install_bundled_extension_if_needed(uuid: str, bundled_dir: Path, dest_parent: Path) -> bool:
    """Copies bundled_dir's contents to dest_parent/uuid/ if not already
    present there, or if the bundled copy's metadata.json version is
    newer than what's already installed (BACKLOG #191 - a bundled
    extension is package payload the user never edits, closer to how a
    .deb upgrade always overwrites its own shipped files, unlike user
    configuration worth preserving across upgrades). Returns True on
    success (including the already-current case, left untouched),
    False if the copy failed - a PermissionError is the expected
    real-world failure mode (Snap's personal-files interface not yet
    connected; see channel_detect.py's own module docstring and the
    Snap channel design spec for why $SNAP_REAL_HOME, not $HOME, must
    be what the caller resolves dest_parent from).

    Copies to a temp sibling and swaps it in rather than copying
    directly into dest, so a copy that fails partway (disk full,
    permission revoked mid-copy) never leaves a half-written or
    corrupted dest behind - the existing, working install (if any)
    survives an interrupted upgrade attempt untouched.
    """
    dest = dest_parent / uuid
    if dest.exists() and _metadata_version(bundled_dir) <= _metadata_version(dest):
        return True
    try:
        dest_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest_parent) as tmp:
            staged = Path(tmp) / uuid
            shutil.copytree(bundled_dir, staged)
            if dest.exists():
                # ponytail: brief non-atomic window between removing the
                # old install and moving the new one in - acceptable for
                # a low-stakes bundled JS file; upgrade to a real atomic
                # directory swap if this ever needs stronger guarantees.
                shutil.rmtree(dest)
            shutil.move(str(staged), str(dest))
        return True
    except OSError:
        return False
