"""Value- and geometry-level tests for ui/magnifier.py's loupe drawing.

test_magnifier.py covers the shape of the thing (something is painted, it
lands at the destination, dest_pos decouples the two coordinate spaces) on
a *solid-colour* source, where every pixel is interchangeable - so reading
the wrong source pixel, shifting the crop by one at a screen edge, or
sliding the crosshair by a pixel are all invisible to it. These tests use a
source whose every pixel has a distinct colour, so the assertions are on
values and exact positions instead.

Geometry, once, so the arithmetic below reads: the loupe is drawn with
diameter d at dest_pos + offset, so its centre is dest + d/2 and its clip
circle has radius d/2. Source pixels land as d/source_size squares
(nearest-neighbour), the white ring's 2px stroke is centred on radius
d/2 - 1, the crosshair's 2px black core sits on the cursor's own pixel with
a 6px gap around it and 70%-of-radius arms, outlined 4px white, and the
crosshair is clipped to radius d/2 - 2 so it never touches the ring.

Headless: Cairo needs no display. Helpers are copied rather than imported -
pytest's importlib mode means test modules must not import each other.
"""

import math

import cairo
import numpy as np

from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.magnifier import draw_magnifier

CANVAS = 240


def varied_image(width=200, height=200):
    """A capture-shaped RGBA array whose every pixel is a different colour:
    red identifies the column and green the row (3 and 7 are coprime with
    200, so neither repeats within the image), blue mixes both. Kept inside
    20..219 so no source pixel can be mistaken for the loupe's own pure
    white ring/outline or pure black crosshair core."""
    y, x = np.mgrid[0:height, 0:width]
    image = np.empty((height, width, 4), dtype=np.uint8)
    image[:, :, 0] = (17 + 3 * x) % 200 + 20
    image[:, :, 1] = (31 + 7 * y) % 200 + 20
    image[:, :, 2] = (11 * x + 13 * y) % 200 + 20
    image[:, :, 3] = 255
    return image


def render(image, cursor, offset=(10, 10), diameter=200, source_size=25, dest_pos=(0, 0), canvas=CANVAS):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas, canvas)
    ctx = cairo.Context(surface)
    draw_magnifier(ctx, image, cursor, offset, diameter, source_size, dest_pos=dest_pos)
    return cairo_surface_to_numpy(surface)


def rgb_at(result, x, y):
    return tuple(int(v) for v in result[y, x, :3])


def source_rgb(image, x, y):
    return tuple(int(v) for v in image[y, x, :3])


def radius_map(canvas, center):
    y, x = np.mgrid[0:canvas, 0:canvas]
    return np.hypot(x + 0.5 - center[0], y + 0.5 - center[1])


def pure_white(result):
    return (result[:, :, 3] == 255) & (result[:, :, :3] == 255).all(axis=2)


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


