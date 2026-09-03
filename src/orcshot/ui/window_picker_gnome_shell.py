"""Window-picker entry point for Wayland/GNOME sessions where the
bundled orcshot-clipboard extension's capture interface is
available - the window-picker counterpart to
ui/region_select_gnome_shell.py (see that module's own docstring for
the shared architecture/rationale, task #77). The *entire* interaction
- frozen backdrop, hover-highlight over real window geometry, click-
to-select + raise, and the post-capture destination picker - runs
inside the Shell/Mutter compositor process as one continuous flow, the
same way region-select's does. Python only finds out once a
destination has already been chosen (or the whole thing was
cancelled) and just executes that one action via
ui/destination_picker.py's dispatch_destination.

Unlike ui/window_picker_wayland.py's WaylandWindowPicker (this
module's fallback when the extension isn't available), no bundled
window-calls extension/D-Bus round trip is needed for window
enumeration or activation at all - the Shell-side overlay reaches
Shell's own native `global.get_window_actors()`/`Meta.Window` API
directly now that the caller is Shell-side too (see extension.js's
own WindowPickerOverlay for the details) - the "worth checking during
implementation" note in REQUIREMENTS.md's original task #77 plan
panned out here the same way it did for region-select's backdrop
capture.
"""

from __future__ import annotations

from orcshot.capture.cursor import CursorBackend
from orcshot.capture.gnome_window_picker import start_window_picker
from orcshot.core.cursor_capture import cursor_shape_for_capture
from orcshot.core.geometry import Rect
from orcshot.ui.capture_modes import should_capture_cursor


class GnomeShellWindowPicker:
    def __init__(
        self, on_captured=None, on_cancelled=None,
        capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
    ):
        self._on_captured = on_captured
        self._on_cancelled = on_cancelled

        # Same pre-interaction sampling timing as WindowPickerWindow/
        # WaylandWindowPicker - see their own __init__ docstrings.
        self._cursor_snapshot = None
        if should_capture_cursor(capture_mouse_cursor):
            if cursor_backend is None:
                from orcshot.capture.cursor import default_cursor_backend

                cursor_backend = default_cursor_backend()
            if cursor_backend is not None:
                self._cursor_snapshot = cursor_backend.cursor_snapshot()

    def show(self) -> None:
        start_window_picker(self._on_selected, self._on_cancelled)

    def _on_selected(self, image, absolute_rect: Rect, destination: str, title: str = "") -> None:
        if self._on_captured is not None:
            self._on_captured(absolute_rect)

        cursor_shape = None
        if self._cursor_snapshot is not None:
            snap = self._cursor_snapshot
            cursor_shape = cursor_shape_for_capture(
                snap.image, snap.x, snap.y, snap.hotspot_x, snap.hotspot_y, absolute_rect,
            )

        from orcshot.ui.destination_picker import dispatch_destination

        dispatch_destination(destination, image, cursor_shape, title=title)
