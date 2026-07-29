"""Pure pixel-format conversion for XFixes cursor images - no live X11
display needed for this part; see test_cursor_backend_contract.py for
the live-display coverage of X11CursorBackend itself.
"""

import numpy as np

from greenshot_linux.capture.x11_cursor import cursor_image_to_rgba


class TestCursorImageToRgba:
    def test_fully_opaque_red_pixel(self):
        # premultiplication is a no-op at full alpha, same as everywhere
        # else in this codebase.
        image = cursor_image_to_rgba(1, 1, [0xFFFF0000])
        assert tuple(image[0, 0]) == (255, 0, 0, 255)

    def test_fully_opaque_green_and_blue(self):
        image = cursor_image_to_rgba(1, 2, [0xFF00FF00, 0xFF0000FF])
        assert tuple(image[0, 0]) == (0, 255, 0, 255)
        assert tuple(image[1, 0]) == (0, 0, 255, 255)

    def test_fully_transparent_pixel_has_no_color_leakage(self):
        image = cursor_image_to_rgba(1, 1, [0x00000000])
        assert tuple(image[0, 0]) == (0, 0, 0, 0)

    def test_half_alpha_premultiplied_white_is_unpremultiplied_to_straight_alpha(self):
        # premultiplied white at ~50% alpha: R=G=B=alpha (128), since
        # premultiplied_channel = straight_channel * alpha / 255 and
        # straight white is 255 - un-premultiplying should recover
        # (255, 255, 255, 128), not the premultiplied (128, 128, 128, 128).
        pixel = (128 << 24) | (128 << 16) | (128 << 8) | 128
        image = cursor_image_to_rgba(1, 1, [pixel])
        assert tuple(image[0, 0]) == (255, 255, 255, 128)

    def test_shape_and_dtype(self):
        image = cursor_image_to_rgba(3, 2, [0] * 6)
        assert image.shape == (2, 3, 4)
        assert image.dtype == np.uint8

    def test_row_major_pixel_order(self):
        # row 0: red, blue; row 1: green, white
        pixels = [0xFFFF0000, 0xFF0000FF, 0xFF00FF00, 0xFFFFFFFF]
        image = cursor_image_to_rgba(2, 2, pixels)
        assert tuple(image[0, 0]) == (255, 0, 0, 255)
        assert tuple(image[0, 1]) == (0, 0, 255, 255)
        assert tuple(image[1, 0]) == (0, 255, 0, 255)
        assert tuple(image[1, 1]) == (255, 255, 255, 255)
