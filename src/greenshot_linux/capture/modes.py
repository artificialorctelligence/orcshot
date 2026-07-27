"""Pure region-resolution logic for each capture mode: given a
CaptureBackend/WindowEnumerator, what Rect should get grabbed. Kept
separate from the actual grab + launch-EditorWindow glue
(ui/capture_modes.py) so it's unit testable against the fakes without
needing GTK.
"""

from __future__ import annotations

from typing import Optional

from greenshot_linux.capture.backend import CaptureBackend
from greenshot_linux.capture.window import WindowEnumerator
from greenshot_linux.core.geometry import Rect


def full_screen_region(capture_backend: CaptureBackend) -> Rect:
    return capture_backend.screen_layout().virtual_bounds


def active_window_region(capture_backend: CaptureBackend, window_enumerator: WindowEnumerator) -> Optional[Rect]:
    """The Rect to grab for the currently focused window, clamped to
    the virtual screen (a window's reported geometry can extend
    slightly past it - e.g. after being dragged partly off-screen), or
    None if there's no active window (focus could be on the desktop
    itself) or it's entirely off-screen.
    """
    window = window_enumerator.active_window()
    if window is None:
        return None
    return capture_backend.screen_layout().clamp(window.bounds)
