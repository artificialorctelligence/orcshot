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

from greenshot_linux.capture.backend import Monitor, ScreenLayout
from greenshot_linux.core.geometry import Rect


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
        monitors = []
        primary = self._display.get_primary_monitor()
        for index in range(self._display.get_n_monitors()):
            gdk_monitor = self._display.get_monitor(index)
            geometry = gdk_monitor.get_geometry()
            # Geometry is in application pixels; on a scaled display the
            # framebuffer is scale_factor times larger in each direction.
            scale = gdk_monitor.get_scale_factor()
            monitors.append(
                Monitor(
                    name=gdk_monitor.get_model() or f"monitor-{index}",
                    bounds=Rect(
                        geometry.x * scale,
                        geometry.y * scale,
                        (geometry.x + geometry.width) * scale,
                        (geometry.y + geometry.height) * scale,
                    ),
                    is_primary=(
                        gdk_monitor.is_primary()
                        if primary is None
                        else gdk_monitor == primary
                    ),
                )
            )
        return ScreenLayout(monitors)

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
