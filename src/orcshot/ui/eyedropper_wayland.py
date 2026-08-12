"""Wayland-specific eyedropper overlay: same UX as eyedropper.py's
_EyedropperOverlay - built from N per-monitor fullscreen windows
instead of one POPUP, for the same reason as
region_select_wayland.py/window_picker_wayland.py.

Unlike X11's version, this one is NOT actually transparent: it paints
a frozen backdrop, grabbed once up front, exactly like region-select
and window-picker already do - see REQUIREMENTS.md's eyedropper
section for why. Confirmed live that genuine window transparency does
not survive fullscreen_on_monitor() under this GNOME/Mutter session at
all (solid black instead, regardless of RGBA visual or an explicit
empty opaque-region hint) - this is Mutter's own documented, deliberate
policy (forcing fullscreen surfaces opaque for scanout-performance
reasons - see the Mutter/Ubuntu bug trackers), not something fixable
from client code, and the protocol that *would* give real transparency
(wlr-layer-shell) is explicitly not implemented by Mutter.

Consequence: colour is sampled from that same frozen image throughout
the whole drag, not re-grabbed live per motion event the way X11's
_EyedropperOverlay._sample() does - a fresh portal round trip on every
mouse-move would be far too slow for a smooth drag anyway. This means
the picked colour reflects screen content at the moment the drag
*started*, not the moment of release (e.g. a hover-state colour change
under the cursor wouldn't be reflected) - see REQUIREMENTS.md for the
full user-facing writeup of this tradeoff.

No pointer or keyboard grab needed at all, unlike an earlier version of
this module: the sampling gesture is a fresh press-drag-release that
starts *within* the overlay itself (see eyedropper.py's module
docstring for why - Gdk.Seat.grab() doesn't redirect an in-progress
gesture from a different window to a plain TOPLEVEL target under
Wayland, confirmed live), so each MonitorWindow just receives its own
press/motion/release events naturally, exactly like region-select and
window-picker already do. Keyboard focus is likewise natural on
mapping - same as those two.

NOT independently verified for cross-monitor dragging: this project's
only Wayland test hardware has a single monitor (see
[[reference-virtualbox-vm-testing]] in memory) - if motion events
don't hand off correctly once the cursor crosses from one
MonitorWindow onto a neighboring one mid-drag, dragging across a
monitor boundary may lose tracking there, even though it works
correctly within a single monitor either way.

The frozen-backdrop portal grab is deferred via GLib.idle_add, not
done inline in __init__: __init__ runs synchronously from the
eyedropper control's own "clicked" handler (see start_eyedropper's
docstring), and calling the portal - its own nested GLib.MainLoop -
directly from inside that handler hangs indefinitely, confirmed live
(same reentrancy problem window_picker_wayland.py hit first; see its
module docstring for the full diagnosis). The overlay windows are
still shown synchronously in show() - they just don't have a backdrop
to paint yet until the deferred callback fills one in a moment later.
Because that callback isn't scoped to whichever main loop was active
when it was scheduled (it can still be pending when a fast pick tears
this overlay down), it checks self._alive before touching anything -
confirmed live as a real failure mode otherwise (a cascade of
Gtk-CRITICAL "assertion 'GTK_IS_WIDGET' failed" errors from operating
on already-destroyed MonitorWindows).
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib

from orcshot.capture.backend import CaptureBackend
from orcshot.ui.cairo_convert import numpy_to_cairo_surface
from orcshot.ui.eyedropper import _LOUPE_DIAMETER, _LOUPE_OFFSET, _PATCH_SIZE, _clamped_patch_rect
from orcshot.ui.magnifier import draw_magnifier
from orcshot.ui.monitor_window import MonitorWindow, create_monitor_windows, destroy_all


class _WaylandEyedropperOverlay:
    def __init__(self, capture_backend: CaptureBackend, on_picked, on_cancelled=None):
        self._capture_backend = capture_backend
        self._on_picked = on_picked
        self._on_cancelled = on_cancelled
        self._layout = capture_backend.screen_layout()
        self._bounds = self._layout.virtual_bounds
        self._frozen_image = None
        self._surfaces = {}
        self._dragging = False
        self._patch = None
        self._patch_cursor = None
        self._current_color = None
        self._cursor_global = None
        # See this module's docstring: _load_backdrop's idle_add can
        # still be pending when a fast pick tears this overlay down,
        # and isn't scoped to any particular main loop - checked at
        # the top of _load_backdrop before it touches anything.
        self._alive = True

        self._monitor_windows = create_monitor_windows(
            self._layout.monitors,
            on_draw=self._on_draw,
            on_motion=self._on_motion,
            on_button_press=self._on_button_press,
            on_button_release=self._on_button_release,
            on_key_press=self._on_key_press,
        )
        self._window_index = {window: index for index, window in enumerate(self._monitor_windows)}

    def show(self) -> None:
        """Shows every per-monitor window; the frozen backdrop itself
        loads a moment later - see this module's docstring."""
        for window in self._monitor_windows:
            window.show_fullscreen()
        # PRIORITY_DEFAULT, not idle_add's default PRIORITY_DEFAULT_IDLE:
        # confirmed live that the default (lower) priority let this
        # callback get starved indefinitely by the continuous stream of
        # motion events fired throughout an active drag - it only ever
        # ran once something (e.g. a keypress) briefly interrupted that
        # stream. Competing at normal event priority instead of pure
        # idle priority avoids that starvation.
        GLib.idle_add(self._load_backdrop, priority=GLib.PRIORITY_DEFAULT)

    def _load_backdrop(self) -> bool:
        if not self._alive:
            return False
        try:
            self._frozen_image = self._capture_backend.grab(self._bounds)
            for index, monitor in enumerate(self._layout.monitors):
                top = monitor.bounds.top - self._bounds.top
                left = monitor.bounds.left - self._bounds.left
                image_slice = self._frozen_image[top:top + monitor.bounds.height, left:left + monitor.bounds.width]
                self._surfaces[index] = numpy_to_cairo_surface(image_slice)
            for window in self._monitor_windows:
                window.queue_draw()
        except Exception:
            import sys
            import traceback

            print("[eyedropper_wayland] exception in _load_backdrop:", file=sys.stderr, flush=True)
            traceback.print_exc()
        return False  # GLib.idle_add: run once, don't repeat

    def _sample(self, global_x: int, global_y: int) -> None:
        # Sliced from the frozen image, not a fresh capture_backend.grab()
        # - see this module's docstring for why (no live per-motion
        # portal round trip; the picked colour reflects drag-start, not
        # release). Guarded: the backdrop loads asynchronously (see
        # _load_backdrop) and may not have arrived yet on the very
        # first motion events of a fast drag.
        if self._frozen_image is None:
            return
        rect, cursor_in_patch = _clamped_patch_rect(global_x, global_y, _PATCH_SIZE, self._bounds)
        top = rect.top - self._bounds.top
        left = rect.left - self._bounds.left
        self._patch = self._frozen_image[top:top + rect.height, left:left + rect.width]
        self._patch_cursor = cursor_in_patch
        self._current_color = tuple(self._patch[cursor_in_patch[1], cursor_in_patch[0]])
        self._cursor_global = (global_x, global_y)

    def _on_button_press(self, global_x: int, global_y: int) -> None:
        self._dragging = True
        self._sample(global_x, global_y)
        for window in self._monitor_windows:
            window.queue_draw()

    def _on_motion(self, global_x: int, global_y: int) -> None:
        if not self._dragging:
            return
        self._sample(global_x, global_y)
        for window in self._monitor_windows:
            window.queue_draw()

    def _on_draw(self, window: MonitorWindow, ctx) -> None:
        index = self._window_index[window]
        surface = self._surfaces.get(index)
        if surface is not None:
            ctx.set_source_surface(surface, 0, 0)
            ctx.paint()

        if self._patch is None or self._cursor_global is None:
            return
        if not window.monitor_bounds.contains(*self._cursor_global):
            return
        local_x, local_y = window.to_local(*self._cursor_global)
        draw_magnifier(
            ctx, self._patch, self._patch_cursor, _LOUPE_OFFSET, _LOUPE_DIAMETER,
            source_size=_PATCH_SIZE, dest_pos=(local_x, local_y),
        )
        r, g, b, a = self._current_color
        text = f"#{r:02X}{g:02X}{b:02X}"
        x, y = local_x + _LOUPE_OFFSET[0], local_y + _LOUPE_OFFSET[1] + _LOUPE_DIAMETER + 4
        ctx.save()
        ctx.select_font_face("sans-serif")
        ctx.set_font_size(13)
        extents = ctx.text_extents(text)
        pad = 4
        ctx.set_source_rgba(0, 0, 0, 0.75)
        ctx.rectangle(x - pad, y - extents.height - pad, extents.width + 2 * pad, extents.height + 2 * pad)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to(x, y)
        ctx.show_text(text)
        ctx.restore()

    def _on_button_release(self, global_x: int, global_y: int) -> None:
        self._alive = False
        destroy_all(self._monitor_windows)
        if self._current_color is not None:
            self._on_picked(self._current_color)
        elif self._on_cancelled is not None:
            self._on_cancelled()

    def _on_key_press(self, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self._alive = False
            destroy_all(self._monitor_windows)
            if self._on_cancelled is not None:
                self._on_cancelled()
            return True
        return False
