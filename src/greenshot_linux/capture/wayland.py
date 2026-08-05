"""Wayland screen capture via the XDG Desktop Portal.

Confirmed live (Ubuntu 26.04/GNOME): a direct GDK root-window read -
the trick X11CaptureBackend uses, which still works under XWayland for
X11 sessions - returns a fully black image on a native Wayland
session. That's the compositor enforcing its no-direct-capture
security boundary, not a bug to route around: the portal
(wayland_portal.request_screenshot) is the only sanctioned way to get
real pixel content there.

The portal has no notion of "grab just this rect" - it always hands
back a full screenshot, so cropping to the caller's requested rect
happens here, client-side, after loading the file.
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")

import numpy as np
from gi.repository import Gdk, GdkPixbuf, Gio, GLib

from greenshot_linux.capture.backend import ScreenLayout
from greenshot_linux.capture.gdk_screen_layout import gdk_screen_layout
from greenshot_linux.capture.wayland_portal import TARGET_SCREEN, request_screenshot
from greenshot_linux.core.geometry import Rect


class WaylandCaptureUnavailable(RuntimeError):
    pass


def _pixbuf_to_rgba(pixbuf: GdkPixbuf.Pixbuf) -> np.ndarray:
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels, rowstride = pixbuf.get_n_channels(), pixbuf.get_rowstride()

    # Rows are padded to `rowstride`, and GdkPixbuf may leave the final
    # row unpadded, so the buffer can be short of height * rowstride.
    data = pixbuf.get_pixels()
    if len(data) < height * rowstride:
        data = data + bytes(height * rowstride - len(data))
    rows = np.frombuffer(data, dtype=np.uint8).reshape(height, rowstride)
    pixels = rows[:, : width * channels].reshape(height, width, channels)

    image = np.empty((height, width, 4), dtype=np.uint8)
    if channels == 4:
        # Unlike X11CaptureBackend's root-window read, the portal's
        # PNG is a real screenshot of opaque desktop content, so its
        # alpha channel is meaningful (if present) rather than needing
        # to be synthesised.
        image[:, :, :] = pixels
    else:
        image[:, :, :3] = pixels[:, :, :3]
        image[:, :, 3] = 255
    return image


def _crop_to_rect(image: np.ndarray, rect: Rect, bounds: Rect) -> np.ndarray:
    """The pure part of grab(): given a full portal screenshot and the
    caller's requested rect, slice out just that region. Split out so
    the offset/bounds-check math has unit coverage that doesn't need a
    real portal call or GTK to exercise.

    Assumes the portal image starts at the virtual screen's own origin
    (bounds.left, bounds.top) - true for the VM's single monitor
    (bounds.left == 0, image was exactly 1366x768), but NOT YET
    verified against a real multi-monitor Wayland session, where
    bounds.left/top can be negative.
    """
    height, width = image.shape[:2]
    crop = Rect(
        rect.left - bounds.left,
        rect.top - bounds.top,
        rect.right - bounds.left,
        rect.bottom - bounds.top,
    )
    if crop.left < 0 or crop.top < 0 or crop.right > width or crop.bottom > height:
        raise WaylandCaptureUnavailable(
            f"portal screenshot was {width}x{height}, too small for "
            f"requested region {rect} against virtual bounds {bounds}"
        )
    return image[crop.top : crop.bottom, crop.left : crop.right]


class WaylandCaptureBackend:
    def __init__(self):
        display = Gdk.Display.get_default()
        if display is None:
            raise WaylandCaptureUnavailable(
                "no display available; is WAYLAND_DISPLAY set and a compositor running?"
            )
        self._display = display

    def screen_layout(self) -> ScreenLayout:
        return gdk_screen_layout(self._display)

    def _load_screenshot(self) -> np.ndarray:
        uri = request_screenshot(TARGET_SCREEN)
        path = Gio.File.new_for_uri(uri).get_path()
        if path is None:
            raise WaylandCaptureUnavailable(f"portal returned a non-local uri: {uri}")

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error as error:
            raise WaylandCaptureUnavailable(
                f"could not load the portal's screenshot file {path}: {error}"
            ) from error

        return _pixbuf_to_rgba(pixbuf)

    def grab(self, rect: Rect) -> np.ndarray:
        bounds = self.screen_layout().virtual_bounds
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"cannot grab an empty region: {rect}")
        if rect.intersect(bounds) != rect:
            raise ValueError(f"{rect} is not inside the virtual screen {bounds}")

        image = self._load_screenshot()
        return _crop_to_rect(image, rect, bounds)
