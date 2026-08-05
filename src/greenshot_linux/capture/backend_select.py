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
from greenshot_linux.capture.window import WindowActivator, WindowEnumerator


def default_capture_backend() -> CaptureBackend:
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from greenshot_linux.capture.wayland import WaylandCaptureBackend

        return WaylandCaptureBackend()

    from greenshot_linux.capture.x11 import X11CaptureBackend

    return X11CaptureBackend()


def default_window_enumerator_and_activator() -> tuple[WindowEnumerator, WindowActivator | None]:
    """A None activator means the caller doesn't need one: X11's
    window-picker already gets correct content from its frozen-backdrop
    crop, with nothing to raise. Wayland has no portable window
    enumeration API at all (see capture/gnome_window_calls.py) - this
    probes for the bundled window-calls GNOME Shell extension rather
    than assuming from session/desktop name alone, since "GNOME on
    Wayland" and "GNOME on Wayland with this extension actually
    enabled" look identical from the outside otherwise.
    """
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from greenshot_linux.capture.gnome_window_calls import GnomeWindowCallsBackend, is_available

        if is_available():
            backend = GnomeWindowCallsBackend()
            return backend, backend

    from greenshot_linux.capture.x11_window import X11WindowEnumerator

    return X11WindowEnumerator(), None


def window_picker_supported() -> bool:
    """Whether "Capture Window" can work correctly right now - always
    true on X11 (the frozen-backdrop crop needs nothing extra beyond
    X11WindowEnumerator), true on Wayland only if the bundled
    window-calls extension is actually installed, enabled, and
    responding. Used to grey out the tray menu item rather than let it
    silently do nothing or show wrong content - see REQUIREMENTS.md's
    Wayland window-picker section."""
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return True

    from greenshot_linux.capture.gnome_window_calls import is_available

    return is_available()
