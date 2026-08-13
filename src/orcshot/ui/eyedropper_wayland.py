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

import cairo
import gi
import math

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib

from orcshot.capture.backend import CaptureBackend
from orcshot.ui.cairo_convert import numpy_to_cairo_surface
from orcshot.ui.eyedropper import _LOUPE_DIAMETER, _LOUPE_OFFSET, _PATCH_SIZE, _clamped_patch_rect
from orcshot.ui.magnifier import draw_magnifier
from orcshot.ui.monitor_window import MonitorWindow, create_monitor_windows, destroy_all


def _union_rect(a, b):
    """The smallest (x, y, w, h) rect covering both ``a`` and ``b`` -
    ``a`` may be None (nothing to union with yet). See
    _redraw_loupe's own docstring for why this exists: one combined
    invalidated region per window per frame, not two separate ones."""
    if a is None:
        return b
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x = min(ax, bx)
    y = min(ay, by)
    return x, y, max(ax + aw, bx + bw) - x, max(ay + ah, by + bh) - y


class _WaylandEyedropperOverlay:
    def __init__(self, capture_backend: CaptureBackend, on_picked, on_cancelled=None):
        self._capture_backend = capture_backend
        self._on_picked = on_picked
        self._on_cancelled = on_cancelled
        self._layout = capture_backend.screen_layout()
        self._bounds = self._layout.virtual_bounds
        self._frozen_image = None
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
        # Task #84 - see _redraw_loupe's own docstring: the last
        # invalidated loupe+swatch rect per window, so the next redraw
        # only repaints where content actually changed instead of the
        # whole fullscreen backdrop.
        self._last_draw_rect: dict = {}

        self._monitor_windows = create_monitor_windows(
            self._layout.monitors,
            on_draw=self._on_draw,
            on_motion=self._on_motion,
            on_button_press=self._on_button_press,
            on_button_release=self._on_button_release,
            on_key_press=self._on_key_press,
        )

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
        self._redraw_loupe()

    def _on_motion(self, global_x: int, global_y: int) -> None:
        if not self._dragging:
            return
        self._sample(global_x, global_y)
        self._redraw_loupe()

    # Loupe+swatch bounding box, relative to dest_pos - generously
    # padded rather than measured exactly against the real text (which
    # would need a scratch Cairo context just to call text_extents
    # before the actual draw), sized to comfortably cover
    # _LOUPE_OFFSET+_LOUPE_DIAMETER (18+80) plus the color-hex swatch
    # drawn below it. See _redraw_loupe's docstring for why this exists.
    _LOUPE_REGION_MARGIN = 2
    _LOUPE_REGION_SIZE = 124

    def _redraw_loupe(self) -> None:
        """Task #84 (originally task #71's own follow-up note): every
        motion event used to call plain queue_draw() on every monitor
        window, invalidating (and forcing a full backdrop re-blit +
        loupe redraw for) the *entire* fullscreen surface on every
        single frame, even though only a small region around the
        cursor actually changes - the documented leading hypothesis for
        the directional flicker/shearing reported on fast drags,
        especially under a software-rendered compositor (this project's
        only Wayland test hardware). Fixed by invalidating just the
        loupe+swatch's own region via queue_draw_area instead of the
        whole window - GTK/Cairo automatically clips _on_draw's
        painting to whatever region was actually invalidated, so
        _on_draw itself needed no changes. For the window currently
        under the cursor, the old (last-drawn) and new rects are
        unioned into a single queue_draw_area call (_union_rect) rather
        than two separate ones - under fast movement those two rects
        often don't overlap, and a single combined region removes
        "two distinct damage regions composited into the same frame"
        as a variable while chasing directional tearing that persisted
        even after this fix (still open, still task #84). Every other
        window's stale old rect (if any, e.g. right after the cursor
        crosses from one monitor to another) still gets cleared on its
        own so a leftover loupe doesn't linger there.
        """
        active_window = None
        if self._cursor_global is not None:
            for window in self._monitor_windows:
                if window.monitor_bounds.contains(*self._cursor_global):
                    active_window = window
                    break

        for window in self._monitor_windows:
            old_rect = self._last_draw_rect.get(window)
            if window is active_window:
                local_x, local_y = window.to_local(*self._cursor_global)
                new_rect = (
                    local_x - self._LOUPE_REGION_MARGIN, local_y - self._LOUPE_REGION_MARGIN,
                    self._LOUPE_REGION_SIZE, self._LOUPE_REGION_SIZE,
                )
                # One combined queue_draw_area call per window, not two
                # separate ones (erase-old, draw-new) - under fast
                # movement those two rects usually don't overlap, so
                # each frame would be composited from two distinct
                # damage regions instead of one. Collapsing to a single
                # bounding rect removes that as a variable while
                # digging into task #84's directional tearing.
                window.queue_draw_area(*_union_rect(old_rect, new_rect))
                self._last_draw_rect[window] = new_rect
            elif old_rect is not None:
                window.queue_draw_area(*old_rect)
                self._last_draw_rect[window] = None

    def _build_loupe_surface(self) -> cairo.ImageSurface:
        """Pre-composites the magnified circle, its ring, crosshair,
        and color swatch onto a small off-screen buffer in one
        self-contained pass - entirely in memory, no interaction with
        the real window. Tried while digging into task #84's
        directional tearing after two other real, measured
        improvements (region-size reduction, single-damage-region
        collapsing in _redraw_loupe) still left it only reduced, not
        eliminated: this reduces _on_draw's own work against the real
        window to a single small blit for all of this, instead of
        five-plus separate Cairo operations (arc-clip+paint, ring
        stroke, two crosshair lines, swatch rectangle+text) each
        landing directly on the window's own backing surface, any one
        of which could be the actual boundary where a partial/torn
        frame gets caught under this compositor.
        """
        size = self._LOUPE_REGION_SIZE
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        ctx = cairo.Context(surface)
        origin = (self._LOUPE_REGION_MARGIN, self._LOUPE_REGION_MARGIN)
        draw_magnifier(
            ctx, self._patch, self._patch_cursor, _LOUPE_OFFSET, _LOUPE_DIAMETER,
            source_size=_PATCH_SIZE, dest_pos=origin,
        )
        r, g, b, a = self._current_color
        text = f"#{r:02X}{g:02X}{b:02X}"
        x = origin[0] + _LOUPE_OFFSET[0]
        y = origin[1] + _LOUPE_OFFSET[1] + _LOUPE_DIAMETER + 4
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
        return surface

    def _on_draw(self, window: MonitorWindow, ctx) -> None:
        # Slices only the actually-invalidated region straight out of
        # the raw frozen pixels, instead of painting (even if clipped)
        # from one big cached per-monitor surface covering the whole
        # window - another lever tried while digging into task #84's
        # directional tearing, on top of the region-size/single-region/
        # pre-composited-loupe fixes above: every per-frame operation
        # now touches genuinely small data end to end, nothing sized to
        # the full monitor at all. ctx.clip_extents() reads back
        # exactly the rectangle GTK already invalidated for this draw
        # (the whole window on the very first paint after
        # _load_backdrop, a small queue_draw_area rect on every
        # subsequent one) - no need to track or guess it separately.
        if self._frozen_image is not None:
            cx1, cy1, cx2, cy2 = ctx.clip_extents()
            left = max(0, int(cx1))
            top = max(0, int(cy1))
            right = min(window.monitor_bounds.width, int(math.ceil(cx2)))
            bottom = min(window.monitor_bounds.height, int(math.ceil(cy2)))
            if right > left and bottom > top:
                global_left, global_top = window.to_global(left, top)
                src_left = global_left - self._bounds.left
                src_top = global_top - self._bounds.top
                slice_ = self._frozen_image[src_top:src_top + (bottom - top), src_left:src_left + (right - left)]
                if slice_.shape[0] > 0 and slice_.shape[1] > 0:
                    ctx.set_source_surface(numpy_to_cairo_surface(slice_), left, top)
                    ctx.paint()

        if self._patch is None or self._cursor_global is None:
            return
        if not window.monitor_bounds.contains(*self._cursor_global):
            return
        local_x, local_y = window.to_local(*self._cursor_global)
        loupe_surface = self._build_loupe_surface()
        ctx.set_source_surface(
            loupe_surface, local_x - self._LOUPE_REGION_MARGIN, local_y - self._LOUPE_REGION_MARGIN,
        )
        ctx.paint()

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
