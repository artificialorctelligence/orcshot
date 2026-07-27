"""X11ClipboardBackend-specific behavior: a genuine round-trip through
the real X clipboard, not just "doesn't raise" (covered by the shared
contract test). Verified feasible before writing this test: Gtk's own
clipboard resolves a locally-set image without needing a second
process to request it, confirmed with a manual probe script.
"""

import os

import numpy as np
import pytest

pytestmark = pytest.mark.x11


@pytest.fixture(autouse=True)
def skip_without_display():
    if not os.environ.get("DISPLAY"):
        pytest.skip("no X11 display available")


def test_set_image_can_be_read_back_from_the_real_clipboard():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    from greenshot_linux.capture.x11_clipboard import X11ClipboardBackend
    from greenshot_linux.ui.gdk_convert import pixbuf_to_numpy

    image = np.full((4, 4, 4), (10, 20, 30, 255), dtype=np.uint8)
    X11ClipboardBackend().set_image(image)

    for _ in range(20):
        while Gtk.events_pending():
            Gtk.main_iteration()

    clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
    pixbuf = clipboard.wait_for_image()

    assert pixbuf is not None
    result = pixbuf_to_numpy(pixbuf)
    assert np.array_equal(result, image)
