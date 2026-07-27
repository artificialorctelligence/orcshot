"""FakeClipboardBackend-specific behavior: recording every set_image
call for tests to inspect, not part of the shared ClipboardBackend
contract (the real adapter has no equivalent introspection).
"""

import numpy as np

from greenshot_linux.capture.fake import FakeClipboardBackend


def test_last_image_is_none_before_any_copy():
    backend = FakeClipboardBackend()
    assert backend.last_image is None


def test_last_image_reflects_the_most_recent_copy():
    backend = FakeClipboardBackend()
    first = np.full((2, 2, 4), (1, 2, 3, 255), dtype=np.uint8)
    second = np.full((2, 2, 4), (9, 8, 7, 255), dtype=np.uint8)

    backend.set_image(first)
    backend.set_image(second)

    assert np.array_equal(backend.last_image, second)
    assert len(backend.images) == 2


def test_stores_a_copy_not_a_reference():
    backend = FakeClipboardBackend()
    image = np.full((2, 2, 4), (1, 2, 3, 255), dtype=np.uint8)
    backend.set_image(image)

    image[:, :] = 0

    assert np.all(backend.last_image == np.array((1, 2, 3, 255), dtype=np.uint8))