class TestTheCropItReads:
    def test_source_size_decides_the_crop_not_the_default_patch_size(self):
        # A 9x9 crop around (100, 100) is image[96:105, 96:105]; the 25x25
        # default would be image[88:113, ...] and show different pixels.
        image = varied_image()
        result = render(image, cursor=(100, 100), diameter=180, source_size=9)
        # dest (10, 10), scale 180/9 = 20: device (40, 40) samples source
        # (1, 1) of the crop, i.e. image[97, 97].
        assert rgb_at(result, 40, 40) == source_rgb(image, 97, 97)
        # device (160, 70) -> crop (7, 3) -> image[99, 103]
        assert rgb_at(result, 160, 70) == source_rgb(image, 103, 99)

    def test_the_crop_is_clamped_to_the_right_and_bottom_edges(self):
        # cursor (195, 195) in a 200x200 image: a centred 25x25 crop would
        # start at 183 and read 8px past the edge, so it starts at 175
        # instead and stays a full 25 wide.
        image = varied_image()
        result = render(image, cursor=(195, 195))
        # dest (10, 10), scale 8: device (46, 110) -> crop (4, 12) ->
        # image[187, 179]
        assert rgb_at(result, 46, 110) == source_rgb(image, 179, 187)
        # device (110, 46) -> crop (12, 4) -> image[179, 187]
        assert rgb_at(result, 110, 46) == source_rgb(image, 187, 179)

    def test_the_crop_is_clamped_to_the_left_and_top_edges(self):
        # cursor (6, 7): a centred 25x25 crop would start at (-6, -5), so it
        # starts at exactly (0, 0) - not 1, which would read the wrong
        # column and row for every pixel in the loupe.
        image = varied_image()
        result = render(image, cursor=(6, 7))
        # dest (10, 10), scale 8: device (110, 110) -> crop (12, 12) ->
        # image[12, 12]
        assert rgb_at(result, 110, 110) == source_rgb(image, 12, 12)
        assert rgb_at(result, 46, 46) == source_rgb(image, 4, 4)

    def test_an_image_smaller_than_the_crop_is_used_whole(self):
        # The eyedropper's pre-cropped patch can be smaller than
        # source_size; the crop then starts at 0, not 1.
        image = varied_image(width=10, height=10)
        result = render(image, cursor=(5, 5))
        # dest (10, 10), scale 200/10 = 20: device (60, 60) -> source
        # (2, 2), device (160, 60) -> source (7, 2)
        assert rgb_at(result, 60, 60) == source_rgb(image, 2, 2)
        assert rgb_at(result, 160, 60) == source_rgb(image, 7, 2)

    def test_a_one_pixel_wide_source_still_draws(self):
        image = varied_image(width=1, height=10)
        result = render(image, cursor=(0, 5))
        assert result[:, :, 3].max() > 0
        # scale_x 200, scale_y 20: device (60, 110) -> source (0, 5)
        assert rgb_at(result, 60, 110) == source_rgb(image, 0, 5)

    def test_a_one_pixel_tall_source_still_draws(self):
        image = varied_image(width=10, height=1)
        result = render(image, cursor=(5, 0))
        assert result[:, :, 3].max() > 0
        # scale_x 20, scale_y 200: device (60, 160) -> source (2, 0)
        assert rgb_at(result, 60, 160) == source_rgb(image, 2, 0)

    def test_an_empty_source_draws_nothing_at_all(self):
        # Either dimension being zero has to bail *before* the scale
        # factors are computed - diameter / 0 is a ZeroDivisionError, and
        # this is the guard against a degenerate frozen image reaching here.
        for image in (varied_image(width=10, height=0), varied_image(width=0, height=10)):
            result = render(image, cursor=(5, 5))
            assert result[:, :, 3].max() == 0


class TestWhereItDraws:
    def test_the_loupe_is_exactly_diameter_wide_at_the_destination(self):
        image = varied_image()
        result = render(image, cursor=(100, 100))
        # dest (10, 10), diameter 200 -> centre (110, 110), radius 100
        assert result[110, 205, 3] > 0     # 95px out: inside
        assert result[110, 215, 3] == 0    # 105px out: nothing

    def test_the_x_offset_moves_it_horizontally_and_the_y_offset_does_not(self):
        image = varied_image()
        result = render(image, cursor=(100, 100), offset=(10, 40), canvas=300)
        # dest (10, 50) -> centre (110, 150), so the loupe's left edge is at
        # x=10 regardless of the y offset.
        assert result[150, 12, 3] > 0
        assert result[150, 5, 3] == 0

    def test_nothing_is_painted_outside_the_loupes_own_circle(self):
        # cursor (191, 192) clamps the crop, putting the cursor's pixel -
        # and so the crosshair - well off centre, where its 70%-radius arms
        # run past the circle's edge and have to be clipped by it.
        image = varied_image()
        result = render(image, cursor=(191, 192))
        outside = radius_map(CANVAS, (110, 110)) > 101.0
        assert result[:, :, 3][outside].max() == 0

    def test_the_crosshair_arm_reaches_the_edge_of_the_clip_circle(self):
        # The same off-centre crosshair, from the other side: the arm is
        # clipped by the circle, not by a smaller shape, so it is still
        # being drawn 92px out from the centre.
        image = varied_image()
        result = render(image, cursor=(191, 192))
        assert rgb_at(result, 193, 150) == BLACK


