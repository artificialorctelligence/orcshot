"""D-Bus client for the bundled orcshot-clipboard extension's
interactive eyedropper capability - the color-picking counterpart to
gnome_region_select.py/gnome_window_picker.py (see gnome_region_select.py's
own docstring for the shared architecture/rationale, task #77).

Unlike region-select/window-picker, there's no destination picker
chained onto this one at all - the whole point of the eyedropper is to
hand a single sampled colour back to its caller (the colour dialog),
not to capture an image. The Shell-side overlay (frozen backdrop,
press-drag-release sampling, the magnifier loupe) runs entirely inside
the Shell/Mutter compositor process, same as the other two.
"""

from __future__ import annotations

import sys
import traceback

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from orcshot.capture.gnome_clipboard import BUS_NAME

OBJECT_PATH = "/org/gnome/Shell/Extensions/OrcshotCapture"
INTERFACE = "org.gnome.Shell.Extensions.OrcshotCapture"


def is_available() -> bool:
    from orcshot.capture.gnome_clipboard import is_available as clipboard_is_available

    return clipboard_is_available()


def start_eyedropper(on_picked, on_cancelled=None) -> None:
    """Asks the Shell extension to run the interactive eyedropper.
    Returns immediately - ``on_picked(color)`` (an (r, g, b, a) tuple,
    each 0-255) or ``on_cancelled()`` fires later, once the user
    finishes or cancels the press-drag-release gesture."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def on_reply(connection, result, _user_data=None):
        try:
            try:
                reply = connection.call_finish(result)
            except GLib.Error:
                if on_cancelled is not None:
                    on_cancelled()
                return
            ok, r, g, b, a = reply.unpack()
            if not ok:
                if on_cancelled is not None:
                    on_cancelled()
                return
            on_picked((r, g, b, a))
        except Exception:
            print("[gnome_eyedropper] exception in on_reply:", file=sys.stderr, flush=True)
            traceback.print_exc()

    bus.call(
        BUS_NAME, OBJECT_PATH, INTERFACE, "StartEyedropper",
        None, GLib.VariantType("(byyyy)"), Gio.DBusCallFlags.NONE,
        GLib.MAXINT, None, on_reply, None,
    )
