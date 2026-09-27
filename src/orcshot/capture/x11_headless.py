"""Headless capture on X11 (BACKLOG #225).

Thin by design: the pixels come from the same X11CaptureBackend every
interactive capture already uses, the window comes from the same
X11WindowEnumerator, and the refusal decision is capture/modes.py's own
pure resolve_window_for_headless_capture. This module is only the wiring
that puts them in a line and writes the result.

Backends are injectable, matching ui/window_picker.py's
start_window_picker, so the whole flow is testable against the fakes
without a display.
"""

from __future__ import annotations

from typing import Optional

from orcshot.capture.modes import resolve_window_for_headless_capture
from orcshot.core.geometry import Rect
from orcshot.ui.file_export import save_image_to_file


def capture_to_file(
    path: str,
    window_title: Optional[str],
    capture_backend=None,
    window_enumerator=None,
) -> None:
    """Grab the screen (or one window) and write it to ``path``.

    Raises HeadlessCaptureError when a named window cannot be captured
    correctly - see resolve_window_for_headless_capture for what that
    means and why it refuses rather than returning the wrong pixels.
    """
    if capture_backend is None:
        from orcshot.capture.x11 import X11CaptureBackend

        capture_backend = X11CaptureBackend()

    layout = capture_backend.screen_layout()
    if window_title is None:
        # Deliberately no enumeration for a full-screen capture: it can
        # raise on a window manager with no EWMH support, and a whole-
        # screen grab has no need to know what windows exist.
        region: Rect = layout.virtual_bounds
    else:
        if window_enumerator is None:
            from orcshot.capture.x11_window import X11WindowEnumerator

            window_enumerator = X11WindowEnumerator()
        # The resolver asks about a WindowInfo; X11 answers about a
        # window id. Adapted here rather than widening either side -
        # GNOME answers about a WindowInfo directly, from the
        # in_current_workspace its own list-windows already carries.
        target = resolve_window_for_headless_capture(
            window_enumerator.list_windows(),
            lambda window: window_enumerator.is_on_current_workspace(window.window_id),
            window_title,
        )
        # Clamped, not refused: a window dragged partly off the edge
        # still has real pixels on screen, and grabbing past
        # virtual_bounds would raise.
        region = layout.clamp(target.bounds)

    save_image_to_file(capture_backend.grab(region), path)
