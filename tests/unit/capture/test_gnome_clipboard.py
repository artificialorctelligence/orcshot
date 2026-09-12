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
import pytest

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


from orcshot.capture import shell_bridge
from orcshot.capture.gnome_clipboard import GnomeClipboardBackend, GnomeClipboardUnavailable, is_available
from tests.unit.capture.fake_bridge import install as install_fake_bridge


class TestBridgePlumbing:
    def test_is_available_is_the_clipboard_capability(self, monkeypatch):
        install_fake_bridge(monkeypatch)
        assert is_available() is False
        install_fake_bridge(monkeypatch, capabilities=["set-clipboard-image"])
        assert is_available() is True

    def test_set_image_sends_png_bytes_as_a_request(self, monkeypatch):
        bridge = install_fake_bridge(monkeypatch, capabilities=["set-clipboard-image"], result={"ok": True})
        GnomeClipboardBackend().set_image(np.zeros((2, 2, 4), dtype=np.uint8))
        (kind, params), = bridge.calls
        assert kind == "set-clipboard-image"
        assert params["pngBytes"].startswith(b"\x89PNG")

    def test_set_image_maps_bridge_errors_to_unavailable(self, monkeypatch):
        install_fake_bridge(monkeypatch, capabilities=["set-clipboard-image"], error=shell_bridge.ShellUnavailable("gone"))
        with pytest.raises(GnomeClipboardUnavailable):
            GnomeClipboardBackend().set_image(np.zeros((2, 2, 4), dtype=np.uint8))
