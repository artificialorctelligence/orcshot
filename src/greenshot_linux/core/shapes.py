"""Concrete annotation shapes.

Behavioral port of RectangleContainer, EllipseContainer, LineContainer,
and ArrowContainer from the Windows source. clickable_at is the part
worth porting carefully: a filled shape is clickable anywhere inside it
(RectangleClickableAt / EllipseClickableAt's fast path), a hollow one
only near its outline, and Line/Arrow use point-to-segment distance
since they have no interior at all.

Deliberate simplification vs. the Windows source: shapes store an
always-normalized Rect (Line/Arrow store true endpoints instead, see
below) rather than raw, possibly-negative Left/Top/Width/Height. Windows
keeps the unnormalized form to remember which corner is being dragged
during an interactive resize; that's UI-layer state this pure model
doesn't need yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Tuple

from shapely.affinity import scale as shapely_scale
from shapely.geometry import LinearRing, LineString, Point, Polygon

from greenshot_linux.core.geometry import Rect

Color = Tuple[int, int, int, int]
TRANSPARENT: Color = (0, 0, 0, 0)
_DEFAULT_LINE_COLOR: Color = (255, 0, 0, 255)


def is_visible(color: Color) -> bool:
    """Ported from Colors.IsVisible: visible means alpha > 0."""
    return color[3] > 0


def _distance_point_to_segment(px, py, ax, ay, bx, by) -> float:
    return Point(px, py).distance(LineString([(ax, ay), (bx, by)]))


def _distance_point_to_polyline(x, y, points: Sequence[Tuple[float, float]]) -> float:
    return Point(x, y).distance(LineString(points))


def _distance_point_to_rect_outline(x, y, rect: Rect) -> float:
    ring = LinearRing(
        [
            (rect.left, rect.top),
            (rect.right, rect.top),
            (rect.right, rect.bottom),
            (rect.left, rect.bottom),
        ]
    )
    return Point(x, y).distance(ring)


def _distance_point_to_ellipse_outline(x, y, rect: Rect) -> float:
    # Shapely-backed, not GDI+'s exact stroked-path geometry (which has
    # no simple closed form for a general ellipse either): a high-
    # resolution circle scaled into an ellipse via an affine transform.
    # Distance to its boundary is exact to within the polygon's
    # resolution (64 segments per quadrant here), which is far tighter
    # than a hit-test margin ever needs to resolve.
    a, b = rect.width / 2, rect.height / 2
    if a == 0 or b == 0:
        return float("inf")
    cx, cy = rect.left + a, rect.top + b
    circle = Point(cx, cy).buffer(1, quad_segs=64)
    ellipse = shapely_scale(circle, xfact=a, yfact=b, origin=(cx, cy))
    return Point(x, y).distance(ellipse.exterior)


@dataclass(frozen=True)
class ShapeStyle:
    line_thickness: int = 2
    line_color: Color = _DEFAULT_LINE_COLOR
    fill_color: Color = TRANSPARENT
    shadow: bool = True


@dataclass(frozen=True)
class RectangleShape:
    bounds: Rect
    style: ShapeStyle = field(default_factory=ShapeStyle)

    def clickable_at(self, x: int, y: int) -> bool:
        if is_visible(self.style.fill_color) and self.bounds.contains(x, y):
            return True
        margin = self.style.line_thickness + 10
        if margin <= 0:
            return False
        return _distance_point_to_rect_outline(x, y, self.bounds) <= margin / 2


@dataclass(frozen=True)
class EllipseShape:
    bounds: Rect
    style: ShapeStyle = field(default_factory=ShapeStyle)

    def clickable_at(self, x: int, y: int) -> bool:
        if is_visible(self.style.fill_color) and self.bounds.contains(x, y):
            return True
        margin = self.style.line_thickness + 10
        if margin <= 0:
            return False
        return _distance_point_to_ellipse_outline(x, y, self.bounds) <= margin / 2


@dataclass(frozen=True)
class LineShape:
    """Defined by its true endpoints, not just a bounding Rect.

    Two diagonals of the same bounding box are different lines — a
    line from (0,0) to (10,10) and one from (10,0) to (0,10) share an
    identical normalized Rect but are not the same segment. Reducing
    this to bounds-only would silently pick the wrong diagonal.
    """

    start: Tuple[int, int]
    end: Tuple[int, int]
    style: ShapeStyle = field(default_factory=ShapeStyle)

    _hit_margin = 5

    @property
    def bounds(self) -> Rect:
        (x1, y1), (x2, y2) = self.start, self.end
        return Rect.from_points(x1, y1, x2, y2)

    def clickable_at(self, x: int, y: int) -> bool:
        margin = self.style.line_thickness + self._hit_margin
        if margin <= 0:
            return False
        (x1, y1), (x2, y2) = self.start, self.end
        return _distance_point_to_segment(x, y, x1, y1, x2, y2) <= margin / 2


class ArrowShape(LineShape):
    # Ported as-is from the source: LineContainer uses thickness + 5,
    # ArrowContainer uses thickness + 10. A real asymmetry in Greenshot,
    # not a typo to "fix" in a faithful port.
    _hit_margin = 10


@dataclass(frozen=True)
class FreehandShape:
    """A captured mouse-drag stroke: a polyline through ``points``.

    See the module-level note in test_freehand.py for what's
    deliberately not ported: GDI+-specific Bezier-smoothing padding.
    """

    points: Tuple[Tuple[int, int], ...]
    style: ShapeStyle = field(default_factory=lambda: ShapeStyle(fill_color=TRANSPARENT))

    @property
    def bounds(self) -> Rect:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return Rect(min(xs), min(ys), max(xs), max(ys))

    def clickable_at(self, x: int, y: int) -> bool:
        margin = self.style.line_thickness + 10
        if margin <= 0 or len(self.points) < 2:
            return False
        return _distance_point_to_polyline(x, y, self.points) <= margin / 2


@dataclass(frozen=True)
class TextShape:
    """Extends RectangleContainer's fields in the source (same
    line/fill/shadow box styling) but deliberately has no clickable_at:
    TextContainer's override reverts to the *base* DrawableContainer
    hit test rather than inheriting RectangleContainer's fill-aware
    outline test, and that base behavior is exactly Layer.hit_test's
    existing bounds-inflate-5 fallback.
    """

    bounds: Rect
    text: str
    font_family: str = "sans-serif"
    font_size: float = 11.0
    bold: bool = False
    italic: bool = False
    horizontal_alignment: str = "center"  # "near" | "center" | "far"
    vertical_alignment: str = "center"  # "near" | "center" | "far"
    style: ShapeStyle = field(default_factory=ShapeStyle)


@dataclass(frozen=True)
class SpeechBubbleShape:
    """A TextShape-like box with a triangular tail pointing at ``target``.

    ``bubble_bounds`` mirrors the source's Bounds (the bubble rectangle
    only, used for the interior-click fast path); ``bounds`` mirrors the
    source's separate, wider DrawingBounds concept (bubble unioned with
    the tail's own extent), which is what Layer needs for z-order
    aggregation. See test_speech_bubble.py for the deliberate
    simplification versus the source: no corner-rounding in the hit
    test (it doesn't change what counts as "inside"), and the tail hit
    test is filled-triangle-plus-margin rather than the source's
    outline-only GraphicsPath.Widen band.

    The tail hit test uses distance-to-polygon, not strict
    Polygon.contains: contains() excludes the boundary under GEOS/OGC
    semantics, and the triangle's apex — the exact point a user would
    click to grab the bubble by its pointer tip — is itself a boundary
    vertex. A property test caught this (asserting the apex is always
    clickable, which failed under strict containment); the fix also
    brings the tail in line with every other shape here, none of which
    use exact/strict containment for hit-testing.
    """

    bubble_bounds: Rect
    target: Tuple[int, int]
    text: str
    font_family: str = "sans-serif"
    font_size: float = 20.0
    bold: bool = True
    italic: bool = False
    horizontal_alignment: str = "center"
    vertical_alignment: str = "center"
    style: ShapeStyle = field(
        default_factory=lambda: ShapeStyle(
            line_color=(0, 0, 255, 255),
            fill_color=(255, 255, 255, 255),
            shadow=False,
        )
    )

    def _tail_triangle(self):
        cx = self.bubble_bounds.left + self.bubble_bounds.width / 2
        cy = self.bubble_bounds.top + self.bubble_bounds.height / 2
        tx, ty = self.target
        dx, dy = tx - cx, ty - cy
        length = (dx * dx + dy * dy) ** 0.5
        if length == 0:
            return None  # target coincides with center: no tail direction

        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendicular to the center->target direction

        tail_width = (abs(self.bubble_bounds.width) + abs(self.bubble_bounds.height)) / 20
        tail_width = min(abs(self.bubble_bounds.width) / 2, tail_width)
        tail_width = min(abs(self.bubble_bounds.height) / 2, tail_width)

        base_left = (cx + tail_width * px, cy + tail_width * py)
        base_right = (cx - tail_width * px, cy - tail_width * py)
        apex = (float(tx), float(ty))
        return base_left, base_right, apex

    @property
    def bounds(self) -> Rect:
        triangle = self._tail_triangle()
        if triangle is None:
            return self.bubble_bounds
        xs = [p[0] for p in triangle]
        ys = [p[1] for p in triangle]
        tail_bounds = Rect(min(xs), min(ys), max(xs), max(ys))
        return self.bubble_bounds.union(tail_bounds)

    def clickable_at(self, x: int, y: int) -> bool:
        if self.bubble_bounds.contains(x, y):
            return True
        margin = self.style.line_thickness + 10
        if margin > 0 and _distance_point_to_rect_outline(x, y, self.bubble_bounds) <= margin / 2:
            return True
        triangle = self._tail_triangle()
        if triangle is not None and Point(x, y).distance(Polygon(triangle)) <= margin / 2:
            return True
        return False
