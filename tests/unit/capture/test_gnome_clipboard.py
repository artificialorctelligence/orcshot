"""Pure coverage for gnome_clipboard.py's PNG-encoding logic - the
D-Bus call itself needs a real GNOME/Wayland session with the
orcshot-clipboard extension enabled, only verified live (see
REQUIREMENTS.md's "Clipboard under Wayland" section). Doesn't need a
real display: GdkPixbuf's own encode/decode round trip works headless,
same as test_gdk_convert.py's file-based round-trip test.
"""

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

import numpy as np

from orcshot.capture.gnome_clipboard import _encode_png


class TestEncodePng:
    def test_produces_valid_png_bytes(self):
        image = np.random.default_rng(0).integers(0, 256, size=(4, 6, 4), dtype=np.uint8)
        png_bytes = _encode_png(image)

        loaded = GdkPixbuf.Pixbuf.new_from_stream(
            Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(png_bytes)), None,
        )
        assert loaded.get_width() == 6
        assert loaded.get_height() == 4

    def test_round_trips_pixel_values(self):
        image = np.zeros((2, 2, 4), dtype=np.uint8)
        image[0, 0] = (255, 0, 0, 255)
        image[1, 1] = (0, 255, 0, 128)
        png_bytes = _encode_png(image)

        loaded = GdkPixbuf.Pixbuf.new_from_stream(
            Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(png_bytes)), None,
        )
        pixels = loaded.get_pixels()
        channels, rowstride = loaded.get_n_channels(), loaded.get_rowstride()
        assert channels == 4  # alpha preserved
        assert tuple(pixels[0:4]) == (255, 0, 0, 255)
        assert tuple(pixels[rowstride + 4:rowstride + 8]) == (0, 255, 0, 128)

    def test_returns_real_bytes_not_a_glib_wrapper(self):
        image = np.zeros((1, 1, 4), dtype=np.uint8)
        assert isinstance(_encode_png(image), bytes)
