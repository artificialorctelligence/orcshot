"""Picks the right CaptureBackend for the current session.

This has to be decided upfront, not "try X11 and fall back on
failure": confirmed live (Ubuntu 26.04/GNOME) that a direct
root-window read doesn't fail or raise under native Wayland, it
silently returns a fully black image - the compositor's capture
boundary looks like success, not an error, so there's nothing to
catch. XDG_SESSION_TYPE is the standard env var every major compositor
(GNOME, KDE, Cinnamon, etc.) sets to say which protocol is actually in
use for the current session - checked once here rather than
duplicated at each of this app's four capture call sites.
"""

from __future__ import annotations

import os

from greenshot_linux.capture.backend import CaptureBackend


def default_capture_backend() -> CaptureBackend:
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from greenshot_linux.capture.wayland import WaylandCaptureBackend

        return WaylandCaptureBackend()

    from greenshot_linux.capture.x11 import X11CaptureBackend

    return X11CaptureBackend()
