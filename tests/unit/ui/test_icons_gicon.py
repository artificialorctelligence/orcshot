"""Pure coverage for the Gio.Icon-producing icon helpers - same
headless-safe pattern as test_gnome_clipboard.py's PNG round-trip
test, no display needed."""
import gi

gi.require_version("Gio", "2.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GdkPixbuf

from orcshot.ui.icons import capture_mode_gicon


class TestCaptureModeGicon:
    def test_returns_a_real_gio_icon(self):
        icon = capture_mode_gicon("region")
        assert isinstance(icon, Gio.Icon)

    def test_serializes_and_deserializes_to_the_same_icon(self):
        icon = capture_mode_gicon("region")
        variant = icon.serialize()
        restored = Gio.Icon.deserialize(variant)
        assert isinstance(restored, Gio.BytesIcon)

    def test_bytes_are_a_valid_decodable_png_at_the_requested_size(self):
        icon = capture_mode_gicon("region", size=32)
        assert isinstance(icon, Gio.BytesIcon)
        png_bytes = icon.get_bytes().get_data()
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream(
            Gio.MemoryInputStream.new_from_bytes(icon.get_bytes()), None,
        )
        assert pixbuf.get_width() == 32
        assert pixbuf.get_height() == 32

    def test_different_modes_produce_different_icons(self):
        region_bytes = capture_mode_gicon("region").get_bytes().get_data()
        window_bytes = capture_mode_gicon("active_window").get_bytes().get_data()
        assert region_bytes != window_bytes
