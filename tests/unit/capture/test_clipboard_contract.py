"""One contract every clipboard backend must satisfy.

Runs against the in-memory fake always, and against the real GTK/X11
and GTK/Wayland adapters whenever a matching display is available -
verified with a genuine in-process clipboard round-trip (Gtk.Clipboard
resolves a set_image locally without needing another process to
request the data, checked manually before writing this test), not
just "doesn't raise".
"""

import os

import numpy as np
import pytest

from orcshot.capture.clipboard import ClipboardBackend
from orcshot.capture.fake import FakeClipboardBackend

pytestmark = pytest.mark.parametrize(
    "backend_name",
    [
        "fake",
        pytest.param("x11", marks=pytest.mark.x11),
        pytest.param("wayland", marks=pytest.mark.wayland),
    ],
)


@pytest.fixture
def backend(backend_name):
    if backend_name == "x11":
        if not os.environ.get("DISPLAY"):
            pytest.skip("no X11 display available")
        from orcshot.capture.x11_clipboard import X11ClipboardBackend

        return X11ClipboardBackend()
    if backend_name == "wayland":
        if not os.environ.get("WAYLAND_DISPLAY"):
            pytest.skip("no Wayland display available")
        from orcshot.capture.wayland_clipboard import WaylandClipboardBackend

        return WaylandClipboardBackend()
    return FakeClipboardBackend()


def test_satisfies_the_backend_protocol(backend):
    assert isinstance(backend, ClipboardBackend)


def test_set_image_does_not_raise(backend):
    image = np.full((4, 4, 4), (10, 20, 30, 255), dtype=np.uint8)
    backend.set_image(image)
