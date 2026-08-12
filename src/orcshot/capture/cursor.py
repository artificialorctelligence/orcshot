"""The cursor-capture port: what every platform adapter must provide
for cursor auto-capture (see core/cursor_capture.py for the pure
placement math this feeds, and ui/capture_modes.py etc. for wiring).

A separate port from CaptureBackend (backend.py): the mouse cursor
isn't part of the screen's pixel content on any platform - Windows
reads it via GetCursorInfo/GetIconInfo (WindowCapture.CaptureCursor,
Greenshot.Base/Core/WindowCapture.cs:81-101), X11 via the XFixes
extension (capture/x11_cursor.py) - so it needs its own query, not a
region grab.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class CursorSnapshot:
    """A mouse cursor, sampled at one instant.

    ``x``/``y`` are the cursor's hotspot position in absolute virtual-
    screen coordinates (the same coordinate space as
    ``CaptureBackend.grab``'s ``rect``); ``hotspot_x``/``hotspot_y``
    are that hotspot's offset within ``image`` itself. Both are needed
    together to place the image - see
    core/cursor_capture.py:cursor_bounds_in_capture.
    """

    image: np.ndarray  # (H, W, 4) uint8 RGBA, straight (non-premultiplied) alpha
    x: int
    y: int
    hotspot_x: int
    hotspot_y: int


@runtime_checkable
class CursorBackend(Protocol):
    """A source of the current mouse cursor's image and position."""

    def cursor_snapshot(self) -> CursorSnapshot | None:
        """The cursor right now, or None if it can't be determined."""
