"""numpy RGBA <-> GdkPixbuf conversion.

GdkPixbuf.Colorspace.RGB stores each pixel as literal R, G, B, A bytes
in that order - confirmed empirically before writing any conversion
code: a (10, 20, 30, 255) pixel round-tripped through new_from_bytes
-> get_pixels came back as the same four bytes, unchanged. Unlike
Cairo's ARGB32, there's no channel swap or premultiplication to work
around here.

GdkPixbuf needs no X11 connection to construct, save, or load a pixbuf
- confirmed with `env -u DISPLAY` before writing any conversion code -
so these tests run headless like the rest of ui/.
"""

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

import numpy as np

from orcshot.ui.gdk_convert import numpy_to_pixbuf, pixbuf_to_numpy


def solid_image(width, height, r, g, b, a=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


class TestNumpyToPixbuf:
    def test_channel_order_is_unchanged(self):
        image = solid_image(1, 1, 10, 20, 30, 255)
        pixbuf = numpy_to_pixbuf(image)
        assert list(bytes(pixbuf.get_pixels()))[:4] == [10, 20, 30, 255]

    def test_dimensions_match_the_array(self):
        image = solid_image(37, 23, 1, 2, 3)
        pixbuf = numpy_to_pixbuf(image)
        assert pixbuf.get_width() == 37
        assert pixbuf.get_height() == 23

    def test_has_alpha_is_set(self):
        pixbuf = numpy_to_pixbuf(solid_image(2, 2, 1, 2, 3))
        assert pixbuf.get_has_alpha() is True


class TestPixbufToNumpy:
    def test_round_trips_back_to_the_original_array(self):
        original = solid_image(10, 8, 12, 200, 77, 255)
        pixbuf = numpy_to_pixbuf(original)
        result = pixbuf_to_numpy(pixbuf)
        assert np.array_equal(result, original)

    def test_round_trips_through_a_real_saved_and_reloaded_png(self, tmp_path):
        # Exercises GdkPixbuf's own file I/O and whatever rowstride
        # padding it chooses on load, not just our own construction.
        original = solid_image(9, 5, 55, 66, 77, 255)
        path = tmp_path / "roundtrip.png"
        numpy_to_pixbuf(original).savev(str(path), "png", [], [])

        loaded = GdkPixbuf.Pixbuf.new_from_file(str(path))
        result = pixbuf_to_numpy(loaded)

        assert np.array_equal(result, original)

    def test_handles_a_pixbuf_without_an_alpha_channel(self):
        # A loaded PNG without alpha has get_n_channels() == 3; the
        # result must still come back as (H, W, 4) with alpha=255.
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 3, 2)
        pixbuf.fill(0x10203000)  # 0xRRGGBBAA-ish fill value GdkPixbuf accepts as RGB(A)

        result = pixbuf_to_numpy(pixbuf)

        assert result.shape == (2, 3, 4)
        assert np.all(result[:, :, 3] == 255)

    def test_output_shape_and_dtype(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 6, 4)
        result = pixbuf_to_numpy(pixbuf)
        assert result.shape == (4, 6, 4)
        assert result.dtype == np.uint8


# --- Property-based tests ---------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st

_dim = st.integers(min_value=1, max_value=20)
_channel = st.integers(min_value=0, max_value=255)


@given(_dim, _dim, _channel, _channel, _channel)
def test_images_always_round_trip_exactly(width, height, r, g, b):
    original = solid_image(width, height, r, g, b, a=255)
    result = pixbuf_to_numpy(numpy_to_pixbuf(original))
    assert np.array_equal(result, original)
