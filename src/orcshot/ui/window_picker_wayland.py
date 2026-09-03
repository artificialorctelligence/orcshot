"""Wayland-specific window-picker overlay: same UX as window_picker.py's
WindowPickerWindow, built from N per-monitor fullscreen windows instead
of one POPUP spanning the whole virtual screen via absolute positioning
- see monitor_window.py's module docstring for why, and
region_select_wayland.py's module docstring for the shared
global-coordinate-state design this mirrors (hover state and the
frozen backdrop are all absolute/virtual-screen coordinates; each
MonitorWindow only translates to its own local frame at draw time).

No crosshair/magnifier here, matching window_picker.py's own docstring
on why those are deliberately region-select-only. No keyboard grab
either, for the same reason region_select_wayland.py dropped it: these
are plain TOPLEVEL windows, which Mutter focuses normally on mapping,
unlike X11's POPUP windows which never get real focus at all.

The activate+fresh-grab portal round trip (see WindowActivator's
docstring) is never called directly from the button-press-event
handler: confirmed live that doing so hangs indefinitely (waited
several minutes; even the portal call's own 120s timeout never fired,
meaning the nested GLib.MainLoop it starts wasn't processing *any* of
its own sources, not just waiting on the compositor - a reentrancy
problem, not a slow response). Deferring the whole selection via
GLib.idle_add avoided the hang but broke the destination picker's
popup instead ("no trigger event for menu popup") - Wayland's popup
grab needs to be requested synchronously within the triggering event.
The fix that satisfies both constraints: show the destination picker
immediately, using the frozen backdrop as a placeholder image, and
only resolve the real activate()+fresh-grab pixels once the user picks
an actual menu item - see destination_picker.py's refresh_image
docstring for the full reasoning.
"""

from __future__ import annotations

import time
from dataclasses import replace

import cairo
import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

from orcshot.capture.backend import CaptureBackend
from orcshot.capture.cursor import CursorBackend
from orcshot.capture.window import WindowActivator, WindowEnumerator
from orcshot.core.cursor_capture import cursor_shape_for_capture
from orcshot.core.geometry import Rect
from orcshot.ui.cairo_convert import numpy_to_cairo_surface
from orcshot.ui.capture_modes import should_capture_cursor
from orcshot.ui.monitor_window import MonitorWindow, create_monitor_windows, destroy_all, queue_draw_all
from orcshot.ui.region_select_wayland import _rect_in_monitor_local
from orcshot.ui.render import render_cursor
from orcshot.ui.window_picker import _DIM_ALPHA, _SELECTION_BORDER


