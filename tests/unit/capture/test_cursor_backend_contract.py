"""One contract every cursor backend must satisfy.

Runs against the in-memory fake always, and against the real X11
adapter whenever a display is available, so the fake cannot quietly
drift away from how the real backend behaves. This only ever reads
the mouse pointer *icon* (a handful of pixels) from the real backend,
never desktop content - safe to exercise for real.
"""

import os

import numpy as np
import pytest

from greenshot_linux.capture.cursor import CursorBackend
from greenshot_linux.capture.fake import FakeCursorBackend

pytestmark = pytest.mark.parametrize(
    "backend_name", ["fake", pytest.param("x11", marks=pytest.mark.x11)]
)


@pytest.fixture
def backend(backend_name):
    if backend_name == "x11":
        if not os.environ.get("DISPLAY"):
            pytest.skip("no X11 display available")
        from greenshot_linux.capture.x11_cursor import X11CursorBackend

        return X11CursorBackend()
    return FakeCursorBackend()


def test_satisfies_the_cursor_backend_protocol(backend):
    assert isinstance(backend, CursorBackend)


def test_snapshot_has_a_nonempty_rgba_image(backend):
    snapshot = backend.cursor_snapshot()

    assert snapshot is not None
    assert snapshot.image.ndim == 3
    assert snapshot.image.shape[2] == 4
    assert snapshot.image.dtype == np.uint8
    assert snapshot.image.shape[0] > 0
    assert snapshot.image.shape[1] > 0


def test_snapshot_hotspot_is_within_the_image_bounds(backend):
    snapshot = backend.cursor_snapshot()

    height, width = snapshot.image.shape[:2]
    assert 0 <= snapshot.hotspot_x < width
    assert 0 <= snapshot.hotspot_y < height
