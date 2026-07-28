"""Headless tests for the magnifier loupe's Cairo drawing - Cairo needs
no X11/display connection, same as ui/render.py's tests. Positioning/
sizing math is tested separately, and purely, in
tests/unit/core/test_magnifier.py.
"""

import cairo
import numpy as np

from greenshot_linux.ui.cairo_convert import cairo_surface_to_numpy
from greenshot_linux.ui.magnifier import draw_magnifier

CANVAS = 200


def render(frozen_image, cursor=(100, 100), offset=(20, 20), diameter=60, source_size=25):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    ctx = cairo.Context(surface)
    draw_magnifier(ctx, frozen_image, cursor, offset, diameter, source_size)
    return cairo_surface_to_numpy(surface)


def solid_image(color, size=200):
    image = np.zeros((size, size, 4), dtype=np.uint8)
    image[:, :] = color
    return image


class TestDrawMagnifier:
    def test_paints_something_visible_at_the_destination(self):
        image = render(solid_image((255, 0, 0, 255)))
        assert image[:, :, 3].max() > 0

    def test_paints_within_the_destination_circle_not_elsewhere(self):
        image = render(solid_image((255, 0, 0, 255)), offset=(20, 20), diameter=60)
        # far outside the destination rect (cursor 100,100 + offset
        # 20,20, diameter 60 -> roughly x,y in [120,180]) should stay
        # untouched.
        assert image[10, 10, 3] == 0

    def test_source_color_shows_through_the_loupe(self):
        image = render(solid_image((10, 200, 30, 255)), offset=(20, 20), diameter=60)
        # sample near the destination circle's center
        cx, cy = 100 + 20 + 30, 100 + 20 + 30
        pixel = image[cy, cx]
        assert pixel[3] > 0
        # allow for the crosshair drawn at dead center - sample just
        # off-center instead, still well within the circle
        pixel = image[cy - 10, cx - 10]
        assert tuple(pixel[:3]) == (10, 200, 30)

    def test_crosshair_arm_is_a_different_color_than_the_source(self):
        # not the exact center pixel - there's a deliberate gap right
        # at the cursor's own pixel (see draw_magnifier's docstring),
        # so the source color shows through there unobstructed.
        image = render(solid_image((10, 200, 30, 255)), offset=(20, 20), diameter=60)
        cx, cy = 100 + 20 + 30, 100 + 20 + 30
        arm_pixel = tuple(image[cy, cx + 15, :3])
        assert arm_pixel != (10, 200, 30)

    def test_handles_a_cursor_near_the_image_edge_without_crashing(self):
        image = solid_image((0, 0, 255, 255), size=200)
        result = render(image, cursor=(2, 2), offset=(20, 20), diameter=60)
        assert result[:, :, 3].max() > 0

    def test_handles_a_cursor_in_the_top_left_corner(self):
        image = solid_image((0, 0, 255, 255), size=200)
        result = render(image, cursor=(0, 0), offset=(20, 20), diameter=60)
        assert result[:, :, 3].max() > 0

    def test_different_diameters_produce_different_sized_content(self):
        small = render(solid_image((255, 255, 0, 255)), diameter=30)
        large = render(solid_image((255, 255, 0, 255)), diameter=90)
        small_opaque = (small[:, :, 3] > 0).sum()
        large_opaque = (large[:, :, 3] > 0).sum()
        assert large_opaque > small_opaque
