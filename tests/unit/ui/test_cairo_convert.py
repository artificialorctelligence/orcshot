"""numpy RGBA <-> Cairo ARGB32 conversion.

Cairo's FORMAT_ARGB32 stores each pixel as a single 32-bit int (0xAARRGGBB)
in *native-endian* order with *premultiplied* alpha. On this machine
(x86_64, little-endian) that means the four bytes appear in memory as
B, G, R, A — the reverse of our R, G, B, A convention — confirmed
empirically (see scratchpad/probe_cairo.py) before writing any
conversion code: drawing pure red via Cairo's own APIs and reading the
raw surface bytes back out gave [0, 0, 255, 255], i.e. B=0, G=0, R=255,
A=255.

Premultiplication was a no-op for every image this app produced until
the auto-captured cursor (capture/x11_cursor.py) - the first source
with genuinely partial-alpha pixels (anti-aliased edges), which
surfaced this as a real visible bug (color fringing at cursor edges)
rather than a latent one. This module now premultiplies on the way
into a Cairo surface and un-premultiplies on the way back out, mirroring
x11_cursor.py's own _unpremultiply - see
test_partial_alpha_round_trips_correctly.

cairo.ImageSurface is a pure in-memory/software surface — no X11
connection needed, so these tests run headless like the rest of core.
"""

import cairo
import numpy as np

from orcshot.ui.cairo_convert import cairo_surface_to_numpy, numpy_to_cairo_surface


def solid_image(width, height, r, g, b, a=255):
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :] = (r, g, b, a)
    return image


class TestNumpyToCairoSurface:
    def test_channel_order_is_swapped_to_bgra_in_memory(self):
        # Matches the empirically-confirmed probe: a red RGBA pixel
        # (255,0,0,255) must land as bytes [0,0,255,255] in the surface.
        image = solid_image(1, 1, 255, 0, 0, 255)

        surface = numpy_to_cairo_surface(image)
        surface.flush()

        assert list(surface.get_data())[:4] == [0, 0, 255, 255]

    def test_surface_dimensions_match_the_array(self):
        image = solid_image(37, 23, 10, 20, 30)
        surface = numpy_to_cairo_surface(image)
        assert surface.get_width() == 37
        assert surface.get_height() == 23

    def test_handles_a_width_whose_stride_needs_padding(self):
        # ARGB32 happens to need no padding beyond width*4 (each pixel
        # is already a 4-byte-aligned unit), but the conversion must use
        # Cairo's own stride query rather than assuming that, so this
        # stays correct if a future format ever needs padding. An odd
        # width exercises the code path regardless.
        image = solid_image(5, 3, 1, 2, 3)
        surface = numpy_to_cairo_surface(image)
        assert surface.get_width() == 5
        assert surface.get_height() == 3

    def test_all_channels_round_trip_correctly(self):
        image = np.zeros((1, 3, 4), dtype=np.uint8)
        image[0, 0] = (10, 20, 30, 255)
        image[0, 1] = (100, 150, 200, 255)
        image[0, 2] = (0, 0, 0, 255)

        surface = numpy_to_cairo_surface(image)
        surface.flush()
        data = list(surface.get_data())

        assert data[0:4] == [30, 20, 10, 255]
        assert data[4:8] == [200, 150, 100, 255]
        assert data[8:12] == [0, 0, 0, 255]


class TestCairoSurfaceToNumpy:
    def test_round_trips_back_to_the_original_array(self):
        original = solid_image(10, 8, 12, 200, 77, 255)
        surface = numpy_to_cairo_surface(original)

        result = cairo_surface_to_numpy(surface)

        assert np.array_equal(result, original)

    def test_round_trips_content_actually_drawn_via_cairo(self):
        # Not just a numpy->surface->numpy identity check: draw with
        # Cairo's own APIs (as real rendering code will) and confirm
        # the colors come back correct, not channel-swapped.
        width, height = 4, 4
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        ctx.set_source_rgba(0.2, 0.4, 0.6, 1.0)  # -> approx (51, 102, 153)
        ctx.paint()
        surface.flush()

        result = cairo_surface_to_numpy(surface)

        assert np.array_equal(result[:, :, 0], np.full((height, width), 51))
        assert np.array_equal(result[:, :, 1], np.full((height, width), 102))
        assert np.array_equal(result[:, :, 2], np.full((height, width), 153))
        assert np.all(result[:, :, 3] == 255)

    def test_output_shape_and_dtype(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 6, 4)
        result = cairo_surface_to_numpy(surface)
        assert result.shape == (4, 6, 4)
        assert result.dtype == np.uint8


