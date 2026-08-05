"""The window-picker overlay: a fullscreen, borderless window showing
a frozen copy of the desktop, that highlights whichever window is
under the cursor as it moves and captures that window on click.
Escape (or clicking where no window is) cancels.

Structurally a sibling of region_select.py's RegionSelectWindow - same
frozen-backdrop-plus-even-odd-dim technique, same POPUP window type
for exact multi-monitor geometry (see region_select.py's module
docstring for why TOPLEVEL doesn't work) - but highlights a pre-known
window rect under the cursor instead of a free-form drag rectangle.

Hover picks the *last* matching window in WindowEnumerator.list_windows()'s
order when windows overlap - correct as long as list_windows() returns
windows in bottom-to-top stacking order, which is now a contract
enforced by test_window_enumerator_contract.py's
test_active_window_is_last_in_list_windows_stacking_order. This caught
a real bug during manual testing: X11WindowEnumerator originally read
_NET_CLIENT_LIST (the window manager's *unordered* window list, no
stacking guarantee) instead of _NET_CLIENT_LIST_STACKING (its actual
bottom-to-top paint order) - on a desktop with several maximized
windows sharing one monitor, hovering the occluded windows' shared
region picked whichever was last in the arbitrary client-list order,
not whichever was actually visible on top. Fixed in
capture/x11_window.py; see that module's docstring for the full story.

Not unit tested for the same reason region_select.py isn't: GTK glue
driving a live event loop and an on-screen window, with no meaningful
headless test. Verified by running it and inspecting real screenshots,
including a live interactive click against real overlapping/maximized
windows after the stacking-order fix.
"""

from __future__ import annotations

import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.capture.window import WindowActivator, WindowEnumerator
from greenshot_linux.core.cursor_capture import cursor_shape_for_capture
from greenshot_linux.core.geometry import Rect
from greenshot_linux.ui.cairo_convert import numpy_to_cairo_surface
from greenshot_linux.ui.capture_modes import should_capture_cursor
from greenshot_linux.ui.render import render_cursor

_SELECTION_BORDER = (0.1, 0.6, 1.0)
_DIM_ALPHA = 0.5


