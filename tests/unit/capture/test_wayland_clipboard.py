"""WaylandClipboardBackend-specific behavior: a genuine round-trip
through the real Wayland clipboard, not just "doesn't raise" (covered
by the shared contract test). Same Gtk.Clipboard mechanism
test_x11_clipboard.py already verified works for an in-process
round-trip - this just confirms it under a Wayland session too.

set_image() is asynchronous here (see wayland_clipboard.py's module
docstring for why - it briefly shows an invisible window and waits for
real compositor focus before claiming the clipboard), so this test
pumps the main loop for real wall-clock time rather than just draining
whatever's already queued - a plain events_pending() drain wouldn't
give the compositor's focus round-trip, or the module's own timeout
fallback, a chance to actually happen.
"""

import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.wayland


@pytest.fixture(autouse=True)
def skip_without_display():
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("no Wayland display available")


def test_set_image_can_be_read_back_from_the_real_clipboard():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    from orcshot.capture.wayland_clipboard import WaylandClipboardBackend
    from orcshot.ui.gdk_convert import pixbuf_to_numpy

    image = np.full((4, 4, 4), (10, 20, 30, 255), dtype=np.uint8)
    WaylandClipboardBackend().set_image(image)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.05)

    clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
    pixbuf = clipboard.wait_for_image()

    assert pixbuf is not None
    result = pixbuf_to_numpy(pixbuf)
    assert np.array_equal(result, image)
