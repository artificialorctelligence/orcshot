"""Wayland-specific region-selection overlay: same UX as
region_select.py's RegionSelectWindow, built from N per-monitor
fullscreen windows (ui/monitor_window.py) instead of one POPUP window
spanning the whole virtual screen via absolute positioning - see
monitor_window.py's module docstring for why that trick doesn't work
under Wayland.

All shared state (the in-progress selection, live cursor position, the
one-time-sampled cursor-preview shape) is kept in absolute/global
(virtual-screen) coordinates - the same convention region_select.py
already uses internally, just not implicitly equal to "this window's
local coordinates" anymore now that there are several windows.
_rect_in_monitor_local is the one pure conversion point: given any
global-coordinate Rect and a specific monitor's bounds, it returns
that rect's local-to-that-monitor portion, or None if it doesn't
overlap that monitor at all.

Cursor-following elements (the aiming crosshair, the magnifier loupe,
the "W x H" size label) are only ever drawn by whichever single window
currently contains the cursor - drawing them in every window using the
same global cursor position would place them at nonsensical local
coordinates everywhere except the one window actually under the
pointer. Every window still independently draws its own dim-with-hole
overlay and selection-rect border for whatever portion of the shared
selection overlaps its own monitor, so a selection spanning multiple
monitors renders correctly across all of them.
"""

from __future__ import annotations

from dataclasses import replace

import cairo
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.core.cursor_capture import cursor_shape_for_capture
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.magnifier import magnifier_diameter, magnifier_offset
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface
from greenshot_linux.ui.capture_modes import should_capture_cursor
from greenshot_linux.ui.magnifier import draw_magnifier
from greenshot_linux.ui.monitor_window import (
    MonitorWindow,
    create_monitor_windows,
    destroy_all,
    queue_draw_all,
)
from greenshot_linux.ui.region_select import (
    _COORD_TOOLTIP_BG,
    _COORD_TOOLTIP_BORDER,
    _CROSSHAIR_COLOR,
    _DIM_ALPHA,
    _SELECTION_BORDER,
)
from greenshot_linux.ui.render import render_cursor


def _rect_in_monitor_local(rect: Rect, monitor_bounds: Rect) -> Rect | None:
    """``rect`` in absolute/global (virtual-screen) coordinates,
    translated to be local to ``monitor_bounds`` - or None if it
    doesn't overlap that monitor at all."""
    overlap = rect.intersect(monitor_bounds)
    if overlap is None:
        return None
    return Rect(
        overlap.left - monitor_bounds.left, overlap.top - monitor_bounds.top,
        overlap.right - monitor_bounds.left, overlap.bottom - monitor_bounds.top,
    )


