"""X11 capture via GDK.

GDK is used rather than raw Xlib because it already resolves the things
that vary between machines — XRandR monitor enumeration, hotplug, and
HiDPI scale factors — and it benchmarks faster than XGetImage for a
full-screen grab.
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")

import numpy as np
from gi.repository import Gdk

from orcshot.capture.backend import ScreenLayout
from orcshot.capture.gdk_screen_layout import gdk_screen_layout
from orcshot.core.geometry import Rect


class X11CaptureUnavailable(RuntimeError):
    pass


def _pixbuf_to_rgba(pixbuf) -> np.ndarray:
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, stride = pixbuf.get_n_channels(), pixbuf.get_rowstride()

    # Rows are padded to `stride`, and GdkPixbuf may leave the final row
    # unpadded, so the buffer can be short of height * stride.
    data = pixbuf.get_pixels()
    if len(data) < height * stride:
        data = data + bytes(height * stride - len(data))
    rows = np.frombuffer(data, dtype=np.uint8).reshape(height, stride)
    pixels = rows[:, : width * channels].reshape(height, width, channels)

    image = np.empty((height, width, 4), dtype=np.uint8)
    image[:, :, :3] = pixels[:, :, :3]
    # X11 root windows carry no meaningful alpha (it reads back as 0),
    # so opacity is synthesised rather than copied.
    image[:, :, 3] = 255
    return image


class X11CaptureBackend:
    def __init__(self):
        display = Gdk.Display.get_default()
        if display is None:
            raise X11CaptureUnavailable(
                "no display available; is DISPLAY set and an X server running?"
            )
        self._display = display

    def screen_layout(self) -> ScreenLayout:
        return gdk_screen_layout(self._display)

    def grab(self, rect: Rect) -> np.ndarray:
        bounds = self.screen_layout().virtual_bounds
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"cannot grab an empty region: {rect}")
        if rect.intersect(bounds) != rect:
            raise ValueError(f"{rect} is not inside the virtual screen {bounds}")

        root = self._display.get_default_screen().get_root_window()
        pixbuf = Gdk.pixbuf_get_from_window(
            root, rect.left, rect.top, rect.width, rect.height
        )
        if pixbuf is None:
            raise X11CaptureUnavailable(
                "the root window could not be captured; direct capture does "
                "not work under Wayland, which needs the portal backend"
            )
        return _pixbuf_to_rgba(pixbuf)
