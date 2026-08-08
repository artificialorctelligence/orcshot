"""Clipboard support under GNOME/Wayland, via the bundled
greenshot-linux-clipboard GNOME Shell extension (this project's own,
wholly original code - see the extension's own extension.js docstring
for why it exists and REQUIREMENTS.md's "Clipboard under Wayland"
section for the full write-up).

Preferred over wayland_clipboard.py's invisible-window/focus-wait
technique when available: this calls into St.Clipboard's privileged,
Shell-side access directly, with no client-side focus requirement to
satisfy at all, and no brief window (and its window-list reflow) to
show. Falls back to that technique when the extension isn't installed,
enabled, or responding - same "probe real behavior, never assume from
session/desktop name alone" pattern this project already uses for
window-calls (see capture/gnome_window_calls.py).
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

import numpy as np

from greenshot_linux.ui.gdk_convert import numpy_to_pixbuf

BUS_NAME = "org.gnome.Shell"
OBJECT_PATH = "/org/gnome/Shell/Extensions/GreenshotClipboard"
INTERFACE = "org.gnome.Shell.Extensions.GreenshotClipboard"


class GnomeClipboardUnavailable(RuntimeError):
    """The extension isn't installed, enabled, or responding - callers
    should fall back to wayland_clipboard.py's technique rather than
    raising this up to the user as an error."""


def _encode_png(image: np.ndarray) -> bytes:
    pixbuf = numpy_to_pixbuf(image)
    success, buffer = pixbuf.save_to_bufferv("png", [], [])
    if not success:
        raise ValueError("failed to encode image as PNG")
    return bytes(buffer)


class GnomeClipboardBackend:
    def __init__(self):
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _call(self, method: str, arg_variant=None, arg_type="()"):
        args = arg_variant if arg_variant is not None else GLib.Variant(arg_type, ())
        try:
            reply = self._bus.call_sync(
                BUS_NAME, OBJECT_PATH, INTERFACE, method, args,
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error as error:
            raise GnomeClipboardUnavailable(
                f"greenshot-linux-clipboard extension call {method} failed: {error.message}"
            ) from error
        return reply.unpack()

    def set_image(self, image: np.ndarray) -> None:
        self._call("SetImage", GLib.Variant("(ay)", (_encode_png(image),)))

    def ping(self) -> None:
        self._call("Ping")


def is_available() -> bool:
    """Empirical probe, not an assumption from session/desktop name -
    a GNOME Wayland session with the extension not installed, not
    enabled, or an incompatible Shell version all look identical from
    the outside otherwise (see gnome_window_calls.is_available, the
    same pattern applied to window enumeration). Calls the dedicated
    Ping() method, not SetImage() - probing availability must never
    have the side effect of overwriting the user's real clipboard,
    which opening the destination picker would trigger before the user
    has chosen to copy anything at all."""
    try:
        GnomeClipboardBackend().ping()
        return True
    except GnomeClipboardUnavailable:
        return False