class TestTheRing:
    def test_the_white_ring_sits_just_inside_the_loupes_edge(self):
        image = varied_image()
        result = render(image, cursor=(100, 100))
        # centre (110, 110), radius 100: the 2px stroke is centred on
        # radius 99, so x=11 on the centre row is fully inside it.
        assert rgb_at(result, 11, 110) == WHITE
        assert result[110, 11, 3] == 255

    def test_the_ring_goes_all_the_way_round(self):
        image = varied_image()
        result = render(image, cursor=(100, 100))
        rr = radius_map(CANVAS, (110, 110))
        y, x = np.mgrid[0:CANVAS, 0:CANVAS]
        angle = np.arctan2(y + 0.5 - 110, x + 0.5 - 110)
        band = (rr > 96) & (rr < 102) & (angle > 0.1) & (angle < 0.9)
        assert pure_white(result)[band].sum() > 40

    def test_the_zoomed_pixels_fill_the_whole_circle(self):
        # The clip is the full circle, not an arc: a point near the rim at a
        # shallow angle is inside it.
        image = varied_image()
        result = render(image, cursor=(100, 100))
        # 93px out at ~0.5 rad; source (22, 18) of the crop -> image[106, 110]
        assert result[154, 191, 3] == 255
        assert rgb_at(result, 191, 154) == source_rgb(image, 110, 106)


class TestTheCrosshair:
    """cursor (100, 195) in a 200x200 image clamps the crop vertically only,
    so the cursor lands at (12, 20) within it - deliberately asymmetric, so
    an x/y mix-up in either the crop offset or the crosshair position moves
    the cross. dest (10, 10), scale 8 -> cross at (110, 174)."""

    IMAGE = varied_image()
    CURSOR = (100, 195)

    def result(self):
        return render(self.IMAGE, cursor=self.CURSOR)

    def test_the_cursors_own_pixel_shows_through_the_gap_at_the_middle(self):
        # The deliberate gap: every arm stops 6px short of the cross, so the
        # pixel being magnified is never covered by the crosshair. Any arm
        # drawn across the middle instead of away from it lands here.
        result = self.result()
        assert rgb_at(result, 110, 174) == source_rgb(self.IMAGE, 100, 195)

    def test_the_vertical_arm_is_a_black_core_in_a_white_outline(self):
        result = self.result()
        row = 130                                   # up the arm, above the gap
        assert rgb_at(result, 107, row) == source_rgb(self.IMAGE, 100, 190)
        assert rgb_at(result, 108, row) == WHITE
        assert rgb_at(result, 109, row) == BLACK
        assert rgb_at(result, 110, row) == BLACK
        assert rgb_at(result, 111, row) == WHITE
        assert rgb_at(result, 112, row) == source_rgb(self.IMAGE, 100, 190)

    def test_the_horizontal_arm_is_a_black_core_in_a_white_outline(self):
        result = self.result()
        col = 60                                    # along the arm, left of the gap
        assert rgb_at(result, col, 171) == source_rgb(self.IMAGE, 94, 195)
        assert rgb_at(result, col, 172) == WHITE
        assert rgb_at(result, col, 173) == BLACK
        assert rgb_at(result, col, 174) == BLACK
        assert rgb_at(result, col, 175) == WHITE
        assert rgb_at(result, col, 176) == source_rgb(self.IMAGE, 94, 195)

    def test_the_arms_are_70_percent_of_the_radius_long(self):
        # Centred cross this time: radius 100, so the arms reach 70px and
        # stop - they are not clipped-to-the-circle long.
        image = varied_image()
        result = render(image, cursor=(100, 100))
        assert rgb_at(result, 110, 45) == BLACK                       # 65px up: arm
        assert rgb_at(result, 110, 35) == source_rgb(image, 100, 91)  # 75px up: not
