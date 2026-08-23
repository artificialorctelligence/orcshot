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

The D-Bus call is genuinely async (Gio.DBusConnection.call(), not
call_sync) with an explicit infinite timeout: StartRegionSelect's
reply only arrives once the user finishes the *entire* selection-
through-destination-choice interaction, so this app's own GTK main
loop must keep running throughout (so its own UI - tray menu, any open
windows - stays responsive) and must never hit GDBus's own ~25s
default per-call timeout for what could legitimately be a much longer
wait. See [[feedback-wayland-portal-reentrancy]] in memory for why
this project treats any interactive-D-Bus-round-trip-from-an-event-
handler with this much care.
"""

from __future__ import annotations

import sys
import traceback

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

from orcshot.capture.gnome_clipboard import BUS_NAME
from orcshot.core.geometry import Rect
from orcshot.settings import get_show_magnifier_while_selecting
from orcshot.ui.gdk_convert import pixbuf_to_numpy

# A distinct object path from gnome_clipboard.py's, not just a
# distinct interface name on the same path - confirmed live that a
# second Gio.DBusExportedObject.export() call to an already-exported
# path is silently a no-op in GJS (see extension.js's enable() for the
# full story), so the two D-Bus capabilities this same bundled
# extension offers need two separate paths.
OBJECT_PATH = "/org/gnome/Shell/Extensions/OrcshotCapture"
INTERFACE = "org.gnome.Shell.Extensions.OrcshotCapture"

# A third distinct object path (task #137 follow-up), same reasoning as
# OBJECT_PATH's own comment - the Shell-native tray panel button's state
# (SetRepeatAvailable) is a separate D-Bus capability from either of the
# two above.
TRAY_OBJECT_PATH = "/org/gnome/Shell/Extensions/OrcshotTray"
TRAY_INTERFACE = "org.gnome.Shell.Extensions.OrcshotTray"


def is_available() -> bool:
    from orcshot.capture.gnome_clipboard import is_available as clipboard_is_available

    # Same bundled extension/object as gnome_clipboard.py, just a
    # different D-Bus interface on it - both are exported together by
    # extension.js's enable(), so Ping() answering for one confirms
    # the other is present too.
    return clipboard_is_available()


def notify_repeat_available(available: bool) -> None:
    """Best-effort push to the Shell-native tray panel button (task #137
    follow-up), if that's what's active - it lives in a different
    process from app.py's own self._repeat_item, with no way to poll
    this app's last_region state itself, so app.py's _remember_region
    pushes changes here instead. Silently does nothing when the
    extension isn't running (X11, or Wayland without it) - same
    is_available() guard as everything else in this module, and the
    same fire-and-forget shape as gnome_clipboard.py's SetImage call
    (no reply expected, nothing useful to do if this particular call
    fails - the panel button just keeps its last-known sensitivity)."""
    if not is_available():
        return
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call(
        BUS_NAME, TRAY_OBJECT_PATH, TRAY_INTERFACE, "SetRepeatAvailable",
        GLib.Variant("(b)", (available,)), None, Gio.DBusCallFlags.NONE, -1, None, None, None,
    )


def shell_tray_button_active() -> bool:
    """Whether the Shell-native tray panel button actually exists right
    now - not just whether the extension responds at all (is_available()
    only confirms Ping(), which predates this feature and would still
    succeed against a stale cached module that never built one).
    HasTrayButton distinguishes "the extension's own PanelMenu.Button
    construction succeeded" from "it threw and enable() caught it" (see
    extension.js's own enable()), so app.py's _build_tray_icon can fall
    back to AyatanaAppIndicator3 instead of leaving the user with no
    tray icon at all in that case."""
    if not is_available():
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            BUS_NAME, TRAY_OBJECT_PATH, TRAY_INTERFACE, "HasTrayButton",
            None, GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        return reply.unpack()[0]
    except GLib.Error:
        return False


def get_tray_button_error() -> str:
    """Empty string if there's no error to report - including when the
    extension isn't running at all, since that case is already covered
    elsewhere (app.py's _check_shell_extension_health) and doesn't need
    a second, redundant message here."""
    if not is_available():
        return ""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            BUS_NAME, TRAY_OBJECT_PATH, TRAY_INTERFACE, "GetTrayButtonError",
            None, GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        return reply.unpack()[0]
    except GLib.Error:
        return ""


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
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def on_reply(connection, result, _user_data=None):
        # PyGObject async D-Bus callbacks can swallow exceptions
        # silently depending on context (same caveat documented in
        # ui/monitor_window.py's _call_with_traceback) - print a full
        # traceback rather than lose it, since this drives real
        # user-facing capture results.
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
            print("[gnome_region_select] exception in on_reply:", file=sys.stderr, flush=True)
            traceback.print_exc()

    bus.call(
        BUS_NAME, OBJECT_PATH, INTERFACE, "StartRegionSelect",
        GLib.Variant("(b)", (get_show_magnifier_while_selecting(),)), GLib.VariantType("(bsayiiii)"),
        Gio.DBusCallFlags.NONE, GLib.MAXINT, None, on_reply, None,
    )
