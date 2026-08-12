"""Pure coverage for wayland.py's crop math - the parts that involve a
real portal call, GTK, or a live display are only verified live (see
REQUIREMENTS.md's Wayland section), matching this project's split of
unit-testable logic vs. live-verified glue.
"""

import numpy as np
import pytest

from orcshot.capture.wayland import WaylandCaptureUnavailable, _crop_to_rect
from orcshot.core.geometry import Rect


def _coordinate_image(bounds: Rect) -> np.ndarray:
    # Same trick as FakeCaptureBackend: encode each pixel's own
    # virtual-screen coordinates, so a test can tell whether the crop
    # sliced out the right region and not merely the right size.
    ys, xs = np.indices((bounds.height, bounds.width), dtype=np.int32)
    xs = xs + bounds.left
    ys = ys + bounds.top
    image = np.zeros((bounds.height, bounds.width, 4), dtype=np.uint8)
    image[:, :, 0] = xs & 0xFF
    image[:, :, 1] = ys & 0xFF
    image[:, :, 3] = 255
    return image


class TestCropToRect:
    def test_single_monitor_at_origin_crops_directly(self):
        bounds = Rect(0, 0, 1366, 768)
        image = _coordinate_image(bounds)
        rect = Rect(10, 20, 110, 90)

        cropped = _crop_to_rect(image, rect, bounds)

        assert cropped.shape == (70, 100, 4)
        assert tuple(cropped[0, 0]) == (10, 20, 0, 255)

    def test_whole_screen_matches_the_full_image(self):
        bounds = Rect(0, 0, 800, 600)
        image = _coordinate_image(bounds)

        cropped = _crop_to_rect(image, bounds, bounds)

        assert np.array_equal(cropped, image)

    def test_monitor_with_negative_origin_offsets_correctly(self):
        # A monitor placed to the left of the primary - bounds.left < 0,
        # matching what a real multi-monitor layout can report.
        bounds = Rect(-1920, 0, 1920, 1080)
        image = _coordinate_image(bounds)
        rect = Rect(-1920, 0, -1820, 100)

        cropped = _crop_to_rect(image, rect, bounds)

        assert cropped.shape == (100, 100, 4)
        # x=-1920, y=0: the low byte of -1920 (two's complement) is 128.
        assert tuple(cropped[0, 0]) == (128, 0, 0, 255)

    def test_image_smaller_than_requested_rect_raises(self):
        bounds = Rect(0, 0, 1366, 768)
        image = _coordinate_image(bounds)
        # A rect that's valid against `bounds` but the portal's actual
        # image came back a different (smaller) size than expected.
        undersized_image = image[:700, :1300]
        rect = Rect(1350, 0, 1366, 50)

        with pytest.raises(WaylandCaptureUnavailable):
            _crop_to_rect(undersized_image, rect, bounds)