def test_numpy_to_cairo_surface_premultiplies_partial_alpha():
    # 100 at alpha=128 premultiplies to round(100 * 128/255) = 50 -
    # confirms the stored bytes are actually scaled by alpha, not just
    # passed through (a round-trip-only test could pass by accident if
    # premultiply and un-premultiply were both silently no-ops).
    image = solid_image(1, 1, 100, 100, 100, a=128)
    surface = numpy_to_cairo_surface(image)
    surface.flush()
    assert list(surface.get_data())[:4] == [50, 50, 50, 128]


def test_partial_alpha_round_trips_correctly():
    # White at ~50% alpha: premultiplied channel = straight * alpha/255
    # = 255 * 128/255 = 128 exactly (no rounding error, since the 255
    # cancels) - same case test_x11_cursor.py's own unpremultiply test
    # uses, for an exact assertion rather than an approximate one.
    image = solid_image(1, 1, 255, 255, 255, a=128)
    surface = numpy_to_cairo_surface(image)
    result = cairo_surface_to_numpy(surface)
    assert tuple(result[0, 0]) == (255, 255, 255, 128)


def test_partial_alpha_round_trip_is_within_one_of_the_original():
    # Not every value cancels as cleanly as the white/alpha=128 case
    # above - 8-bit premultiplied alpha is inherently lossy for a
    # translucent pixel, same as x11_cursor.py's own _unpremultiply.
    # Documented rather than hidden: this asserts the tolerance, not
    # exact equality.
    image = solid_image(1, 1, 200, 100, 50, a=128)
    surface = numpy_to_cairo_surface(image)
    result = cairo_surface_to_numpy(surface)
    for original, recovered in zip((200, 100, 50), result[0, 0, :3]):
        assert abs(int(recovered) - original) <= 1
    assert result[0, 0, 3] == 128


# --- Property-based tests -------------------------------------------------

from hypothesis import given
from hypothesis import strategies as st

_dim = st.integers(min_value=1, max_value=20)
_channel = st.integers(min_value=0, max_value=255)


@given(_dim, _dim, _channel, _channel, _channel)
def test_opaque_images_always_round_trip_exactly(width, height, r, g, b):
    original = solid_image(width, height, r, g, b, a=255)
    result = cairo_surface_to_numpy(numpy_to_cairo_surface(original))
    assert np.array_equal(result, original)


_nonzero_alpha = st.integers(min_value=1, max_value=255)


@given(_dim, _dim, _channel, _channel, _channel, _nonzero_alpha)
def test_partial_alpha_round_trip_error_is_bounded_by_alpha_precision(width, height, r, g, b, a):
    # Alpha itself always round-trips exactly (never premultiplied).
    # RGB precision loss is inherent to 8-bit premultiplied alpha and
    # scales with 1/alpha: premultiplying rounds to the nearest integer
    # (max error 0.5) in *premultiplied* space, and un-premultiplying
    # divides back out by alpha/255, amplifying that error by roughly
    # 255/alpha - at very low alpha (e.g. alpha=1, ~0.4% opacity) most
    # of the original color is genuinely unrecoverable. Same property
    # any 8-bit premultiplied-alpha pipeline has (including Cairo's own
    # native compositing), not something this conversion could avoid -
    # the handpicked test above covers the realistic anti-aliased-edge
    # case (alpha=128) with a tight bound; this one just confirms the
    # error stays a well-behaved function of alpha rather than blowing
    # up unboundedly or leaking into the alpha channel itself.
    original = solid_image(width, height, r, g, b, a=a)
    result = cairo_surface_to_numpy(numpy_to_cairo_surface(original))
    assert np.array_equal(result[:, :, 3], original[:, :, 3])
    max_error = 256 // a + 2  # generous margin over the ~127.5/a + 1 worst case
    diff = np.abs(result[:, :, :3].astype(int) - original[:, :, :3].astype(int))
    assert np.all(diff <= max_error)
