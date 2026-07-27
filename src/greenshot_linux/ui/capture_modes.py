"""The non-interactive capture triggers: full screen, active window,
and repeat-last-region. Region select (interactive drag) lives in
region_select.py; window picker (interactive hover+click) in
window_picker.py - both need a live overlay, these three don't, so
there's no window class here, just grab-then-launch functions.

Not unit tested for the same reason region_select.py isn't: GTK glue
with no meaningful headless test. The *which Rect to grab* logic these
call (capture.modes.full_screen_region/active_window_region) is pure
and tested there instead.
"""

from __future__ import annotations

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.modes import active_window_region, full_screen_region
from greenshot_linux.capture.window import WindowEnumerator
from greenshot_linux.core.geometry import Rect


def _default_capture_backend() -> CaptureBackend:
    from greenshot_linux.capture.x11 import X11CaptureBackend

    return X11CaptureBackend()


def _default_window_enumerator() -> WindowEnumerator:
    from greenshot_linux.capture.x11_window import X11WindowEnumerator

    return X11WindowEnumerator()


def _launch_editor(image):
    from greenshot_linux.ui.editor_window import EditorWindow

    editor = EditorWindow(image)
    editor.show_all()
    return editor


def start_full_screen_capture(capture_backend: CaptureBackend = None, on_captured=None):
    """Grabs the whole virtual screen and opens EditorWindow on it.
    ``on_captured(absolute_rect)``, if given, fires right before the
    editor opens - GreenshotApplication uses this to remember the
    region for "repeat last region".
    """
    if capture_backend is None:
        capture_backend = _default_capture_backend()
    region = full_screen_region(capture_backend)
    image = capture_backend.grab(region)
    if on_captured is not None:
        on_captured(region)
    return _launch_editor(image)


def start_active_window_capture(
    capture_backend: CaptureBackend = None, window_enumerator: WindowEnumerator = None, on_captured=None
):
    """Grabs the currently focused window and opens EditorWindow on
    it. Returns None (doing nothing else) if there's no active window
    to capture - e.g. focus is on the desktop itself.
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
    return _launch_editor(image)


def start_last_region_capture(last_region: Rect, capture_backend: CaptureBackend = None):
    """Re-grabs ``last_region`` fresh (not cached pixels - "repeat"
    means the same spatial region, picking up whatever's there now,
    matching the Windows source's Shift+PrintScreen behavior) and
    opens EditorWindow on it. Returns None if there's no region to
    repeat, matching start_active_window_capture's "nothing to do"
    convention.
    """
    if last_region is None:
        return None
    if capture_backend is None:
        capture_backend = _default_capture_backend()
    clamped = capture_backend.screen_layout().clamp(last_region)
    if clamped is None:
        return None
    image = capture_backend.grab(clamped)
    return _launch_editor(image)
