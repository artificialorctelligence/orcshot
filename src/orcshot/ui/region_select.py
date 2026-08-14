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
trying to see.

Before a drag starts (not once one's in progress), also draws a
full-screen dotted aiming crosshair through the cursor plus a small
"X x Y" coordinate tooltip - faithful port of CaptureForm.cs:1154-1182
(colors, dash style, and tooltip layout all taken from that block
directly: LightSeaGreen #20B2AA dotted lines, a SeaGreen #2E8B57
tooltip border/text on a light mint background). Deliberately not
shared with window_picker.py: the real source gates this exact branch
with `!(_mouseDown || _captureMode == CaptureMode.Window || ...)` -
Window-mode capture never reaches it either, even though CaptureForm
is nominally one shared class across capture modes.

Verified with a FakeCaptureBackend (synthetic coordinate-pattern
image, no real X11 grab) and by calling _on_draw directly against an
offscreen Cairo surface - never a real desktop capture for inspection,
consistent with this project's standing caution around viewing live
desktop content.
"""

from __future__ import annotations

import os

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from orcshot.capture.backend import CaptureBackend
from orcshot.capture.cursor import CursorBackend
from orcshot.core.cursor_capture import cursor_shape_for_capture
from orcshot.core.geometry import Rect
from orcshot.core.magnifier import magnifier_diameter, magnifier_offset
from orcshot.settings import get_show_magnifier_while_selecting
from orcshot.ui.cairo_convert import numpy_to_cairo_surface
from orcshot.ui.capture_modes import should_capture_cursor
from orcshot.ui.magnifier import draw_magnifier
from orcshot.ui.render import render_cursor

_SELECTION_BORDER = (0.1, 0.6, 1.0)
_DIM_ALPHA = 0.5

# CaptureForm.cs:1154-1182's aiming-crosshair colors, converted from
# System.Drawing's named colors to 0-1 RGB: LightSeaGreen (#20B2AA)
# for the crosshair lines, SeaGreen (#2E8B57) for the coordinate
# tooltip's border/text, and its light-mint background
# (FromArgb(200, 217, 240, 227), alpha included).
_CROSSHAIR_COLOR = (32 / 255, 178 / 255, 170 / 255)
_COORD_TOOLTIP_BORDER = (46 / 255, 139 / 255, 87 / 255)
_COORD_TOOLTIP_BG = (217 / 255, 240 / 255, 227 / 255, 200 / 255)


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

        self._screen_layout = capture_backend.screen_layout()
        self._bounds = self._screen_layout.virtual_bounds
        self._frozen_image = capture_backend.grab(self._bounds)
        self._surface = numpy_to_cairo_surface(self._frozen_image)

        # Faithful port of Windows' "zoomer" setting (task #95's
        # Capture tab, settings.get_show_magnifier_while_selecting) -
        # read once here rather than per-frame in _on_draw, matching
        # how capture_mouse_cursor is resolved once at construction
        # too. No per-invocation asymmetry the way cursor capture has
        # (hotkey vs. tray), so no threading through start_region_
        # capture's own signature is needed - just the one global
        # setting.
        self._show_magnifier = get_show_magnifier_while_selecting()

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
                from orcshot.capture.x11_cursor import X11CursorBackend

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

        if self._cursor_pos is not None and self._drag_origin is None:
            self._draw_aiming_crosshair(ctx)

        if self._cursor_pos is not None and self._show_magnifier:
            # Sized from the monitor under the cursor, not the whole
            # virtual desktop - matches both the Wayland path
            # (region_select_wayland.py, naturally per-monitor since it
            # uses one overlay window per monitor) and the real Windows
            # source (CaptureForm.cs:814-819's screenBounds comes from
            # DisplayInfo.GetBounds(MousePosition), the single display
            # under the cursor). Falls back to the full virtual bounds
            # if the cursor is over dead space between differently
            # sized/offset monitors (see ScreenLayout's own docstring).
            monitor = self._screen_layout.monitor_at(
                self._bounds.left + self._cursor_pos[0], self._bounds.top + self._cursor_pos[1],
            )
            monitor_bounds = monitor.bounds if monitor is not None else self._bounds
            diameter = magnifier_diameter(monitor_bounds.width, monitor_bounds.height)
            screen_rect = Rect(0, 0, self._bounds.width, self._bounds.height)
            offset = magnifier_offset(self._cursor_pos, screen_rect, self._selection, diameter)
            draw_magnifier(ctx, self._frozen_image, self._cursor_pos, offset, diameter)
        if self._cursor_pos is not None:
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

    def _draw_aiming_crosshair(self, ctx) -> None:
        """Full-screen dotted crosshair through the cursor, plus a
        small coordinate tooltip - faithful port of CaptureForm.cs:
        1154-1182 (see this module's docstring for why it's only drawn
        before a drag starts, and only here, not window_picker.py).
        Coordinates in the tooltip are absolute screen position
        (self._bounds.left/top + the local cursor position), matching
        WinForms' Cursor.Position being screen-space, not form-relative.
        """
        x, y = self._cursor_pos
        ctx.save()
        ctx.set_source_rgb(*_CROSSHAIR_COLOR)
        ctx.set_line_width(1)
        ctx.set_dash([1, 3])
        ctx.move_to(x + 0.5, 0)
        ctx.line_to(x + 0.5, self._bounds.height)
        ctx.stroke()
        ctx.move_to(0, y + 0.5)
        ctx.line_to(self._bounds.width, y + 0.5)
        ctx.stroke()
        ctx.restore()

        text = f"{self._bounds.left + x} x {self._bounds.top + y}"
        ctx.save()
        ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(11)
        extents = ctx.text_extents(text)
        pad = 3
        box_x, box_y = x + 5, y + 5
        box_w, box_h = extents.width + 2 * pad, extents.height + 2 * pad
        ctx.set_source_rgba(*_COORD_TOOLTIP_BG)
        ctx.rectangle(box_x, box_y, box_w, box_h)
        ctx.fill_preserve()
        ctx.set_source_rgb(*_COORD_TOOLTIP_BORDER)
        ctx.set_line_width(1)
        ctx.set_dash([])
        ctx.stroke()
        ctx.move_to(box_x + pad, box_y + pad + extents.height)
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
        self._release_grab()
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
            self._release_grab()
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

    def _release_grab(self) -> None:
        Gdk.Display.get_default().get_default_seat().ungrab()


def start_region_capture(
    capture_backend: CaptureBackend = None, on_captured=None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
):
    """Show the overlay and show the destination picker on whatever
    gets selected. capture_backend is injectable (for tests/fakes); the
    default constructs the real X11 adapter lazily so importing this
    module doesn't require a display. ``on_captured(absolute_rect)``,
    if given, fires right before the picker opens (or, under Wayland
    with the bundled Shell extension available, right after a capture
    completes - see below) - OrcshotApplication uses this to
    remember the region for "repeat last region".

    Under Wayland, prefers GnomeShellRegionSelect (the bundled
    orcshot-clipboard extension's Shell-side selection-through-
    destination-choice flow - see ui/region_select_gnome_shell.py's own
    docstring) when available, falling back to WaylandRegionSelect (a
    per-monitor multi-window overlay - see
    ui/region_select_wayland.py's module docstring for why a single
    POPUP window, this function's X11 path below, doesn't work there)
    otherwise.
    """
    if capture_backend is None:
        from orcshot.capture.backend_select import default_capture_backend

        capture_backend = default_capture_backend()

    def on_selected(image, absolute_rect, cursor_shape, anchor_monitor_window=None, anchor_local_pos=None):
        if on_captured is not None:
            on_captured(absolute_rect)
        from orcshot.ui.destination_picker import show_destination_picker

        gdk_anchor = anchor_monitor_window.get_window() if anchor_monitor_window is not None else None
        menu = show_destination_picker(
            image, cursor_shape=cursor_shape, anchor_window=gdk_anchor, anchor_local_pos=anchor_local_pos,
        )
        if anchor_monitor_window is not None:
            menu.connect("deactivate", lambda _menu: anchor_monitor_window.destroy())

    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from orcshot.capture.gnome_region_select import is_available as gnome_shell_capture_available

        if gnome_shell_capture_available():
            # Own branch, not on_selected: GnomeShellRegionSelect's
            # contract is different from the other two overlays' - the
            # destination has already been chosen Shell-side by the
            # time Python hears about a capture at all (see that
            # module's own docstring for why), so there's no picker to
            # show here, just on_captured for "repeat last region"
            # bookkeeping.
            from orcshot.ui.region_select_gnome_shell import GnomeShellRegionSelect

            overlay = GnomeShellRegionSelect(
                on_captured=on_captured, capture_mouse_cursor=capture_mouse_cursor, cursor_backend=cursor_backend,
            )
            overlay.show()
            return overlay

        from orcshot.ui.region_select_wayland import WaylandRegionSelect

        overlay = WaylandRegionSelect(
            capture_backend, on_selected, capture_mouse_cursor=capture_mouse_cursor, cursor_backend=cursor_backend,
        )
        overlay.show()
        return overlay

    window = RegionSelectWindow(
        capture_backend, on_selected, capture_mouse_cursor=capture_mouse_cursor, cursor_backend=cursor_backend,
    )
    window.show_all()
    window.grab_focus()
    # POPUP (override-redirect) windows bypass the window manager, so
    # nothing ever hands them real X keyboard focus - grab_focus() only
    # sets GTK's own bookkeeping. Without an explicit keyboard grab,
    # Escape silently goes to whatever window last had focus instead of
    # this overlay. Confirmed empirically: has_toplevel_focus()/
    # XGetInputFocus both stayed false after grab_focus() alone; a
    # Gdk.Seat KEYBOARD grab is what actually redirects key events here
    # regardless of nominal X focus.
    Gdk.Display.get_default().get_default_seat().grab(
        window.get_window(), Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None,
    )
    # Faithful port of CaptureForm.Designer.cs:61's `this.Cursor =
    # Cursors.Cross` - the real OS mouse pointer itself becomes a
    # crosshair for the whole selection gesture, separate from (and in
    # addition to) the full-screen guide lines RegionSelectWindow's own
    # _on_draw already draws. Gdk.CursorType.CROSSHAIR is the same
    # X cursor-font glyph Cursors.Cross maps to.
    crosshair = Gdk.Cursor.new_for_display(Gdk.Display.get_default(), Gdk.CursorType.CROSSHAIR)
    window.get_window().set_cursor(crosshair)
    return window
