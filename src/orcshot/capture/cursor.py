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


def default_cursor_backend() -> CursorBackend | None:
    """The platform's default cursor backend, or None if none is
    available right now.

    X11CursorBackend's constructor connects to an X11 display eagerly
    (see x11_cursor.py) - on a session with no reachable X11/XWayland
    display that raises Xlib.error.DisplayError, live-observed as an
    uncaught crash through every capture-mode call site on a
    pure-Wayland session with no DISPLAY set. Every call site used to
    construct X11CursorBackend directly and unconditionally; this is
    the one shared place that catches the failure instead, so callers
    just get None here the same way cursor_snapshot() already documents
    None as a valid "couldn't determine the cursor" outcome.
    """
    from Xlib.error import DisplayError

    from orcshot.capture.x11_cursor import X11CursorBackend

    try:
        return X11CursorBackend()
    except DisplayError:
        return None
