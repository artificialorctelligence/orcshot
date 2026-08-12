"""One contract every capture backend must satisfy.

Runs against the in-memory fake always, and against the real X11 adapter
whenever a display is available, so the fake cannot quietly drift away
from how the real backend behaves.
"""

import os

import numpy as np
import pytest

from orcshot.capture.backend import CaptureBackend, ScreenLayout
from orcshot.capture.fake import FakeCaptureBackend
from orcshot.core.geometry import Rect

pytestmark = pytest.mark.parametrize(
    "backend_name", ["fake", pytest.param("x11", marks=pytest.mark.x11)]
)


@pytest.fixture
def backend(backend_name):
    if backend_name == "x11":
        if not os.environ.get("DISPLAY"):
            pytest.skip("no X11 display available")
        from orcshot.capture.x11 import X11CaptureBackend

        return X11CaptureBackend()
    return FakeCaptureBackend()


def test_satisfies_the_backend_protocol(backend):
    assert isinstance(backend, CaptureBackend)


def test_reports_a_usable_screen_layout(backend):
    layout = backend.screen_layout()

    assert isinstance(layout, ScreenLayout)
    assert len(layout.monitors) >= 1
    assert layout.virtual_bounds.width > 0
    assert layout.virtual_bounds.height > 0


def test_grabbing_the_whole_screen_matches_the_virtual_bounds(backend):
    bounds = backend.screen_layout().virtual_bounds

    image = backend.grab(bounds)

    assert image.shape == (bounds.height, bounds.width, 4)
    assert image.dtype == np.uint8


def test_grabbing_a_sub_region_returns_that_size(backend):
    bounds = backend.screen_layout().virtual_bounds
    rect = Rect(bounds.left + 10, bounds.top + 20, bounds.left + 110, bounds.top + 90)

    image = backend.grab(rect)

    assert image.shape == (70, 100, 4)


def test_captured_pixels_are_fully_opaque(backend):
    # X11 root windows carry no meaningful alpha, so backends must
    # synthesise it; the editor composites annotations over this.
    bounds = backend.screen_layout().virtual_bounds
    rect = Rect(bounds.left, bounds.top, bounds.left + 32, bounds.top + 32)

    image = backend.grab(rect)

    assert np.all(image[:, :, 3] == 255)


def test_grabbing_outside_the_virtual_bounds_is_rejected(backend):
    bounds = backend.screen_layout().virtual_bounds
    outside = Rect(bounds.right + 100, bounds.top, bounds.right + 200, bounds.top + 100)

    with pytest.raises(ValueError):
        backend.grab(outside)


def test_grabbing_a_partly_outside_rect_is_rejected(backend):
    # Callers are expected to ScreenLayout.clamp first; silently
    # returning a smaller image than asked for would be worse.
    bounds = backend.screen_layout().virtual_bounds
    overhanging = Rect(bounds.right - 50, bounds.top, bounds.right + 50, bounds.top + 50)

    with pytest.raises(ValueError):
        backend.grab(overhanging)


def test_grabbing_an_empty_rect_is_rejected(backend):
    bounds = backend.screen_layout().virtual_bounds
    empty = Rect(bounds.left, bounds.top, bounds.left, bounds.top)

    with pytest.raises(ValueError):
        backend.grab(empty)
