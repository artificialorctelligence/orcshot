"""An in-memory capture backend for tests.

Generates content that encodes each pixel's absolute virtual-screen
coordinates, so a test can tell whether a grab came from the right place
and not merely the right size.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from greenshot_linux.capture.backend import Monitor, ScreenLayout
from greenshot_linux.capture.window import WindowInfo, is_capturable
from greenshot_linux.core.geometry import Rect

DEFAULT_MONITORS = (Monitor("FAKE-1", Rect(0, 0, 1920, 1080), is_primary=True),)


def _coordinate_pattern(bounds: Rect) -> np.ndarray:
    ys, xs = np.indices((bounds.height, bounds.width), dtype=np.int32)
    xs = xs + bounds.left
    ys = ys + bounds.top
    image = np.empty((bounds.height, bounds.width, 4), dtype=np.uint8)
    image[:, :, 0] = xs & 0xFF
    image[:, :, 1] = ys & 0xFF
    image[:, :, 2] = ((xs >> 8) & 0x0F) << 4 | ((ys >> 8) & 0x0F)
    image[:, :, 3] = 255
    return image


class FakeCaptureBackend:
    def __init__(
        self,
        monitors: Sequence[Monitor] | None = None,
        image: np.ndarray | None = None,
    ):
        self._layout = ScreenLayout(monitors or DEFAULT_MONITORS)
        bounds = self._layout.virtual_bounds
        if image is None:
            image = _coordinate_pattern(bounds)
        elif image.shape[:2] != (bounds.height, bounds.width):
            raise ValueError(
                f"image is {image.shape[1]}x{image.shape[0]}, "
                f"expected {bounds.width}x{bounds.height}"
            )
        self._image = image
        self.grabs: list[Rect] = []

    def screen_layout(self) -> ScreenLayout:
        return self._layout

    def grab(self, rect: Rect) -> np.ndarray:
        bounds = self._layout.virtual_bounds
        if rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"cannot grab an empty region: {rect}")
        if rect.intersect(bounds) != rect:
            raise ValueError(f"{rect} is not inside the virtual screen {bounds}")
        self.grabs.append(rect)
        top = rect.top - bounds.top
        left = rect.left - bounds.left
        return self._image[top:top + rect.height, left:left + rect.width].copy()


class FakeWindowEnumerator:
    def __init__(
        self,
        windows: Sequence[WindowInfo] = (),
        active: Optional[WindowInfo] = None,
    ):
        self._windows = list(windows)
        self._active = active

    def list_windows(self) -> Sequence[WindowInfo]:
        return [w for w in self._windows if is_capturable(w)]

    def active_window(self) -> Optional[WindowInfo]:
        return self._active
