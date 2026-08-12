"""The fake's own behaviour: deterministic content and call recording.

Crop correctness is pinned here rather than in the shared contract
because only the fake has content that is guaranteed not to change
between two grabs.
"""

import numpy as np
import pytest

from orcshot.capture.backend import Monitor
from orcshot.capture.fake import FakeCaptureBackend
from orcshot.core.geometry import Rect


def test_defaults_to_a_single_monitor():
    layout = FakeCaptureBackend().screen_layout()

    assert len(layout.monitors) == 1
    assert layout.virtual_bounds == Rect(0, 0, 1920, 1080)


def test_accepts_an_arbitrary_monitor_arrangement():
    monitors = [
        Monitor("A", Rect(0, 0, 1280, 1024), is_primary=True),
        Monitor("B", Rect(1280, 0, 3200, 1080)),
    ]

    layout = FakeCaptureBackend(monitors=monitors).screen_layout()

    assert layout.virtual_bounds == Rect(0, 0, 3200, 1080)
    assert layout.primary.name == "A"


def test_sub_region_grab_matches_the_same_crop_of_a_full_grab():
    backend = FakeCaptureBackend()
    rect = Rect(37, 51, 137, 121)

    full = backend.grab(backend.screen_layout().virtual_bounds)
    part = backend.grab(rect)

    assert np.array_equal(part, full[rect.top:rect.bottom, rect.left:rect.right])


def test_generated_content_is_positionally_unique():
    # Two same-sized grabs from different offsets must differ, otherwise
    # the fake could not catch an adapter that ignores the rect origin.
    backend = FakeCaptureBackend()

    first = backend.grab(Rect(0, 0, 64, 64))
    second = backend.grab(Rect(64, 64, 128, 128))

    assert not np.array_equal(first, second)


def test_grabs_are_repeatable():
    backend = FakeCaptureBackend()
    rect = Rect(10, 10, 50, 50)

    assert np.array_equal(backend.grab(rect), backend.grab(rect))


def test_can_be_given_an_explicit_screen_image():
    screen = np.zeros((1080, 1920, 4), dtype=np.uint8)
    screen[:, :] = (7, 8, 9, 255)
    backend = FakeCaptureBackend(image=screen)

    image = backend.grab(Rect(0, 0, 4, 4))

    assert np.array_equal(image, np.full((4, 4, 4), (7, 8, 9, 255), dtype=np.uint8))


def test_explicit_image_must_match_the_virtual_bounds():
    with pytest.raises(ValueError):
        FakeCaptureBackend(image=np.zeros((10, 10, 4), dtype=np.uint8))


def test_records_every_grab_for_inspection():
    backend = FakeCaptureBackend()
    first, second = Rect(0, 0, 10, 10), Rect(5, 5, 20, 20)

    backend.grab(first)
    backend.grab(second)

    assert backend.grabs == [first, second]


def test_returned_arrays_do_not_alias_each_other():
    backend = FakeCaptureBackend()
    rect = Rect(0, 0, 16, 16)

    first = backend.grab(rect)
    first[:] = 0

    assert not np.array_equal(backend.grab(rect), first)
