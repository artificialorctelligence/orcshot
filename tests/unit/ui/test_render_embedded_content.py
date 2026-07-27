"""Cairo rendering of IconShape, CursorShape, ImageShape.

Behavioral port of IconContainer/CursorContainer/ImageContainer's Draw:
all three just paint their stored bitmap scaled to fill bounds, with no
shadow for Icon/Cursor. ImageContainer's Draw additionally supports a
shadow - a deliberate simplification here: the source generates a
separate `_shadowBitmap` via CheckShadow (details not fully replicated);
this port instead tints the image's own RGB to black while keeping its
alpha channel, then paints that with per-step alpha via the same 5-step
DrawShadow offsets everything else uses, offset by the source's own
literal +1 "shadowOffset" on top.
"""

import cairo
import numpy as np

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import CursorShape, IconShape, ImageShape
from greenshot_linux.ui.cairo_convert import cairo_surface_to_numpy
from greenshot_linux.ui.render import render_shape


def render_to_numpy(width, height, draw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    draw(ctx)
    surface.flush()
    return cairo_surface_to_numpy(surface)


def solid_image(w, h, color):
    image = np.zeros((h, w, 4), dtype=np.uint8)
    image[:, :] = color
    return image


class TestRenderIcon:
    def test_paints_the_image_scaled_to_fill_bounds(self):
        image = solid_image(2, 2, (10, 20, 30, 255))
        shape = IconShape(Rect(5, 5, 25, 25), image=image)
        result = render_to_numpy(30, 30, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[15, 15]) == (10, 20, 30, 255)

    def test_does_not_paint_outside_bounds(self):
        image = solid_image(2, 2, (10, 20, 30, 255))
        shape = IconShape(Rect(5, 5, 25, 25), image=image)
        result = render_to_numpy(30, 30, lambda ctx: render_shape(ctx, shape))
        assert result[0, 0, 3] == 0


class TestRenderCursor:
    def test_paints_the_image_scaled_to_fill_bounds(self):
        image = solid_image(2, 2, (40, 50, 60, 255))
        shape = CursorShape(Rect(0, 0, 16, 16), image=image)
        result = render_to_numpy(16, 16, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[8, 8]) == (40, 50, 60, 255)


class TestRenderImage:
    def test_paints_the_image_scaled_to_fill_bounds(self):
        image = solid_image(4, 4, (70, 80, 90, 255))
        shape = ImageShape(Rect(10, 10, 30, 30), image=image)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[20, 20]) == (70, 80, 90, 255)

    def test_no_shadow_by_default(self):
        image = solid_image(4, 4, (70, 80, 90, 255))
        shape = ImageShape(Rect(10, 10, 30, 30), image=image, shadow=False)
        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape))
        band = result[32:40, 32:40]
        assert band[:, :, 3].max() == 0

    def test_shadow_paints_pixels_beyond_the_image_when_enabled(self):
        image = solid_image(4, 4, (70, 80, 90, 255))
        shape = ImageShape(Rect(10, 10, 30, 30), image=image, shadow=True)
        result = render_to_numpy(50, 50, lambda ctx: render_shape(ctx, shape))
        band = result[31:37, 31:37]
        assert band[:, :, 3].max() > 0
