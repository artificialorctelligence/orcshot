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
from typing import Tuple

from greenshot_linux.core.geometry import Rect

Color = Tuple[int, int, int, int]
TRANSPARENT: Color = (0, 0, 0, 0)
_DEFAULT_LINE_COLOR: Color = (255, 0, 0, 255)


def is_visible(color: Color) -> bool:
    """Ported from Colors.IsVisible: visible means alpha > 0."""
    return color[3] > 0


def _distance_point_to_segment(px, py, ax, ay, bx, by) -> float:
    abx, aby = bx - ax, by - ay
    length_sq = abx * abx + aby * aby
    if length_sq == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / length_sq))
    closest_x = ax + t * abx
    closest_y = ay + t * aby
    dx, dy = px - closest_x, py - closest_y
    return (dx * dx + dy * dy) ** 0.5


def _distance_point_to_rect_outline(x, y, rect: Rect) -> float:
    edges = (
        (rect.left, rect.top, rect.right, rect.top),
        (rect.right, rect.top, rect.right, rect.bottom),
        (rect.right, rect.bottom, rect.left, rect.bottom),
        (rect.left, rect.bottom, rect.left, rect.top),
    )
    return min(_distance_point_to_segment(x, y, *edge) for edge in edges)


def _distance_point_to_ellipse_outline(x, y, rect: Rect) -> float:
    # Approximation, not GDI+'s exact stroked-path geometry (which has
    # no simple closed form for a general ellipse): scale the point into
    # the ellipse's normalized unit-circle space, take the radial
    # distance from 1.0, and scale back by the smaller semi-axis. Exact
    # for a circle; close enough elsewhere for "is this click near the
    # outline", which is all a hit test needs.
    a, b = rect.width / 2, rect.height / 2
    if a == 0 or b == 0:
        return float("inf")
    cx, cy = rect.left + a, rect.top + b
    u, v = (x - cx) / a, (y - cy) / b
    radial = (u * u + v * v) ** 0.5
    return abs(radial - 1.0) * min(a, b)


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
        segments = zip(self.points, self.points[1:])
        return min(
            _distance_point_to_segment(x, y, ax, ay, bx, by)
            for (ax, ay), (bx, by) in segments
        ) <= margin / 2
