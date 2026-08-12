"""GTK clipboard adapter for Wayland.

Same Gtk.Clipboard.set_image() call as x11_clipboard.py - GTK's
clipboard API is toolkit-level, not X11-specific, and works under
Wayland's own data-device protocol too. The one thing deliberately
left out: X11ClipboardBackend's clipboard.store() call, which asks the
X11 CLIPBOARD_MANAGER to persist the data past the offering
process/window going away - a purely X11 selection-ownership
convention with no Wayland equivalent (confirmed via research: Wayland
clipboard managers instead rely on the wlr-data-control protocol
extension, a compositor-level mechanism this app has no part in, and
one GNOME/Mutter doesn't implement anyway - same story as
wlr-layer-shell not being implemented, see eyedropper_wayland.py).

The harder problem, confirmed live before this existed: calling
set_image() directly from the destination picker's own menu-item
"activate" handler silently fails to claim the clipboard at all - a
completely separate process probing the clipboard right afterward saw
zero targets, not a delayed-expiry symptom. Root cause, confirmed via
research (Wayland's own protocol docs plus wl-clipboard's documented
behavior): a wl_data_offer is only valid while the *claiming client
has real keyboard focus*, and set_selection() needs a recent, valid
serial from that focus. Gtk.Menu's popup is a Wayland popup-role
surface, which gets pointer/keyboard *events* forwarded via its
parent's grab but never receives genuine wl_keyboard focus the way a
real toplevel window does - so the claim from inside a menu item never
had valid focus to begin with, on any compositor without the
wlr-data-control extension.

wl-clipboard's own real-world fix for exactly this (confirmed via its
documentation, not assumed) is the technique used here: briefly show a
tiny, invisible TOPLEVEL window purely to receive genuine
compositor-granted focus (the same natural "TOPLEVEL windows get real
focus on mapping" behavior this project already relies on for
region-select/window-picker/eyedropper), and only claim the clipboard
once that focus genuinely arrives - not assumed to be instant. This is
the documented industry-standard workaround for compositors (GNOME/
Mutter included) that don't implement the "correct" protocol extension,
not a guaranteed mechanism - wl-clipboard's own docs note some
compositors don't reliably focus this kind of window either, hence the
timeout fallback below.

This makes set_image() fire off asynchronous work rather than claim
the clipboard synchronously before returning - acceptable here since
ClipboardBackend.set_image()'s contract was always fire-and-forget
(callers never waited for or checked a result).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

import numpy as np

from orcshot.ui.gdk_convert import numpy_to_pixbuf

_FOCUS_TIMEOUT_MS = 1000


class WaylandClipboardBackend:
    def set_image(self, image: np.ndarray) -> None:
        pixbuf = numpy_to_pixbuf(image)

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_decorated(False)
        window.set_default_size(1, 1)
        window.set_accept_focus(True)
        # Standard EWMH-style hints asking the shell not to give this
        # window a taskbar/window-list entry or an Alt-Tab/pager
        # appearance - worth trying since the brief invisible window
        # is otherwise visible as a momentary window-list reflow (see
        # this module's docstring). Harmless if unsupported/ignored
        # under Wayland, unlike Gdk.Window.focus() - these are just
        # hints, not a protocol call that can itself fail.
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        screen = window.get_screen()
        rgba_visual = screen.get_rgba_visual() if screen is not None else None
        if rgba_visual is not None:
            window.set_visual(rgba_visual)
        window.set_opacity(0)

        state = {"claimed": False}

        def claim_and_close() -> None:
            if state["claimed"]:
                return
            state["claimed"] = True
            clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
            clipboard.set_image(pixbuf)
            window.destroy()

        def on_focus_in(_widget, _event) -> bool:
            claim_and_close()
            return False

        def on_timeout() -> bool:
            # Focus never arrived - see this module's docstring. Try
            # the claim anyway (best-effort; matches this backend's
            # pre-focus-fix behavior, may or may not actually stick)
            # rather than silently doing nothing, and clean up either
            # way instead of leaving an invisible window behind.
            claim_and_close()
            return False  # GLib.timeout_add: run once, don't repeat

        window.connect("focus-in-event", on_focus_in)
        GLib.timeout_add(_FOCUS_TIMEOUT_MS, on_timeout)
        window.show_all()
        window.present()
