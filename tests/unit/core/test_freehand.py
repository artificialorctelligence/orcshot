"""FreehandShape: captured points, polyline hit-testing, tight bounds.

Behavioral port of FreehandContainer from the Windows source, scoped
deliberately: the source smooths captured points into GDI+ Bezier curves
via a point-duplication padding algorithm tied to GDI+'s AddBeziers API
(needs point count === 1 mod 3). That's a rendering-layer detail specific
to GDI+, not something a future Cairo-based renderer needs to reproduce
to get the same user-facing "smooth freehand stroke" behavior. What's
ported here is the portable part: the captured points themselves, and
hit-testing via distance to the nearest polyline segment, using the same
thickness+10 margin as ClickableAt's outline pen width.

Also deliberately different from the source: Bounds there is pinned to
the whole canvas (an implementation detail of how GDI+ coordinates were
set up for live mouse capture) while DrawingBounds is the tight box
around the actual stroke. This model only needs one concept of bounds,
and the tight box is the useful one for z-order aggregation.
"""

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import FreehandShape, ShapeStyle


class TestBounds:
    def test_bounds_is_the_tight_box_around_all_points(self):
        shape = FreehandShape(points=((10, 40), (30, 10), (50, 60)))
        assert shape.bounds == Rect(10, 10, 50, 60)

    def test_a_single_point_has_zero_area_bounds(self):
        shape = FreehandShape(points=((10, 10),))
        assert shape.bounds == Rect(10, 10, 10, 10)


class TestClickableAt:
    def make(self, points, line_thickness=3):
        return FreehandShape(points=points, style=ShapeStyle(line_thickness=line_thickness))

    def test_point_exactly_on_a_segment_is_clickable(self):
        shape = self.make([(0, 0), (100, 0)])
        assert shape.clickable_at(50, 0)

    def test_point_near_a_segment_within_the_margin_is_clickable(self):
        # margin = thickness + 10 = 13, so within 6.5px counts.
        shape = self.make([(0, 0), (100, 0)], line_thickness=3)
        assert shape.clickable_at(50, 6)

    def test_point_past_the_margin_is_not_clickable(self):
        shape = self.make([(0, 0), (100, 0)], line_thickness=3)
        assert not shape.clickable_at(50, 20)

    def test_checks_every_segment_not_just_the_first(self):
        # An L-shaped stroke: (0,0)->(0,100)->(100,100). A click near
        # the second leg must still register.
        shape = self.make([(0, 0), (0, 100), (100, 100)])
        assert shape.clickable_at(50, 100)

    def test_a_single_point_has_no_segments_and_is_never_clickable(self):
        shape = self.make([(10, 10)])
        assert not shape.clickable_at(10, 10)

    def test_zero_margin_disables_clicking(self):
        shape = self.make([(0, 0), (100, 0)], line_thickness=-15)  # margin = -5
        assert not shape.clickable_at(50, 0)
