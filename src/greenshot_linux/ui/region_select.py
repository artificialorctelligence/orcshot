"""The region-selection overlay: a fullscreen, borderless window
showing a frozen copy of the desktop, that lets the user click-drag to
pick a rectangular region. Releasing shows the destination picker
(ui/destination_picker.py) on the selected region; Escape cancels.
This is the actual "day one" trigger for a capture - everything built
so far (capture backends, EditorWindow) needed something to launch
them from a real user gesture, rather than being constructed by hand
in a script.

Not unit tested for the same reason editor_window.py isn't: GTK glue
driving a live event loop and an on-screen window, with no meaningful
headless test. Verified by running it and inspecting real screenshots.

The overlay captures the *whole* virtual screen once up front and
displays that frozen copy for the entire selection gesture, then crops
the final region from that same frozen copy rather than re-grabbing -
both so the displayed backdrop can't drift from what's actually
captured (the desktop could otherwise change mid-drag) and to avoid a
second X11 round-trip.

Also draws a magnifier loupe that follows the cursor (a circular,
nearest-neighbor-zoomed preview of the pixels right around it, plus a
precision crosshair marking the exact cursor pixel) and, once a drag
is in progress, a "W x H" label showing the selection's current pixel
dimensions - both ported from the Windows source's CaptureForm.cs; see
core/magnifier.py and ui/magnifier.py's docstrings for the exact
algorithm this was traced from. Positioning avoids the current
selection rect where possible so the loupe doesn't cover what you're
trying to see. Verified with a FakeCaptureBackend (synthetic
coordinate-pattern image, no real X11 grab) and by calling _on_draw
directly against an offscreen Cairo surface - never a real desktop
capture for inspection, consistent with this project's standing
caution around viewing live desktop content.
"""

from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.core.cursor_capture import cursor_shape_for_capture
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.magnifier import magnifier_diameter, magnifier_offset
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface
from greenshot_linux.ui.capture_modes import should_capture_cursor
from greenshot_linux.ui.magnifier import draw_magnifier
from greenshot_linux.ui.render import render_cursor

_SELECTION_BORDER = (0.1, 0.6, 1.0)
_DIM_ALPHA = 0.5


class RegionSelectWindow(Gtk.Window):
    def __init__(
        self, capture_backend: CaptureBackend, on_region_selected, on_cancelled=None,
        capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
    ):
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

        # Sampled once, right here - matching Windows' own timing
        # (CaptureHelper.cs samples the cursor before the interactive
        # CaptureForm is even shown, CaptureHelper.cs:315-329), not
        # wherever the drag happens to end. Placement math needs the
        # final *selected* rect, not known until button-release, so
        # only the raw snapshot is captured now; core.cursor_capture's
        # placement+intersection check runs later in
        # _on_button_release. cursor_visible is the live "M" key
        # toggle's state (CaptureForm.cs:307-311) - starts at whatever
        # should_capture_cursor decided, can flip during the drag.
        self._cursor_snapshot = None
        self._cursor_preview_shape = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from greenshot_linux.capture.x11_cursor import X11CursorBackend

                cursor_backend = X11CursorBackend()
            self._cursor_snapshot = cursor_backend.cursor_snapshot()
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            local_bounds = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y,
                capture_rect=Rect(self._bounds.left, self._bounds.top, self._bounds.right, self._bounds.bottom),
            )
            self._cursor_preview_shape = local_bounds
        self._cursor_visible = self._cursor_snapshot is not None

        self._drag_origin = None
        self._selection = None
        self._cursor_pos = None

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

        if self._cursor_visible and self._cursor_preview_shape is not None:
            # live preview of the auto-captured cursor overlay, at its
            # one sampled position (see __init__) - not the live mouse
            # position, matching Windows' own CaptureForm.cs:1027-1030.
            render_cursor(ctx, self._cursor_preview_shape)

        if self._cursor_pos is not None:
            diameter = magnifier_diameter(self._bounds.width, self._bounds.height)
            screen_rect = Rect(0, 0, self._bounds.width, self._bounds.height)
            offset = magnifier_offset(self._cursor_pos, screen_rect, self._selection, diameter)
            draw_magnifier(ctx, self._frozen_image, self._cursor_pos, offset, diameter)
            if self._selection is not None:
                self._draw_size_label(ctx, self._selection)
        return False

    def _draw_size_label(self, ctx, selection: Rect) -> None:
        text = f"{selection.width} x {selection.height}"
        cx, cy = self._cursor_pos
        ctx.save()
        ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(13)
        extents = ctx.text_extents(text)
        pad = 4
        x, y = cx + 14, cy + 28
        ctx.set_source_rgba(0, 0, 0, 0.75)
        ctx.rectangle(x - pad, y - extents.height - pad, extents.width + 2 * pad, extents.height + 2 * pad)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to(x, y)
        ctx.show_text(text)
        ctx.restore()

    def _on_button_press(self, widget, event):
        self._drag_origin = (int(event.x), int(event.y))
        self._selection = Rect.from_points(*self._drag_origin, *self._drag_origin)
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        self._cursor_pos = (int(event.x), int(event.y))
        if self._drag_origin is not None:
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
            cursor_shape = None
            if self._cursor_visible and self._cursor_snapshot is not None:
                snap = self._cursor_snapshot
                cursor_shape = cursor_shape_for_capture(
                    snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, absolute,
                )
            self._on_region_selected(cropped, absolute, cursor_shape)
        elif self._on_cancelled is not None:
            self._on_cancelled()
        return True

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        if event.keyval in (Gdk.KEY_m, Gdk.KEY_M) and self._cursor_snapshot is not None:
            # matches Windows' own CaptureForm.cs:307-311 "M" toggle -
            # only meaningful if there's an actual cursor snapshot to
            # show or hide.
            self._cursor_visible = not self._cursor_visible
            widget.queue_draw()
            return True
        return False


def start_region_capture(
    capture_backend: CaptureBackend = None, on_captured=None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
) -> RegionSelectWindow:
    """Show the overlay and show the destination picker on whatever
    gets selected. capture_backend is injectable (for tests/fakes); the
    default constructs the real X11 adapter lazily so importing this
    module doesn't require a display. ``on_captured(absolute_rect)``,
    if given, fires right before the picker opens - GreenshotApplication
    uses this to remember the region for "repeat last region".
    """
    if capture_backend is None:
        from greenshot_linux.capture.x11 import X11CaptureBackend

        capture_backend = X11CaptureBackend()

    def on_selected(image, absolute_rect, cursor_shape):
        if on_captured is not None:
            on_captured(absolute_rect)
        from greenshot_linux.ui.destination_picker import show_destination_picker

        show_destination_picker(image, cursor_shape=cursor_shape)

    window = RegionSelectWindow(
        capture_backend, on_selected, capture_mouse_cursor=capture_mouse_cursor, cursor_backend=cursor_backend,
    )
    window.show_all()
    window.grab_focus()
    return window