class WaylandRegionSelect:
    def __init__(
        self, capture_backend: CaptureBackend, on_region_selected, on_cancelled=None,
        capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
    ):
        self._on_region_selected = on_region_selected
        self._on_cancelled = on_cancelled

        layout = capture_backend.screen_layout()
        self._bounds = layout.virtual_bounds
        self._frozen_image = capture_backend.grab(self._bounds)

        # Same sampling as RegionSelectWindow - see its __init__
        # docstring for the Windows-parity timing rationale.
        self._cursor_snapshot = None
        self._cursor_preview_shape = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from greenshot_linux.capture.x11_cursor import X11CursorBackend

                cursor_backend = X11CursorBackend()
            self._cursor_snapshot = cursor_backend.cursor_snapshot()
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, capture_rect=self._bounds,
            )
            if shape is not None:
                # cursor_shape_for_capture returns bounds relative to
                # capture_rect's own origin - convert to absolute once,
                # so every other piece of shared state is consistently
                # global, and _rect_in_monitor_local handles all of it
                # uniformly.
                b = shape.bounds
                absolute_bounds = Rect(
                    b.left + self._bounds.left, b.top + self._bounds.top,
                    b.right + self._bounds.left, b.bottom + self._bounds.top,
                )
                shape = replace(shape, bounds=absolute_bounds)
            self._cursor_preview_shape = shape
        self._cursor_visible = self._cursor_snapshot is not None

        self._drag_origin: tuple[int, int] | None = None
        self._selection: Rect | None = None
        self._cursor_pos: tuple[int, int] | None = None

        self._monitor_images = {}
        self._surfaces = {}
        for index, monitor in enumerate(layout.monitors):
            top = monitor.bounds.top - self._bounds.top
            left = monitor.bounds.left - self._bounds.left
            image_slice = self._frozen_image[top:top + monitor.bounds.height, left:left + monitor.bounds.width]
            self._monitor_images[index] = image_slice
            self._surfaces[index] = numpy_to_cairo_surface(image_slice)

        self._windows = create_monitor_windows(
            layout.monitors,
            on_draw=self._on_draw,
            on_motion=self._on_motion,
            on_button_press=self._on_button_press,
            on_button_release=self._on_button_release,
            on_key_press=self._on_key_press,
        )
        self._window_index = {window: index for index, window in enumerate(self._windows)}

    def show(self) -> None:
        crosshair = Gdk.Cursor.new_for_display(Gdk.Display.get_default(), Gdk.CursorType.CROSSHAIR)
        for window in self._windows:
            window.show_fullscreen()
            window.get_window().set_cursor(crosshair)
        # No keyboard grab here, unlike X11's RegionSelectWindow: that
        # one needs it because X11 POPUP (override-redirect) windows
        # never get real window-manager focus at all. These are plain
        # TOPLEVEL windows, which Mutter focuses normally on mapping
        # (confirmed live on this same session) - a grab would also
        # trigger Wayland's keyboard-shortcuts-inhibit permission
        # dialog, an async, easy-to-miss consent prompt this code
        # never waits for. If Escape/M turn out to need it after all,
        # revisit rather than assume - but try without it first.

    def _on_draw(self, window: MonitorWindow, ctx) -> None:
        index = self._window_index[window]
        ctx.set_source_surface(self._surfaces[index], 0, 0)
        ctx.paint()

        local_selection = _rect_in_monitor_local(self._selection, window.monitor_bounds) if self._selection else None

        ctx.save()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(0, 0, window.monitor_bounds.width, window.monitor_bounds.height)
        if local_selection is not None:
            ctx.rectangle(local_selection.left, local_selection.top, local_selection.width, local_selection.height)
        ctx.set_source_rgba(0, 0, 0, _DIM_ALPHA)
        ctx.fill()
        ctx.restore()

        if local_selection is not None:
            ctx.save()
            ctx.set_source_rgb(*_SELECTION_BORDER)
            ctx.set_line_width(1)
            ctx.rectangle(local_selection.left, local_selection.top, local_selection.width, local_selection.height)
            ctx.stroke()
            ctx.restore()

        if self._cursor_visible and self._cursor_preview_shape is not None:
            local_bounds = _rect_in_monitor_local(self._cursor_preview_shape.bounds, window.monitor_bounds)
            if local_bounds is not None:
                render_cursor(ctx, replace(self._cursor_preview_shape, bounds=local_bounds))

        if self._cursor_pos is not None and window.monitor_bounds.contains(*self._cursor_pos):
            local_x, local_y = window.to_local(*self._cursor_pos)
            if self._drag_origin is None:
                self._draw_aiming_crosshair(ctx, window, local_x, local_y)

            diameter = magnifier_diameter(window.monitor_bounds.width, window.monitor_bounds.height)
            screen_rect = Rect(0, 0, window.monitor_bounds.width, window.monitor_bounds.height)
            offset = magnifier_offset((local_x, local_y), screen_rect, local_selection, diameter)
            draw_magnifier(ctx, self._monitor_images[index], (local_x, local_y), offset, diameter)
            if local_selection is not None:
                self._draw_size_label(ctx, local_x, local_y, self._selection)

    def _draw_size_label(self, ctx, local_x: int, local_y: int, global_selection: Rect) -> None:
        text = f"{global_selection.width} x {global_selection.height}"
        ctx.save()
        ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(13)
        extents = ctx.text_extents(text)
        pad = 4
        x, y = local_x + 14, local_y + 28
        ctx.set_source_rgba(0, 0, 0, 0.75)
        ctx.rectangle(x - pad, y - extents.height - pad, extents.width + 2 * pad, extents.height + 2 * pad)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to(x, y)
        ctx.show_text(text)
        ctx.restore()

    def _draw_aiming_crosshair(self, ctx, window: MonitorWindow, local_x: int, local_y: int) -> None:
        ctx.save()
        ctx.set_source_rgb(*_CROSSHAIR_COLOR)
        ctx.set_line_width(1)
        ctx.set_dash([1, 3])
        ctx.move_to(local_x + 0.5, 0)
        ctx.line_to(local_x + 0.5, window.monitor_bounds.height)
        ctx.stroke()
        ctx.move_to(0, local_y + 0.5)
        ctx.line_to(window.monitor_bounds.width, local_y + 0.5)
        ctx.stroke()
        ctx.restore()

        # Absolute screen position, matching WinForms' Cursor.Position
        # being screen-space, not window-relative.
        global_x, global_y = window.to_global(local_x, local_y)
        text = f"{global_x} x {global_y}"
        ctx.save()
        ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(11)
        extents = ctx.text_extents(text)
        pad = 3
        box_x, box_y = local_x + 5, local_y + 5
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

    def _on_motion(self, global_x: int, global_y: int) -> None:
        self._cursor_pos = (global_x, global_y)
        if self._drag_origin is not None:
            x0, y0 = self._drag_origin
            self._selection = Rect.from_points(x0, y0, global_x, global_y)
        queue_draw_all(self._windows)

    def _on_button_press(self, global_x: int, global_y: int) -> None:
        self._drag_origin = (global_x, global_y)
        self._selection = Rect.from_points(global_x, global_y, global_x, global_y)
        queue_draw_all(self._windows)

    def _on_button_release(self, global_x: int, global_y: int) -> None:
        if self._drag_origin is None:
            return
        x0, y0 = self._drag_origin
        selection = Rect.from_points(x0, y0, global_x, global_y)
        self._drag_origin = None

        clamped = selection.intersect(self._bounds)
        if clamped is not None and clamped.width > 0 and clamped.height > 0:
            # Keep whichever window contains the release point alive as
            # the destination picker's popup anchor - Wayland popups
            # need a real, still-mapped parent surface (see
            # destination_picker.py's anchor_window docstring); destroy
            # the rest now, this one once the picker closes.
            anchor_window = None
            anchor_local_pos = None
            for window in self._windows:
                if window.monitor_bounds.contains(global_x, global_y):
                    anchor_window = window
                    anchor_local_pos = window.to_local(global_x, global_y)
                    break
            for window in self._windows:
                if window is not anchor_window:
                    window.destroy()

            top = clamped.top - self._bounds.top
            left = clamped.left - self._bounds.left
            cropped = self._frozen_image[top:top + clamped.height, left:left + clamped.width]
            cursor_shape = None
            if self._cursor_visible and self._cursor_snapshot is not None:
                snap = self._cursor_snapshot
                cursor_shape = cursor_shape_for_capture(
                    snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, clamped,
                )
            self._on_region_selected(
                cropped, clamped, cursor_shape,
                anchor_monitor_window=anchor_window, anchor_local_pos=anchor_local_pos,
            )
        else:
            destroy_all(self._windows)
            if self._on_cancelled is not None:
                self._on_cancelled()

    def _on_key_press(self, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            destroy_all(self._windows)
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        if event.keyval in (Gdk.KEY_m, Gdk.KEY_M) and self._cursor_snapshot is not None:
            self._cursor_visible = not self._cursor_visible
            queue_draw_all(self._windows)
            return True
        return False
