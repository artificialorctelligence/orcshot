"""D-Bus client for the bundled orcshot-clipboard extension's
interactive region-select capability - see that extension's
extension.js docstring and REQUIREMENTS.md's Shell-side rewrite
section (task #77) for the full architecture and rationale.

The *entire* interaction (frozen backdrop, drag-to-select, dim-
outside-selection, Escape-to-cancel, and the post-capture destination
picker) runs inside the Shell/Mutter compositor process as one
continuous flow - no separate client window is ever created for any
of it, unlike region_select_wayland.py's per-monitor MonitorWindow
overlay. By the time StartRegionSelect's reply arrives, a destination
has already been chosen (or the whole thing was cancelled) - this
module hands the caller the destination id straight through, it
doesn't show or know about any picker UI itself.

The request is genuinely async (shell_bridge.request_async, never the
blocking request()) with no timeout: the extension's Deliver only
arrives once the user finishes the *entire* selection-through-
destination-choice interaction, so this app's own GTK main loop must
keep running throughout (so its own UI - tray menu, any open windows -
stays responsive, and so the Deliver call can be serviced at all). See [[feedback-wayland-portal-reentrancy]] in memory for why
this project treats any interactive-D-Bus-round-trip-from-an-event-
handler with this much care.
"""

from __future__ import annotations

import sys
import traceback

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

from orcshot.capture.shell_bridge import ShellRequestError, ShellUnavailable, get_bridge
from orcshot.core.geometry import Rect
from orcshot.settings import get_show_magnifier_while_selecting
from orcshot.ui.gdk_convert import pixbuf_to_numpy

# A distinct object path from gnome_clipboard.py's, not just a
# distinct interface name on the same path - confirmed live that a
# second Gio.DBusExportedObject.export() call to an already-exported
# path is silently a no-op in GJS (see extension.js's enable() for the
# full story), so the two D-Bus capabilities this same bundled
# extension offers need two separate paths.
CAPABILITY = "region-select"


def is_available() -> bool:
    return get_bridge().has(CAPABILITY)


def decode_png(data: bytes):
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
    pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
    return pixbuf_to_numpy(pixbuf)


def start_region_select(on_selected, on_cancelled=None) -> None:
    """Asks the Shell extension to run the whole interactive region-
    select-through-destination-choice flow. Returns immediately -
    ``on_selected(image, absolute_rect, destination)`` or
    ``on_cancelled()`` fires later, once the user finishes the entire
    interaction (drag, then picking a destination) or cancels out of
    it at any point (Escape/click-outside during either the drag or
    the destination picker - the extension treats both the same way,
    so this module doesn't distinguish them either).

    Task #174: passes settings.get_show_magnifier_while_selecting()
    through as StartRegionSelect's own new in-arg - previously this
    preference had no channel into the Shell-native path at all
    (RegionSelectWindow/WaylandRegionSelect, the other two backends,
    already read it directly since they run in this same process),
    so the extension's own RegionSelectOverlay always showed the
    magnifier regardless of what the user had configured.
    """
    def on_result(result: dict):
        try:
            image = decode_png(bytes(result["pngBytes"]))
            x, y, w, h = result["x"], result["y"], result["width"], result["height"]
            on_selected(image, Rect(x, y, x + w, y + h), result["destination"])
        except Exception:
            print("[gnome_region_select] exception in on_result:", file=sys.stderr, flush=True)
            traceback.print_exc()

    def on_error(_error):
        if on_cancelled is not None:
            on_cancelled()

    try:
        get_bridge().request_async(CAPABILITY, {"showMagnifier": get_show_magnifier_while_selecting()}, on_result, on_error)
    except ShellUnavailable:
        on_error(None)