class WaylandWindowPicker:
    def __init__(
        self, capture_backend: CaptureBackend, window_enumerator: WindowEnumerator, on_window_selected,
        on_cancelled=None, capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
        window_activator: WindowActivator = None,
    ):
        self._on_window_selected = on_window_selected
        self._on_cancelled = on_cancelled
        self._capture_backend = capture_backend
        self._window_activator = window_activator

        layout = capture_backend.screen_layout()
        self._bounds = layout.virtual_bounds
        self._frozen_image = capture_backend.grab(self._bounds)
        self._windows_info = [w for w in window_enumerator.list_windows() if not w.is_minimized]
        self._hovered = None

        self._cursor_snapshot = None
        self._cursor_preview_shape = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from orcshot.capture.cursor import default_cursor_backend

                cursor_backend = default_cursor_backend()
            if cursor_backend is not None:
                self._cursor_snapshot = cursor_backend.cursor_snapshot()
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, capture_rect=self._bounds,
            )
            if shape is not None:
                b = shape.bounds
                absolute_bounds = Rect(
                    b.left + self._bounds.left, b.top + self._bounds.top,
                    b.right + self._bounds.left, b.bottom + self._bounds.top,
                )
                shape = replace(shape, bounds=absolute_bounds)
            self._cursor_preview_shape = shape
        self._cursor_visible = self._cursor_snapshot is not None

        self._monitor_images = {}
        self._surfaces = {}
        for index, monitor in enumerate(layout.monitors):
            top = monitor.bounds.top - self._bounds.top
            left = monitor.bounds.left - self._bounds.left
            image_slice = self._frozen_image[top:top + monitor.bounds.height, left:left + monitor.bounds.width]
            self._monitor_images[index] = image_slice
            self._surfaces[index] = numpy_to_cairo_surface(image_slice)

        self._monitor_windows = create_monitor_windows(
            layout.monitors,
            on_draw=self._on_draw,
            on_motion=self._on_motion,
            on_button_press=self._on_button_press,
            on_key_press=self._on_key_press,
        )
        self._window_index = {window: index for index, window in enumerate(self._monitor_windows)}

    def show(self) -> None:
        for window in self._monitor_windows:
            window.show_fullscreen()

    def _window_at(self, global_x: int, global_y: int):
        # Last match wins, matching window_picker.py's own stacking-
        # order contract (list_windows() returns bottom-to-top).
        match = None
        for info in self._windows_info:
            if info.bounds.contains(global_x, global_y):
                match = info
        return match

    def _on_draw(self, window: MonitorWindow, ctx) -> None:
        index = self._window_index[window]
        ctx.set_source_surface(self._surfaces[index], 0, 0)
        ctx.paint()

        local_hover = _rect_in_monitor_local(self._hovered.bounds, window.monitor_bounds) if self._hovered else None

        ctx.save()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(0, 0, window.monitor_bounds.width, window.monitor_bounds.height)
        if local_hover is not None:
            ctx.rectangle(local_hover.left, local_hover.top, local_hover.width, local_hover.height)
        ctx.set_source_rgba(0, 0, 0, _DIM_ALPHA)
        ctx.fill()
        ctx.restore()

        if local_hover is not None:
            ctx.save()
            ctx.set_source_rgb(*_SELECTION_BORDER)
            ctx.set_line_width(2)
            ctx.rectangle(local_hover.left, local_hover.top, local_hover.width, local_hover.height)
            ctx.stroke()
            ctx.restore()

        if self._cursor_visible and self._cursor_preview_shape is not None:
            local_bounds = _rect_in_monitor_local(self._cursor_preview_shape.bounds, window.monitor_bounds)
            if local_bounds is not None:
                render_cursor(ctx, replace(self._cursor_preview_shape, bounds=local_bounds))

    def _on_motion(self, global_x: int, global_y: int) -> None:
        hovered = self._window_at(global_x, global_y)
        if hovered is not self._hovered:
            self._hovered = hovered
            queue_draw_all(self._monitor_windows)

    def _on_button_press(self, global_x: int, global_y: int) -> None:
        hovered = self._hovered

        if hovered is None:
            destroy_all(self._monitor_windows)
            if self._on_cancelled is not None:
                self._on_cancelled()
            return

        clamped = hovered.bounds.intersect(self._bounds)
        if clamped is None:
            destroy_all(self._monitor_windows)
            if self._on_cancelled is not None:
                self._on_cancelled()
            return

        # Same anchor-window handoff as region_select_wayland.py - see
        # destination_picker.py's anchor_window docstring for why.
        anchor_window = None
        anchor_local_pos = None
        for window in self._monitor_windows:
            if window.monitor_bounds.contains(global_x, global_y):
                anchor_window = window
                anchor_local_pos = window.to_local(global_x, global_y)
                break
        for window in self._monitor_windows:
            if window is not anchor_window:
                window.destroy()

        top = clamped.top - self._bounds.top
        left = clamped.left - self._bounds.left
        placeholder = self._frozen_image[top:top + clamped.height, left:left + clamped.width]

        cursor_shape = None
        if self._cursor_visible and self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            cursor_shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, clamped,
            )

        def refresh_image():
            # No portable way to know which window is really topmost
            # under Wayland (see capture/window.py's WindowActivator
            # docstring) - force the clicked window to the front, then
            # grab it fresh, rather than trusting the frozen backdrop
            # placeholder, which may be showing an occluded window's
            # stale content. Same logic as window_picker.py's X11-
            # hosted WindowPickerWindow, proven live with the bundled
            # window-calls extension (task #69) - just deferred to
            # menu-item-click time rather than done inline here (see
            # destination_picker.py's refresh_image docstring for why).
            self._window_activator.activate(hovered.window_id)
            # 0.15s, matching window_picker.py's X11-hosted
            # WindowPickerWindow - confirmed live (briefly stretched to
            # 2s for direct visual verification, then reverted here)
            # that the raise genuinely happens, just too fast to
            # perceive normally at this timing.
            time.sleep(0.15)
            return self._capture_backend.grab(clamped)

        # The menu popup itself must happen synchronously, right here,
        # in direct response to this button-press-event - see
        # destination_picker.py's refresh_image docstring for the full
        # reasoning (confirmed live both ways: deferring this whole
        # call broke the popup; calling the portal refresh inline here
        # instead hung indefinitely).
        self._on_window_selected(
            placeholder, hovered, cursor_shape,
            anchor_monitor_window=anchor_window, anchor_local_pos=anchor_local_pos,
            refresh_image=refresh_image if self._window_activator is not None else None,
        )

    def _on_key_press(self, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            destroy_all(self._monitor_windows)
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        return False
