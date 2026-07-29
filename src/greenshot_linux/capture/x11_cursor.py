"""X11 cursor capture via the XFixes extension's GetCursorImage
request - the direct analogue of the Win32 GetCursorInfo+GetIconInfo
pair used by Windows Greenshot's WindowCapture.CaptureCursor
(Greenshot.Base/Core/WindowCapture.cs:81-101).

Uses python-xlib rather than GDK: GTK/GDK has no public API for
reading the *system* cursor image (only for setting an application's
own cursor), so this needs direct X11 protocol access - the same
dependency capture/x11_window.py already uses for window enumeration.

XFixesGetCursorImage's ``window`` argument is unused by python-xlib's
own implementation (confirmed by reading Xlib/ext/xfixes.py:173-176)
but is still a required positional parameter, so it's called with
``None``, confirmed live (see the class docstring below) rather than
guessed.

Pixel format confirmed empirically (own mouse pointer icon, no
desktop content involved) rather than assumed from the XFixes spec
alone: each of ``cursor_image``'s ints is a 32-bit premultiplied ARGB
value, alpha in the top byte, matching Cairo's own ARGB32 layout - an
opaque black cursor pixel read back as ``0xff000000`` exactly as
expected. Un-premultiplied here because this codebase's numpy RGBA
convention is straight alpha everywhere else (see
ui/cairo_convert.py's documented premultiplication limitation) - the
cursor is the first image source in this codebase with genuinely
partial-alpha pixels (anti-aliased edges), so unlike every other
image source, skipping this step would be visibly wrong, not just a
latent simplification.
"""

from __future__ import annotations

import numpy as np
from Xlib import display

from greenshot_linux.capture.cursor import CursorSnapshot


def _unpremultiply(rgba: np.ndarray) -> None:
    alpha = rgba[:, :, 3].astype(np.float32)
    nonzero = alpha > 0
    for channel in range(3):
        straight = np.zeros_like(alpha)
        premultiplied = rgba[:, :, channel][nonzero].astype(np.float32)
        straight[nonzero] = premultiplied * 255.0 / alpha[nonzero]
        rgba[:, :, channel] = np.clip(straight, 0, 255).astype(np.uint8)


def cursor_image_to_rgba(width: int, height: int, cursor_image) -> np.ndarray:
    """Pure conversion, factored out so the tricky bit-unpacking and
    un-premultiply math is unit-testable without a live X11 display.
    """
    packed = np.array(cursor_image, dtype=np.uint32).reshape(height, width)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[:, :, 0] = (packed >> 16) & 0xFF  # R
    rgba[:, :, 1] = (packed >> 8) & 0xFF  # G
    rgba[:, :, 2] = packed & 0xFF  # B
    rgba[:, :, 3] = (packed >> 24) & 0xFF  # A
    _unpremultiply(rgba)
    return rgba


class X11CursorBackend:
    def __init__(self):
        self._display = display.Display()
        if not self._display.has_extension("XFIXES"):
            raise RuntimeError("X server has no XFixes extension - cannot capture the cursor")
        self._display.xfixes_query_version()

    def cursor_snapshot(self) -> CursorSnapshot | None:
        reply = self._display.xfixes_get_cursor_image(None)
        if reply is None or reply.width == 0 or reply.height == 0:
            return None
        image = cursor_image_to_rgba(reply.width, reply.height, reply.cursor_image)
        return CursorSnapshot(image=image, x=reply.x, y=reply.y, hotspot_x=reply.xhot, hotspot_y=reply.yhot)
