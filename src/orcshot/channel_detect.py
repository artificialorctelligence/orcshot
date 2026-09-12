"""Detecting which packaging channel this running process is inside of
(plain .deb, Flatpak, or Snap). ui/extension_install.py turns that,
plus the desktop, into how the GNOME Shell extension / Cinnamon applet
reaches the user - never by this app writing into the home directory
(spec 2026-09-11). This module used to also do that copying; it does
not any more.
"""

from __future__ import annotations

import os


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
