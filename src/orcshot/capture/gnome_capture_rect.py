"""D-Bus client for the bundled orcshot-clipboard extension's
CaptureRect method - task #73's Shell-native replacement for full-
screen/active-window/last-region-repeat capture's old XDG portal round
trip (wayland_portal.request_screenshot). Region-select/window-picker/
eyedropper already moved off the portal in task #77's Shell-side
rewrite - see extension.js's own docstring and REQUIREMENTS.md for
that story.

Grabs and PNG-crops an already-known rect, then runs the *same*
Shell-native destination-picker flow (pickDestinationAsync) those
overlays use, all in one continuous Shell-side round trip - not just
the pixel grab. Two real, separate artifacts motivated this, both
confirmed live: (1) xdg-desktop-portal-gnome plays an audible camera-
shutter sound as its own built-in UI feedback whenever the portal's
Screenshot() method is invoked, which Shell.Screenshot (used here
instead) doesn't; (2) even after switching only the pixel grab (an
earlier version of this module), the old ui/destination_picker.py
Gtk.Menu popup - a real client-side window - still caused a brief
dock/taskbar flash under this Wayland session, the same class of
artifact task #76/#77 eliminated for region-select/window-picker by
moving their own destination picker Shell-side too.

Genuinely async (shell_bridge.request_async, not the blocking request()), same
reasoning as gnome_region_select.start_region_select: once the
destination choice is folded in, this is an open-ended, user-timed
wait (however long picking a destination takes), not the bounded,
non-interactive round trip an earlier version of this module assumed
call_sync was safe for.
"""

from __future__ import annotations

import sys
import traceback

import gi


from orcshot.capture.shell_bridge import ShellRequestError, ShellUnavailable, get_bridge
from orcshot.capture.gnome_region_select import decode_png
from orcshot.core.geometry import Rect

CAPABILITY = "capture-rect"


def is_available() -> bool:
    return get_bridge().has(CAPABILITY)


def start_capture_rect(rect: Rect, on_captured, on_cancelled=None) -> None:
    """Asks the Shell extension to grab+crop ``rect`` and run the
    whole destination-picker interaction on it. Returns immediately -
    ``on_captured(image, destination)`` or ``on_cancelled()`` fires
    later, once the user picks a destination or dismisses the picker
    (Escape/click-outside) - see this module's own docstring for why
    this can't be a bounded/synchronous call the way an earlier
    version of it was.
    """
    def on_result(result: dict):
        try:
            on_captured(decode_png(bytes(result["pngBytes"])), result["destination"])
        except Exception:
            print("[gnome_capture_rect] exception in on_result:", file=sys.stderr, flush=True)
            traceback.print_exc()

    def on_error(_error):
        if on_cancelled is not None:
            on_cancelled()

    try:
        get_bridge().request_async(CAPABILITY, {"x": rect.left, "y": rect.top, "width": rect.width, "height": rect.height}, on_result, on_error)
    except ShellUnavailable:
        on_error(None)
