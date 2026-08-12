"""Cairo rendering of SvgShape.

Behavioral port of VectorGraphicsContainer.Draw, which caches a bitmap
rendered from the SVG at bounds size and draws that. This port renders
directly onto the Cairo context instead, via librsvg's modern
render_document(ctx, viewport) API - no intermediate bitmap cache
needed, and it handles scaling the SVG's own intrinsic size to fill
bounds itself.
"""

import cairo

from orcshot.core.geometry import Rect
from orcshot.core.shapes import SvgShape
from orcshot.ui.cairo_convert import cairo_surface_to_numpy
from orcshot.ui.render import render_shape


def render_to_numpy(width, height, draw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    draw(ctx)
    surface.flush()
    return cairo_surface_to_numpy(surface)


RED_SQUARE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
<rect width="10" height="10" fill="#ff0000"/>
</svg>"""


class TestRenderSvg:
    def test_renders_svg_content_within_bounds(self):
        shape = SvgShape(Rect(10, 10, 30, 30), svg_data=RED_SQUARE_SVG)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[20, 20]) == (255, 0, 0, 255)

    def test_does_not_paint_outside_bounds(self):
        shape = SvgShape(Rect(10, 10, 30, 30), svg_data=RED_SQUARE_SVG)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        assert result[0, 0, 3] == 0

    def test_scales_the_intrinsic_svg_size_to_fill_bounds(self):
        # the SVG declares itself as 10x10, but bounds is 40x40 -
        # content must fill the whole box, not stay tiny/centered.
        shape = SvgShape(Rect(0, 0, 40, 40), svg_data=RED_SQUARE_SVG)
        result = render_to_numpy(40, 40, lambda ctx: render_shape(ctx, shape))
        assert tuple(result[2, 2]) == (255, 0, 0, 255)
        assert tuple(result[37, 37]) == (255, 0, 0, 255)
