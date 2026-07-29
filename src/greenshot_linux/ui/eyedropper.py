"""The eyedropper / pick-a-color-from-anywhere-on-screen tool used by
the color dialog (ui/color_dialog.py) - faithful port of
Greenshot.Editor.Controls.Pipette + MovableShowColorForm
(Pipette.cs, MovableShowColorForm.cs): press-and-hold on the
eyedropper control, drag anywhere on screen (not confined to the
color dialog's own window), a small magnified preview follows the
cursor, release commits the color under the cursor, Escape cancels.

Reuses capture.backend.CaptureBackend.grab() for reading pixel data -
the same real X11 mechanism every capture mode already uses, just a
tiny patch instead of a full region - and ui/magnifier.py's existing
draw_magnifier for the magnified preview, the same one region_select.py's
capture overlay already uses. No new pixel-reading path.

Not unit tested for the same reason region_select.py/window_picker.py
aren't: GTK event-loop glue (a live pointer grab) with no meaningful
headless test. Verified live with FakeCaptureBackend synthetic content
wherever possible - see REQUIREMENTS.md's "Color picker" section.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.core.geometry import Rect
from greenshot_linux.ui.magnifier import draw_magnifier

_PATCH_SIZE = 25  # matches region_select.py's magnifier source_size default
_LOUPE_DIAMETER = 80
_LOUPE_OFFSET = (18, 18)


def _clamped_patch_rect(cursor_x: int, cursor_y: int, size: int, bounds: Rect):
    """A ``size`` x ``size`` rect around (cursor_x, cursor_y), clamped
    to stay fully within ``bounds`` (the cursor can be near a screen
    edge, where a naive centered rect would fall outside the virtual
    screen and CaptureBackend.grab would reject it) - plus where,
    within that rect, the cursor's own pixel actually landed.
    """
    half = size // 2
    left = max(bounds.left, min(cursor_x - half, bounds.right - size))
    top = max(bounds.top, min(cursor_y - half, bounds.bottom - size))
    rect = Rect(left, top, left + size, top + size)
    return rect, (cursor_x - left, cursor_y - top)


class _EyedropperOverlay(Gtk.Window):
    """A fullscreen, invisible (transparent) POPUP that appears for
    the duration of one eyedropper drag - same POPUP/override-redirect
    technique region_select.py/window_picker.py use for exact
    multi-monitor geometry, but with no visible backdrop of its own
    (the real desktop underneath is what the user is actually looking
    at while picking a color from it).
    """

    def __init__(self, capture_backend: CaptureBackend, on_picked, on_cancelled=None):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._capture_backend = capture_backend
        self._on_picked = on_picked
        self._on_cancelled = on_cancelled
        self._bounds = capture_backend.screen_layout().virtual_bounds
        self._patch = None
        self._patch_cursor = None
        self._current_color = None
        self._cursor_local = None

        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.move(self._bounds.left, self._bounds.top)
        self.resize(self._bounds.width, self._bounds.height)
        self.add_events(
            Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_button_release)
        self.connect("key-press-event", self._on_key_press)

    def _sample(self, local_x: int, local_y: int) -> None:
        abs_x, abs_y = local_x + self._bounds.left, local_y + self._bounds.top
        rect, cursor_in_patch = _clamped_patch_rect(abs_x, abs_y, _PATCH_SIZE, self._bounds)
        self._patch = self._capture_backend.grab(rect)
        self._patch_cursor = cursor_in_patch
        self._current_color = tuple(self._patch[cursor_in_patch[1], cursor_in_patch[0]])
        self._cursor_local = (local_x, local_y)

    def _on_motion(self, widget, event):
        self._sample(int(event.x), int(event.y))
        widget.queue_draw()
        return True

    def _on_draw(self, widget, ctx):
        if self._patch is None or self._cursor_local is None:
            return False
        draw_magnifier(ctx, self._patch, self._patch_cursor, _LOUPE_OFFSET, _LOUPE_DIAMETER, source_size=_PATCH_SIZE)
        r, g, b, a = self._current_color
        text = f"#{r:02X}{g:02X}{b:02X}"
        x, y = self._cursor_local[0] + _LOUPE_OFFSET[0], self._cursor_local[1] + _LOUPE_OFFSET[1] + _LOUPE_DIAMETER + 4
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
        return False

    def _on_button_release(self, widget, event):
        self._release_grab()
        self.destroy()
        if self._current_color is not None:
            self._on_picked(self._current_color)
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
        return False

    def _release_grab(self) -> None:
        Gdk.Display.get_default().get_default_seat().ungrab()


def start_eyedropper(
    trigger_widget: Gtk.Widget,
    press_event,
    on_picked,
    on_cancelled=None,
    capture_backend: CaptureBackend = None,
) -> None:
    """Call from the eyedropper button's own button-press-event
    handler, passing that same ``press_event`` through - a fullscreen
    overlay appears and a pointer grab redirects the in-progress
    drag's motion/release events to it (Gdk.Seat.grab, confirmed live
    to work for exactly this "press started on one widget, drag
    continues over a different window" case), so the drag can sample
    pixels anywhere on screen, not just within the small color dialog.
    """
    if capture_backend is None:
        from greenshot_linux.capture.x11 import X11CaptureBackend

        capture_backend = X11CaptureBackend()

    overlay = _EyedropperOverlay(capture_backend, on_picked, on_cancelled)
    overlay.show_all()
    seat = Gdk.Display.get_default().get_default_seat()
    seat.grab(overlay.get_window(), Gdk.SeatCapabilities.ALL_POINTING, False, None, press_event, None)
