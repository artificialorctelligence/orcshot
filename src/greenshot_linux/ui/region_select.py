"""The region-selection overlay: a fullscreen, borderless window
showing a frozen copy of the desktop, that lets the user click-drag to
pick a rectangular region. Releasing launches EditorWindow on the
selected region; Escape cancels. This is the actual "day one" trigger
for a capture - everything built so far (capture backends,
EditorWindow) needed something to launch them from a real user
gesture, rather than being constructed by hand in a script.

Not unit tested for the same reason editor_window.py isn't: GTK glue
driving a live event loop and an on-screen window, with no meaningful
headless test. Verified by running it and inspecting real screenshots.

The overlay captures the *whole* virtual screen once up front and
displays that frozen copy for the entire selection gesture, then crops
the final region from that same frozen copy rather than re-grabbing -
both so the displayed backdrop can't drift from what's actually
captured (the desktop could otherwise change mid-drag) and to avoid a
second X11 round-trip.
"""

from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.core.geometry import Rect
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface

_SELECTION_BORDER = (0.1, 0.6, 1.0)
_DIM_ALPHA = 0.5


class RegionSelectWindow(Gtk.Window):
    def __init__(self, capture_backend: CaptureBackend, on_region_selected, on_cancelled=None):
        # POPUP (X11 override-redirect) rather than TOPLEVEL: a normal
        # toplevel gets its size clamped by the window manager to a
        # single monitor's work area (confirmed empirically - a 4480x1440
        # request came back 4480x1040 under Cinnamon/Muffin here, cutting
        # off part of the taller of two monitors). POPUP bypasses window
        # manager placement/sizing entirely, giving exact geometry
        # control - the same technique other screenshot tools use for
        # this kind of overlay.
        super().__init__(type=Gtk.WindowType.POPUP)
        self._on_region_selected = on_region_selected
        self._on_cancelled = on_cancelled

        self._bounds = capture_backend.screen_layout().virtual_bounds
        self._frozen_image = capture_backend.grab(self._bounds)
        self._surface = numpy_to_cairo_surface(self._frozen_image)

        self._drag_origin = None
        self._selection = None

        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.set_can_focus(True)
        self.move(self._bounds.left, self._bounds.top)
        self.resize(self._bounds.width, self._bounds.height)

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_button_release)
        self.connect("key-press-event", self._on_key_press)

    def _on_draw(self, widget, ctx):
        ctx.set_source_surface(self._surface, 0, 0)
        ctx.paint()

        # Dim everything except the current selection, via an even-odd
        # fill rule "hole" - simpler than clip-region combination.
        ctx.save()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(0, 0, self._bounds.width, self._bounds.height)
        if self._selection is not None:
            s = self._selection
            ctx.rectangle(s.left, s.top, s.width, s.height)
        ctx.set_source_rgba(0, 0, 0, _DIM_ALPHA)
        ctx.fill()
        ctx.restore()

        if self._selection is not None:
            s = self._selection
            ctx.save()
            ctx.set_source_rgb(*_SELECTION_BORDER)
            ctx.set_line_width(1)
            ctx.rectangle(s.left, s.top, s.width, s.height)
            ctx.stroke()
            ctx.restore()
        return False

    def _on_button_press(self, widget, event):
        self._drag_origin = (int(event.x), int(event.y))
        self._selection = Rect.from_points(*self._drag_origin, *self._drag_origin)
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        if self._drag_origin is None:
            return False
        x0, y0 = self._drag_origin
        self._selection = Rect.from_points(x0, y0, int(event.x), int(event.y))
        widget.queue_draw()
        return True

    def _on_button_release(self, widget, event):
        if self._drag_origin is None:
            return False
        x0, y0 = self._drag_origin
        local = Rect.from_points(x0, y0, int(event.x), int(event.y))
        self._drag_origin = None
        self.destroy()
        if local.width > 0 and local.height > 0:
            cropped = self._frozen_image[local.top:local.bottom, local.left:local.right]
            absolute = Rect(
                local.left + self._bounds.left, local.top + self._bounds.top,
                local.right + self._bounds.left, local.bottom + self._bounds.top,
            )
            self._on_region_selected(cropped, absolute)
        elif self._on_cancelled is not None:
            self._on_cancelled()
        return True

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        return False


def start_region_capture(capture_backend: CaptureBackend = None, on_captured=None) -> RegionSelectWindow:
    """Show the overlay and launch EditorWindow on whatever gets
    selected. capture_backend is injectable (for tests/fakes); the
    default constructs the real X11 adapter lazily so importing this
    module doesn't require a display. ``on_captured(absolute_rect)``,
    if given, fires right before the editor opens - GreenshotApplication
    uses this to remember the region for "repeat last region".
    """
    if capture_backend is None:
        from greenshot_linux.capture.x11 import X11CaptureBackend

        capture_backend = X11CaptureBackend()

    def on_selected(image, absolute_rect):
        if on_captured is not None:
            on_captured(absolute_rect)
        from greenshot_linux.ui.editor_window import EditorWindow

        editor = EditorWindow(image)
        editor.show_all()

    window = RegionSelectWindow(capture_backend, on_selected)
    window.show_all()
    window.grab_focus()
    return window
