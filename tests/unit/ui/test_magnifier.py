"""Headless tests for the magnifier loupe's Cairo drawing - Cairo needs
no X11/display connection, same as ui/render.py's tests. Positioning/
sizing math is tested separately, and purely, in
tests/unit/core/test_magnifier.py.
"""

import cairo
import numpy as np

from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.magnifier import draw_magnifier

CANVAS = 200


def render(frozen_image, cursor=(100, 100), offset=(20, 20), diameter=60, source_size=25, dest_pos=None):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS, CANVAS)
    ctx = cairo.Context(surface)
    draw_magnifier(ctx, frozen_image, cursor, offset, diameter, source_size, dest_pos=dest_pos)
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

    def test_dest_pos_decouples_where_it_draws_from_the_crop_source(self):
        # eyedropper.py/eyedropper_wayland.py pass an already-small,
        # pre-cropped patch as frozen_image, where cursor's position
        # *within that patch* has nothing to do with where the loupe
        # should be drawn on the real overlay window - confirmed live
        # that omitting dest_pos pinned the loupe near the origin
        # regardless of the real cursor position; this is the
        # regression test for that fix.
        patch = solid_image((10, 200, 30, 255), size=25)
        small_cursor_in_patch = (12, 12)
        far_away_dest = (150, 150)

        image = render(
            patch, cursor=small_cursor_in_patch, offset=(5, 5), diameter=40, source_size=25,
            dest_pos=far_away_dest,
        )

        # nothing painted near the origin (where it would land without
        # dest_pos, since cursor + offset would be ~(17, 17))
        assert image[10:20, 10:20, 3].max() == 0
        # something painted at the real destination instead
        assert image[far_away_dest[1] + 20, far_away_dest[0] + 20, 3] > 0

    def test_dest_pos_defaults_to_cursor_when_not_given(self):
        # region_select.py's usage: frozen_image and the drawing
        # context share a coordinate space, so cursor alone is already
        # the correct draw position - must stay unchanged.
        with_default = render(solid_image((10, 200, 30, 255)), cursor=(100, 100), offset=(20, 20), diameter=60)
        explicit_same = render(
            solid_image((10, 200, 30, 255)), cursor=(100, 100), offset=(20, 20), diameter=60, dest_pos=(100, 100),
        )
        assert np.array_equal(with_default, explicit_same)
