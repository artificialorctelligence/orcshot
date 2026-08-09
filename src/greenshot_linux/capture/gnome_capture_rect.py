"""D-Bus client for the bundled greenshot-linux-clipboard extension's
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

Genuinely async (Gio.DBusConnection.call(), not call_sync), same
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

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from greenshot_linux.capture.gnome_clipboard import BUS_NAME
from greenshot_linux.capture.gnome_region_select import decode_png
from greenshot_linux.core.geometry import Rect

OBJECT_PATH = "/org/gnome/Shell/Extensions/GreenshotCapture"
INTERFACE = "org.gnome.Shell.Extensions.GreenshotCapture"


def is_available() -> bool:
    from greenshot_linux.capture.gnome_clipboard import is_available as clipboard_is_available

    # Same bundled extension/object as gnome_clipboard.py/gnome_region_
    # select.py, just a different method on the same interface - Ping()
    # answering for one confirms all three are present, since they're
    # exported together by extension.js's own enable().
    return clipboard_is_available()


def start_capture_rect(rect: Rect, on_captured, on_cancelled=None) -> None:
    """Asks the Shell extension to grab+crop ``rect`` and run the
    whole destination-picker interaction on it. Returns immediately -
    ``on_captured(image, destination)`` or ``on_cancelled()`` fires
    later, once the user picks a destination or dismisses the picker
    (Escape/click-outside) - see this module's own docstring for why
    this can't be a bounded/synchronous call the way an earlier
    version of it was.
    """
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def on_reply(connection, result, _user_data=None):
        # PyGObject async D-Bus callbacks can swallow exceptions
        # silently depending on context (same caveat gnome_region_
        # select.py's own on_reply documents) - print a full traceback
        # rather than lose it.
        try:
            try:
                reply = connection.call_finish(result)
            except GLib.Error:
                if on_cancelled is not None:
                    on_cancelled()
                return
            ok, destination, png_bytes = reply.unpack()
            if not ok:
                if on_cancelled is not None:
                    on_cancelled()
                return
            image = decode_png(bytes(png_bytes))
            on_captured(image, destination)
        except Exception:
            print("[gnome_capture_rect] exception in on_reply:", file=sys.stderr, flush=True)
            traceback.print_exc()

    bus.call(
        BUS_NAME, OBJECT_PATH, INTERFACE, "CaptureRect",
        GLib.Variant("(iiii)", (rect.left, rect.top, rect.width, rect.height)),
        GLib.VariantType("(bsay)"), Gio.DBusCallFlags.NONE,
        GLib.MAXINT, None, on_reply, None,
    )