class WindowPickerWindow(Gtk.Window):
    def __init__(
        self, capture_backend: CaptureBackend, window_enumerator: WindowEnumerator, on_window_selected,
        on_cancelled=None, capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
        window_activator: WindowActivator = None,
    ):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._on_window_selected = on_window_selected
        self._on_cancelled = on_cancelled
        self._capture_backend = capture_backend
        self._window_activator = window_activator

        self._bounds = capture_backend.screen_layout().virtual_bounds
        self._frozen_image = capture_backend.grab(self._bounds)
        self._surface = numpy_to_cairo_surface(self._frozen_image)
        self._windows = [w for w in window_enumerator.list_windows() if not w.is_minimized]
        self._hovered = None

        # Same sampling/toggle scheme as region_select.py's
        # RegionSelectWindow - see that module's __init__ docstring.
        self._cursor_snapshot = None
        self._cursor_preview_shape = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from greenshot_linux.capture.x11_cursor import X11CursorBackend

                cursor_backend = X11CursorBackend()
            self._cursor_snapshot = cursor_backend.cursor_snapshot()
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            self._cursor_preview_shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y,
                capture_rect=Rect(self._bounds.left, self._bounds.top, self._bounds.right, self._bounds.bottom),
            )
        self._cursor_visible = self._cursor_snapshot is not None

        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.set_can_focus(True)
        self.move(self._bounds.left, self._bounds.top)
        self.resize(self._bounds.width, self._bounds.height)

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("key-press-event", self._on_key_press)

    def _local_rect(self, absolute: Rect) -> Rect:
        return Rect(
            absolute.left - self._bounds.left, absolute.top - self._bounds.top,
            absolute.right - self._bounds.left, absolute.bottom - self._bounds.top,
        )

    def _window_at_local(self, x: int, y: int):
        ax, ay = x + self._bounds.left, y + self._bounds.top
        match = None
        for window in self._windows:
            if window.bounds.contains(ax, ay):
                match = window
        return match

    def _on_draw(self, widget, ctx):
        ctx.set_source_surface(self._surface, 0, 0)
        ctx.paint()

        ctx.save()
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(0, 0, self._bounds.width, self._bounds.height)
        if self._hovered is not None:
            r = self._local_rect(self._hovered.bounds)
            ctx.rectangle(r.left, r.top, r.width, r.height)
        ctx.set_source_rgba(0, 0, 0, _DIM_ALPHA)
        ctx.fill()
        ctx.restore()

        if self._hovered is not None:
            r = self._local_rect(self._hovered.bounds)
            ctx.save()
            ctx.set_source_rgb(*_SELECTION_BORDER)
            ctx.set_line_width(2)
            ctx.rectangle(r.left, r.top, r.width, r.height)
            ctx.stroke()
            ctx.restore()

        if self._cursor_visible and self._cursor_preview_shape is not None:
            render_cursor(ctx, self._cursor_preview_shape)
        return False

    def _on_motion(self, widget, event):
        hovered = self._window_at_local(int(event.x), int(event.y))
        if hovered is not self._hovered:
            self._hovered = hovered
            widget.queue_draw()
        return True

    def _on_button_press(self, widget, event):
        hovered = self._hovered
        self._release_grab()
        self.destroy()
        if hovered is None:
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True

        absolute_rect = hovered.bounds.intersect(self._bounds)
        if absolute_rect is None:
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True

        if self._window_activator is not None:
            # No portable way to know which window is really topmost
            # under Wayland (see capture/window.py's WindowActivator
            # docstring) - force the clicked window to the front, then
            # grab it fresh, rather than trusting the frozen backdrop's
            # hover-highlight guess, which may be showing an occluded
            # window's stale content.
            self._window_activator.activate(hovered.window_id)
            time.sleep(0.15)
            cropped = self._capture_backend.grab(absolute_rect)
        else:
            local = self._local_rect(absolute_rect)
            cropped = self._frozen_image[local.top:local.bottom, local.left:local.right]

        cursor_shape = None
        if self._cursor_visible and self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            cursor_shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, absolute_rect,
            )
        self._on_window_selected(cropped, hovered, cursor_shape)
        return True

    def _on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self._release_grab()
            self.destroy()
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        if event.keyval in (Gdk.KEY_m, Gdk.KEY_M) and self._cursor_snapshot is not None:
            self._cursor_visible = not self._cursor_visible
            widget.queue_draw()
            return True
        return False

    def _release_grab(self) -> None:
        Gdk.Display.get_default().get_default_seat().ungrab()


def start_window_picker(
    capture_backend: CaptureBackend = None, window_enumerator: WindowEnumerator = None, on_captured=None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
    window_activator: WindowActivator = None,
) -> WindowPickerWindow:
    """Show the overlay and show the destination picker on whichever
    window gets clicked. Backends are injectable (for tests/fakes); the
    defaults construct the real adapters lazily so importing this
    module doesn't require a display. ``on_captured(absolute_rect)``,
    if given, fires right before the picker opens - GreenshotApplication
    uses this to remember the region for "repeat last region".
    """
    if capture_backend is None:
        from greenshot_linux.capture.backend_select import default_capture_backend

        capture_backend = default_capture_backend()
    if window_enumerator is None:
        from greenshot_linux.capture.backend_select import default_window_enumerator_and_activator

        window_enumerator, window_activator = default_window_enumerator_and_activator()

    def on_selected(image, window_info, cursor_shape):
        if on_captured is not None:
            on_captured(window_info.bounds)
        from greenshot_linux.ui.destination_picker import show_destination_picker

        show_destination_picker(image, cursor_shape=cursor_shape)

    window = WindowPickerWindow(
        capture_backend, window_enumerator, on_selected,
        capture_mouse_cursor=capture_mouse_cursor, cursor_backend=cursor_backend,
        window_activator=window_activator,
    )
    window.show_all()
    window.grab_focus()
    # See region_select.py's start_region_capture for why this explicit
    # keyboard grab is required - POPUP windows never get real X
    # keyboard focus from grab_focus() alone.
    Gdk.Display.get_default().get_default_seat().grab(
        window.get_window(), Gdk.SeatCapabilities.KEYBOARD, True, None, None, None, None,
    )
    return window
