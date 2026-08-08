"""The eyedropper / pick-a-color-from-anywhere-on-screen tool used by
the color dialog (ui/color_dialog.py) - based on Greenshot.Editor.
Controls.Pipette + MovableShowColorForm (Pipette.cs, MovableShowColor
Form.cs), with one deliberate interaction change from the Windows
original: click the eyedropper control to open a fullscreen picking
overlay, then a *separate* press-drag-release anywhere on screen (not
confined to the color dialog's own window) samples and commits a
color, with a small magnified preview following the cursor during the
drag; Escape cancels.

Windows' Pipette.cs (Pipette.cs:111-136) instead does one continuous
press-hold-drag-release starting on the eyedropper control itself, via
Win32's SetCapture - the OS redirects that whole in-progress gesture to
a different window for its duration. X11 supports the same trick via
Gdk.Seat.grab() tied to the triggering press event (confirmed live,
still used to grab keyboard below), but Wayland's Gdk.Seat.grab() does
not do this for a plain Gtk.WindowType.TOPLEVEL target - confirmed live
(motion/release events kept going to the original button, not the
overlay, however the grab was configured). Rather than have the two
platforms behave differently, this project deliberately unifies both
on the two-step version - also closer to how most other eyedropper
implementations behave anyway, not just a Wayland workaround.

Reuses capture.backend.CaptureBackend.grab() for reading pixel data -
the same real X11 mechanism every capture mode already uses, just a
tiny patch instead of a full region - and ui/magnifier.py's existing
draw_magnifier for the magnified preview, the same one region_select.py's
capture overlay already uses. No new pixel-reading path.

Not unit tested for the same reason region_select.py/window_picker.py
aren't: GTK event-loop glue with no meaningful headless test. Verified
live with FakeCaptureBackend synthetic content wherever possible - see
REQUIREMENTS.md's "Color picker" section.
"""

from __future__ import annotations

import os

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
    """A fullscreen, invisible (transparent) POPUP that appears when
    the eyedropper control is clicked and stays up for one subsequent
    press-drag-release gesture - same POPUP/override-redirect
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
        self._dragging = False
        self._patch = None
        self._patch_cursor = None
        self._current_color = None
        self._cursor_local = None

        self.set_app_paintable(True)
        self.set_keep_above(True)
        self.move(self._bounds.left, self._bounds.top)
        self.resize(self._bounds.width, self._bounds.height)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
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

    def _on_button_press(self, widget, event):
        self._dragging = True
        self._sample(int(event.x), int(event.y))
        widget.queue_draw()
        return True

    def _on_motion(self, widget, event):
        if not self._dragging:
            return True
        self._sample(int(event.x), int(event.y))
        widget.queue_draw()
        return True

    def _on_draw(self, widget, ctx):
        if self._patch is None or self._cursor_local is None:
            return False
        draw_magnifier(
            ctx, self._patch, self._patch_cursor, _LOUPE_OFFSET, _LOUPE_DIAMETER,
            source_size=_PATCH_SIZE, dest_pos=self._cursor_local,
        )
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
    on_picked,
    on_cancelled=None,
    capture_backend: CaptureBackend = None,
) -> None:
    """Call from the eyedropper control's "clicked" handler - shows a
    fullscreen picking overlay; the actual color sample happens via a
    fresh press-drag-release *within* that overlay afterward, not a
    continuation of the triggering click (see this module's docstring
    for why).

    Under Wayland, delegates to _WaylandEyedropperOverlay (a
    per-monitor multi-window overlay - see
    ui/eyedropper_wayland.py's module docstring for why, and for the
    one thing that's genuinely unverified there: cross-monitor
    dragging).
    """
    if capture_backend is None:
        from greenshot_linux.capture.backend_select import default_capture_backend

        capture_backend = default_capture_backend()

    # color_dialog.py's only caller shows this via Gtk.Dialog.run(),
    # which holds a GTK-level modal grab (gtk_grab_add) for its whole
    # duration - independent of window-manager/compositor focus and
    # independent of any window-system-level device grab. Confirmed
    # live under Wayland: the new overlay window had real compositor
    # focus (GNOME Shell's own window list reported focus:true for it)
    # yet no click or keypress ever reached it - GTK's own event
    # dispatcher was redirecting everything back to the dialog, the
    # current grab widget, regardless. Released for the eyedropper's
    # duration and restored once it's done, on both platforms - this
    # is a GTK concept, not an X11/Wayland one, and X11's previous
    # explicit pointer grab likely only masked the same underlying
    # issue rather than needing a genuinely different mechanism.
    suspended_grab = Gtk.grab_get_current()
    if suspended_grab is not None:
        suspended_grab.grab_remove()

    def restore_grab() -> None:
        if suspended_grab is not None:
            suspended_grab.grab_add()

    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        from greenshot_linux.ui.eyedropper_wayland import _WaylandEyedropperOverlay

        # Destroying the fullscreened overlay windows doesn't reliably
        # hand focus/stacking prominence back to the color dialog on
        # its own under this GNOME/Wayland session - confirmed live,
        # the dialog appeared to vanish (fell behind the editor window)
        # even though apply_color() was being called correctly.
        # present() explicitly restores it.
        toplevel = trigger_widget.get_toplevel()

        def refocused_picked(color):
            restore_grab()
            on_picked(color)
            if isinstance(toplevel, Gtk.Window):
                toplevel.present()

        def refocused_cancelled():
            restore_grab()
            if on_cancelled is not None:
                on_cancelled()
            if isinstance(toplevel, Gtk.Window):
                toplevel.present()

        wayland_overlay = _WaylandEyedropperOverlay(capture_backend, refocused_picked, refocused_cancelled)
        wayland_overlay.show()
        return

    def unwound_picked(color):
        restore_grab()
        on_picked(color)

    def unwound_cancelled():
        restore_grab()
        if on_cancelled is not None:
            on_cancelled()

    overlay = _EyedropperOverlay(capture_backend, unwound_picked, unwound_cancelled)
    overlay.show_all()
    seat = Gdk.Display.get_default().get_default_seat()
    # KEYBOARD only, not ALL: the sampling gesture now starts fresh on
    # the overlay itself (already topmost, covering the whole screen),
    # which receives its own press/motion/release events naturally, no
    # pointer grab needed. Keyboard still needs an explicit grab
    # because this is a POPUP (override-redirect) window, which never
    # gets real X keyboard focus through the window manager on its own
    # - see region_select.py's start_region_capture for how that was
    # confirmed empirically. Not tied to a specific triggering event
    # since there's no gesture-in-progress to redirect anymore.
    seat.grab(overlay.get_window(), Gdk.SeatCapabilities.KEYBOARD, False, None, None, None)
