"""Region-select entry point for Wayland/GNOME sessions where the
bundled greenshot-linux-clipboard extension's capture interface is
available - see that extension's extension.js docstring and
REQUIREMENTS.md's Shell-side rewrite section (task #77) for the full
architecture and rationale.

Unlike region_select_wayland.py's WaylandRegionSelect (this module's
fallback when the extension isn't available), the *entire* interaction
- frozen backdrop, drag-to-select, dim-outside-selection, Escape-to-
cancel, and the post-capture destination picker - runs inside the
Shell/Mutter compositor process as one continuous flow. No client
window is ever created for any of it. Python only finds out once a
destination has already been chosen (or the whole thing was cancelled)
and just executes that one action via
ui/destination_picker.py's dispatch_destination - it builds no picker
UI of its own for this path at all.

This design followed directly from three related bugs live-verified
this session with the previous (client-anchored-picker) approach, all
sharing the same root cause - a real, separate client window
(however small/invisible) briefly existing for the picker phase: a
window-list icon flashing in the dock, the dock itself blinking, and
the selection overlay's dim backdrop staying visible while the picker
tried (and, past the very first capture, silently failed) to appear.
See extension.js's own docstring for the deeper reason a client-side
Gtk.Menu popup couldn't work here at all past the first call - a real
Wayland protocol restriction (popups need a live client input-event
serial to be created), not something fixable with another window/
timing trick.
"""

from __future__ import annotations

from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.capture.gnome_region_select import start_region_select
from greenshot_linux.core.cursor_capture import cursor_shape_for_capture
from greenshot_linux.core.geometry import Rect
from greenshot_linux.ui.capture_modes import should_capture_cursor


class GnomeShellRegionSelect:
    def __init__(
        self, on_captured=None, on_cancelled=None,
        capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
    ):
        self._on_captured = on_captured
        self._on_cancelled = on_cancelled

        # Same pre-interaction sampling timing as RegionSelectWindow/
        # WaylandRegionSelect - see their own __init__ docstrings for
        # the Windows-parity rationale (CaptureHelper.cs samples the
        # cursor before the interactive form is even shown).
        self._cursor_snapshot = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from greenshot_linux.capture.x11_cursor import X11CursorBackend

                cursor_backend = X11CursorBackend()
            self._cursor_snapshot = cursor_backend.cursor_snapshot()

    def show(self) -> None:
        start_region_select(self._on_selected, self._on_cancelled)

    def _on_selected(self, image, absolute_rect: Rect, destination: str) -> None:
        if self._on_captured is not None:
            self._on_captured(absolute_rect)

        cursor_shape = None
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            cursor_shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, absolute_rect,
            )

        from greenshot_linux.ui.destination_picker import dispatch_destination

        dispatch_destination(destination, image, cursor_shape)
