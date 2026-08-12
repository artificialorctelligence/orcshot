"""D-Bus client for the bundled orcshot-clipboard extension's
interactive window-picker capability - the window-picker counterpart
to gnome_region_select.py (see that module's own docstring for the
shared architecture/rationale, task #77). Mirrors it closely: the
*entire* interaction (frozen backdrop, hover-highlight over real
window geometry, click-to-select + raise, and the post-capture
destination picker) runs inside the Shell/Mutter compositor process as
one continuous flow, using the exact same StartWindowPicker reply
shape and pickDestinationAsync as region-select does.

Real window geometry/content comes straight from Shell's own native
`global.get_window_actors()`/`Meta.Window` API now that the caller is
Shell-side too, not the bundled window-calls extension's own D-Bus
interface - the "worth checking during implementation" note in
REQUIREMENTS.md's original plan panned out.
"""

from __future__ import annotations

import sys
import traceback

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from orcshot.capture.gnome_clipboard import BUS_NAME
from orcshot.capture.gnome_region_select import decode_png
from orcshot.core.geometry import Rect

OBJECT_PATH = "/org/gnome/Shell/Extensions/OrcshotCapture"
INTERFACE = "org.gnome.Shell.Extensions.OrcshotCapture"


def is_available() -> bool:
    from orcshot.capture.gnome_clipboard import is_available as clipboard_is_available

    return clipboard_is_available()


def start_window_picker(on_selected, on_cancelled=None) -> None:
    """Asks the Shell extension to run the whole interactive window-
    picker-through-destination-choice flow. Returns immediately -
    ``on_selected(image, absolute_rect, destination)`` or
    ``on_cancelled()`` fires later, once the user finishes the entire
    interaction (click a window, then pick a destination) or cancels
    out of it at any point."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def on_reply(connection, result, _user_data=None):
        try:
            try:
                reply = connection.call_finish(result)
            except GLib.Error:
                if on_cancelled is not None:
                    on_cancelled()
                return
            ok, destination, png_bytes, x, y, width, height = reply.unpack()
            if not ok:
                if on_cancelled is not None:
                    on_cancelled()
                return
            image = decode_png(bytes(png_bytes))
            on_selected(image, Rect(x, y, x + width, y + height), destination)
        except Exception:
            print("[gnome_window_picker] exception in on_reply:", file=sys.stderr, flush=True)
            traceback.print_exc()

    bus.call(
        BUS_NAME, OBJECT_PATH, INTERFACE, "StartWindowPicker",
        None, GLib.VariantType("(bsayiiii)"), Gio.DBusCallFlags.NONE,
        GLib.MAXINT, None, on_reply, None,
    )
