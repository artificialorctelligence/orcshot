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

from orcshot.capture.backend import CaptureBackend
from orcshot.capture.clipboard import ClipboardBackend
from orcshot.capture.window import WindowActivator, WindowEnumerator


def default_capture_backend() -> CaptureBackend:
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from orcshot.capture.wayland import WaylandCaptureBackend

        return WaylandCaptureBackend()

    from orcshot.capture.x11 import X11CaptureBackend

    return X11CaptureBackend()


def default_clipboard_backend() -> ClipboardBackend:
    """Prefers the bundled orcshot-clipboard GNOME Shell
    extension when it's actually installed, enabled, and responding
    (probed empirically, same "never assume from session/desktop name
    alone" precedent as default_window_enumerator_and_activator) - it
    calls into St.Clipboard's privileged, Shell-side access directly,
    with no client-side focus requirement to satisfy and no brief
    window to show (see REQUIREMENTS.md's "Clipboard under Wayland"
    section). Falls back to WaylandClipboardBackend's invisible-window/
    focus-wait technique otherwise - still correct, just with its known
    window-list reflow side effect - rather than leaving clipboard
    broken outright for anyone who declined the extension in first-run
    setup or hasn't logged back in since enabling it yet.

    X11ClipboardBackend's clipboard.store() call (asks X11's
    CLIPBOARD_MANAGER to persist the data past this process/window
    going away) has no Wayland equivalent - confirmed via research,
    Wayland clipboard persistence instead relies on a separate
    clipboard-manager daemon using the wlr-data-control protocol
    extension, nothing this app has any part in. WaylandClipboardBackend
    omits that call; this app being a persistent background process
    (never exits after a capture) is what actually keeps a Wayland
    clipboard offer servable, not an explicit persistence call.
    """
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return _WaylandClipboard()

    from orcshot.capture.x11_clipboard import X11ClipboardBackend

    return X11ClipboardBackend()


class _WaylandClipboard:
    """Shell-native when the extension has said Hello, portal-style
    otherwise - decided on every call, not once at startup: Hello
    arrives asynchronously after the app owns its bus name, so a
    one-time probe here could race it and cache the wrong answer for
    the whole session (spec 2026-09-11 §3). A late Hello simply
    upgrades the next copy."""

    def __init__(self):
        from orcshot.capture.wayland_clipboard import WaylandClipboardBackend

        self._portal = WaylandClipboardBackend()

    def set_image(self, image) -> None:
        from orcshot.capture.gnome_clipboard import GnomeClipboardBackend, GnomeClipboardUnavailable, is_available

        if is_available():
            try:
                GnomeClipboardBackend().set_image(image)
                return
            except GnomeClipboardUnavailable:
                pass
        self._portal.set_image(image)


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
        from orcshot.capture.gnome_window_calls import GnomeWindowCallsBackend, is_available

        if is_available():
            backend = GnomeWindowCallsBackend()
            return backend, backend

    from orcshot.capture.x11_window import X11WindowEnumerator

    return X11WindowEnumerator(), None


def _shell_has(kind: str) -> bool:
    """One seam for both capability lookups below, so a test can answer
    them without a bridge or a bus."""
    from orcshot.capture.shell_bridge import get_bridge

    return get_bridge().has(kind)


def window_picker_supported() -> bool:
    """Whether "Capture Window" can work correctly right now.

    Always true on X11: the frozen-backdrop crop needs nothing beyond
    X11WindowEnumerator. (Strictly, that enumerator's constructor still
    raises on a window manager with no EWMH _NET_CLIENT_LIST - real
    desktops all have one, and a bare Xvfb, which does not, is not a
    session anyone captures from.)

    On Wayland, true if the bundled Shell extension offers *either*
    capability, because ui/window_picker.py's start_window_picker
    accepts either: it prefers the Shell-native "window-picker" flow and
    falls back to a plain overlay driven by "list-windows" enumeration.
    Checking only one would disable a menu item that would have worked -
    and the two can differ in practice, because the Shell may be running
    a cached older copy of the extension than the one this package ships
    (see gnome_extension_setup.bundled_version_name).

    With neither, activating the item reaches X11WindowEnumerator under
    Wayland, whose constructor raises X11WindowEnumerationUnavailable -
    which OrcshotApplication._run_capture does not catch, since it
    handles the three portal exceptions only. The click does nothing at
    all. Gating the action is what turns that into a visibly unavailable
    menu item (BACKLOG #224).
    """
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return True

    from orcshot.capture.gnome_window_calls import CAPABILITY as ENUMERATE_CAPABILITY
    from orcshot.capture.gnome_window_picker import CAPABILITY as SHELL_PICKER_CAPABILITY

    return _shell_has(SHELL_PICKER_CAPABILITY) or _shell_has(ENUMERATE_CAPABILITY)
