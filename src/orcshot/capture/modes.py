"""Pure region-resolution logic for each capture mode: given a
CaptureBackend/WindowEnumerator, what Rect should get grabbed. Kept
separate from the actual grab + launch-EditorWindow glue
(ui/capture_modes.py) so it's unit testable against the fakes without
needing GTK.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from orcshot.capture.backend import CaptureBackend
from orcshot.capture.window import WindowEnumerator, WindowInfo
from orcshot.core.geometry import Rect


def full_screen_region(capture_backend: CaptureBackend) -> Rect:
    return capture_backend.screen_layout().virtual_bounds


def active_window_info(capture_backend: CaptureBackend, window_enumerator: WindowEnumerator) -> Optional[WindowInfo]:
    """The currently focused window, its ``bounds`` clamped to the
    virtual screen (a window's reported geometry can extend slightly
    past it - e.g. after being dragged partly off-screen), or None if
    there's no active window (focus could be on the desktop itself) or
    it's entirely off-screen.

    Was ``active_window_region`` (returning just the clamped Rect)
    until task #139 - callers now also need ``.title`` to fill in the
    ``${title}`` filename pattern token (core/filename_pattern.py),
    which real Windows Greenshot always has available for these two
    capture modes (FilenameHelper.cs's own ${title} substitution)
    since a captured window always has one, unlike region/full-screen
    capture.
    """
    window = window_enumerator.active_window()
    if window is None:
        return None
    clamped = capture_backend.screen_layout().clamp(window.bounds)
    if clamped is None:
        return None
    return replace(window, bounds=clamped)
