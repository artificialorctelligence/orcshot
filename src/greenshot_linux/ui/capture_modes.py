"""The non-interactive capture triggers: full screen, active window,
and repeat-last-region. Region select (interactive drag) lives in
region_select.py; window picker (interactive hover+click) in
window_picker.py - both need a live overlay, these three don't, so
there's no window class here, just grab-then-show-picker functions.

Not unit tested for the same reason region_select.py isn't: GTK glue
with no meaningful headless test. The *which Rect to grab* logic these
call (capture.modes.full_screen_region/active_window_region) is pure
and tested there instead.

``capture_mouse_cursor`` on every ``start_*`` function here is the
per-call override from CaptureHelper.cs's own ``_captureMouseCursor``
constructor parameter (see PluginHelper.cs:141's doc comment) - True
means "defer to the Preferences setting" (settings.py's
get_capture_mouse_cursor), False means "never show it regardless of
the setting". app.py passes False from every tray-menu item and True
from hotkey/CLI invocations, matching Windows' own asymmetry: by the
time you've clicked a menu item your mouse is over the menu, not your
content, so Windows' MainForm.cs hardcodes it off there too - see
REQUIREMENTS.md's cursor auto-capture section for the full citation
trail.
"""

from __future__ import annotations

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.capture.modes import active_window_region, full_screen_region
from greenshot_linux.capture.window import WindowEnumerator
from greenshot_linux.core.cursor_capture import cursor_shape_for_capture
from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import CursorShape
from greenshot_linux.settings import get_capture_mouse_cursor


def _default_capture_backend() -> CaptureBackend:
    from greenshot_linux.capture.x11 import X11CaptureBackend

    return X11CaptureBackend()


def _default_window_enumerator() -> WindowEnumerator:
    from greenshot_linux.capture.x11_window import X11WindowEnumerator

    return X11WindowEnumerator()


def _default_cursor_backend() -> CursorBackend:
    from greenshot_linux.capture.x11_cursor import X11CursorBackend

    return X11CursorBackend()


def should_capture_cursor(capture_mouse_cursor: bool) -> bool:
    """The gate check alone (see module docstring), with no fetch -
    combines the per-call override with the persisted Preferences
    setting, faithfully porting CaptureHelper.cs:319's
    ``_captureMouseCursor && CoreConfig.CaptureMousepointer``. Split
    out from capture_cursor_shape so an interactive overlay (region
    select, window picker) can decide *whether* to sample the cursor
    at construction time, before the final captured rect - needed for
    placement - is even known.
    """
    return capture_mouse_cursor and get_capture_mouse_cursor()


def capture_cursor_shape(
    capture_rect: Rect, capture_mouse_cursor: bool, cursor_backend: CursorBackend = None
) -> CursorShape | None:
    """The mouse cursor as a CursorShape ready to add to a Layer, or
    None if it shouldn't be captured at all right now - for the
    non-interactive modes below, where the captured rect is already
    known up front. See should_capture_cursor's docstring for why the
    interactive overlays don't use this directly.
    """
    if not should_capture_cursor(capture_mouse_cursor):
        return None
    if cursor_backend is None:
        cursor_backend = _default_cursor_backend()
    snapshot = cursor_backend.cursor_snapshot()
    if snapshot is None:
        return None
    return cursor_shape_for_capture(
        snapshot.image, snapshot.x, snapshot.y, snapshot.hotspot_x, snapshot.hotspot_y, capture_rect,
    )


def _show_picker(image, cursor_shape: CursorShape = None):
    from greenshot_linux.ui.destination_picker import show_destination_picker

    return show_destination_picker(image, cursor_shape=cursor_shape)


def start_full_screen_capture(
    capture_backend: CaptureBackend = None, on_captured=None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
):
    """Grabs the whole virtual screen and shows the destination picker
    on it. ``on_captured(absolute_rect)``, if given, fires right before
    the picker opens - GreenshotApplication uses this to remember the
    region for "repeat last region".
    """
    if capture_backend is None:
        capture_backend = _default_capture_backend()
    region = full_screen_region(capture_backend)
    image = capture_backend.grab(region)
    if on_captured is not None:
        on_captured(region)
    cursor_shape = capture_cursor_shape(region, capture_mouse_cursor, cursor_backend)
    return _show_picker(image, cursor_shape)


def start_active_window_capture(
    capture_backend: CaptureBackend = None, window_enumerator: WindowEnumerator = None, on_captured=None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
):
    """Grabs the currently focused window and shows the destination
    picker on it. Returns None (doing nothing else) if there's no
    active window to capture - e.g. focus is on the desktop itself.
    """
    if capture_backend is None:
        capture_backend = _default_capture_backend()
    if window_enumerator is None:
        window_enumerator = _default_window_enumerator()
    region = active_window_region(capture_backend, window_enumerator)
    if region is None:
        return None
    image = capture_backend.grab(region)
    if on_captured is not None:
        on_captured(region)
    cursor_shape = capture_cursor_shape(region, capture_mouse_cursor, cursor_backend)
    return _show_picker(image, cursor_shape)


def start_last_region_capture(
    last_region: Rect, capture_backend: CaptureBackend = None,
    capture_mouse_cursor: bool = True, cursor_backend: CursorBackend = None,
):
    """Re-grabs ``last_region`` fresh (not cached pixels - "repeat"
    means the same spatial region, picking up whatever's there now,
    matching the Windows source's Shift+PrintScreen behavior) and
    shows the destination picker on it. Returns None if there's no
    region to repeat, matching start_active_window_capture's "nothing
    to do" convention.
    """
    if last_region is None:
        return None
    if capture_backend is None:
        capture_backend = _default_capture_backend()
    clamped = capture_backend.screen_layout().clamp(last_region)
    if clamped is None:
        return None
    image = capture_backend.grab(clamped)
    cursor_shape = capture_cursor_shape(clamped, capture_mouse_cursor, cursor_backend)
    return _show_picker(image, cursor_shape)
