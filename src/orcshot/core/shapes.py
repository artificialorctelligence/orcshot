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

import secrets
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Sequence, Tuple

import numpy as np
from shapely.affinity import scale as shapely_scale
from shapely.geometry import LinearRing, LineString, Point, Polygon

from orcshot.core.geometry import Rect

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


def _rectangle_clickable_at(bounds: Rect, margin: int, fill_color: Color, x: int, y: int) -> bool:
    # Mirrors RectangleContainer.RectangleClickableAt: margin is passed
    # explicitly rather than derived from line_thickness here, since
    # StepLabelShape calls this with a hardcoded margin of 0 (see
    # StepLabelContainer.ClickableAt in the source), not the usual +10.
    if is_visible(fill_color) and bounds.contains(x, y):
        return True
    if margin <= 0:
        return False
    return _distance_point_to_rect_outline(x, y, bounds) <= margin / 2


def _ellipse_clickable_at(bounds: Rect, margin: int, fill_color: Color, x: int, y: int) -> bool:
    # Mirrors EllipseContainer.EllipseClickableAt; see the note above.
    if is_visible(fill_color) and bounds.contains(x, y):
        return True
    if margin <= 0:
        return False
    return _distance_point_to_ellipse_outline(x, y, bounds) <= margin / 2


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
        return _rectangle_clickable_at(
            self.bounds, self.style.line_thickness + 10, self.style.fill_color, x, y
        )


@dataclass(frozen=True)
class EllipseShape:
    bounds: Rect
    style: ShapeStyle = field(default_factory=ShapeStyle)

    def clickable_at(self, x: int, y: int) -> bool:
        return _ellipse_clickable_at(
            self.bounds, self.style.line_thickness + 10, self.style.fill_color, x, y
        )


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
    # line_color deliberately black, not SpeechbubbleContainer.cs:80's
    # own Blue default - a direct user request, not a citation error
    # (see core/tools.py's matching _TOOL_STYLE_DEFAULTS entry).
    style: ShapeStyle = field(
        default_factory=lambda: ShapeStyle(
            line_color=(0, 0, 0, 255),
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


@dataclass(frozen=True)
class StepLabelShape:
    """An auto-numbered circle. See the module docstring in
    test_step_label.py for the ClickableAt margin=0 quirk this ports
    faithfully, and for why renumbering is a standalone function rather
    than shape state tied to a parent container.
    """

    bounds: Rect
    number: int
    style: ShapeStyle = field(
        default_factory=lambda: ShapeStyle(
            fill_color=(139, 0, 0, 255),  # DarkRed
            line_color=(255, 255, 255, 255),  # White
            line_thickness=0,
            shadow=False,
        )
    )

    def clickable_at(self, x: int, y: int) -> bool:
        # Ported as-is: the source passes a literal 0 here, not
        # line_thickness + 10 the way EllipseContainer's own
        # ClickableAt does.
        return _ellipse_clickable_at(self.bounds, 0, self.style.fill_color, x, y)


def renumber_step_labels(
    labels: Sequence[StepLabelShape], start: int = 1
) -> list[StepLabelShape]:
    """Reassign sequential numbers in the given order, starting at
    ``start`` (matching the source's per-Surface CounterStart, default
    1). Returns new instances; StepLabelShape is frozen.
    """
    return [replace(label, number=start + i) for i, label in enumerate(labels)]


@dataclass(frozen=True)
class IconShape:
    """Behavioral port of IconContainer: no ClickableAt override, so
    Layer.hit_test's generic bounds-inflate-5 fallback applies as-is.
    """

    bounds: Rect
    image: np.ndarray = field(compare=False, repr=False)


@dataclass(frozen=True)
class CursorShape:
    """Behavioral port of CursorContainer: no ClickableAt override."""

    bounds: Rect
    image: np.ndarray = field(compare=False, repr=False)


@dataclass(frozen=True)
class ImageShape:
    """Behavioral port of ImageContainer: no ClickableAt override. The
    only field the source actually has (besides the image itself).
    """

    bounds: Rect
    image: np.ndarray = field(compare=False, repr=False)
    shadow: bool = False


@dataclass(frozen=True)
class SvgShape:
    """Behavioral port of SvgContainer (via VectorGraphicsContainer):
    no ClickableAt override, no fields of its own beyond the markup.
    """

    bounds: Rect
    svg_data: str


class HighlightMode(str, Enum):
    # Windows' own PreparedFilter enum spells this TEXT_HIGHTLIGHT (a
    # typo in the real source, HighlightContainer.cs) - corrected here
    # since it's an internal identifier, not user-facing text; noted
    # for traceability back to the source, not reproduced.
    TEXT_HIGHLIGHT = "text_highlight"
    AREA_HIGHLIGHT = "area_highlight"
    GRAYSCALE = "grayscale"
    MAGNIFICATION = "magnification"


@dataclass(frozen=True)
class HighlightShape:
    """Behavioral port of HighlightContainer: like ObfuscateShape, has
    no visual content of its own - rendering it means re-filtering the
    region of the original captured image under ``bounds`` (see
    ui/render.py's render_highlight), using the highlight_text/
    highlight_area/highlight_grayscale/highlight_magnify functions in
    filters.py.

    Unlike every ObfuscateMode, two of these four modes act as a
    "spotlight" rather than filtering the region itself - real
    Windows' AREA_HIGHLIGHT (BrightnessFilter+BlurFilter, both with
    their own Invert=true) and GRAYSCALE (GrayscaleFilter, Invert=true)
    apply their effect to the rest of the *whole image*, excluding
    ``bounds``, leaving the bounds themselves untouched - the opposite
    direction from every Obfuscate mode, which always filters *inside*
    its own bounds and leaves everything else alone.

    ``fill_color`` is TEXT_HIGHLIGHT's own highlighter-marker color
    (default opaque yellow, matching HighlightFilter's own
    FILL_COLOR default) - unused by every other mode.

    ``brightness``/``blur_radius`` are AREA_HIGHLIGHT's own two
    stacked filters' fields (BrightnessFilter's own BRIGHTNESS default
    0.9, BlurFilter's own BLUR_RADIUS default 3, both applied together
    in the source, not swappable independently) - unused by every
    other mode.

    ``magnification_factor`` is MAGNIFICATION's own zoom level
    (MagnifierFilter's own MAGNIFICATION_FACTOR default 2) - unused by
    every other mode.

    No ``seed`` field, unlike ObfuscateShape - none of these four
    modes use randomness (no Pixelize/Scramble equivalent here).
    """

    bounds: Rect
    mode: HighlightMode = HighlightMode.TEXT_HIGHLIGHT
    fill_color: Color = (255, 255, 0, 255)
    brightness: float = 0.9
    blur_radius: int = 3
    magnification_factor: int = 2


class ObfuscateMode(str, Enum):
    BLUR = "blur"
    PIXELIZE = "pixelize"
    # Both added for task #60, no Windows equivalent - see filters.py's
    # solid_fill()/scramble() docstrings for the security reasoning:
    # Blur/Pixelize are both faithful ports of the real Windows filters,
    # but neither is a genuine security guarantee (both are documented-
    # reversible via public tools like Depix/unredacter, even with
    # Pixelize's own noise hardening - see REQUIREMENTS.md's task #60
    # writeup for the full research trail this was built from).
    SOLID_FILL = "solid_fill"
    SCRAMBLE = "scramble"


@dataclass(frozen=True)
class ObfuscateShape:
    """Behavioral port of ObfuscateContainer: has no visual content of
    its own, unlike every other shape here. Rendering it means
    re-filtering the region of the *original captured image* under
    ``bounds`` (see ui/render.py's render_obfuscate), using the
    box_blur/pixelize/solid_fill/scramble functions in filters.py. No
    ClickableAt override in the source, so this falls through to the
    generic bounds-inflate-5 hit test, same as TextShape/IconShape/
    CursorShape/ImageShape/SvgShape.

    ``amount`` is blur radius when ``mode`` is BLUR, pixel block size
    when PIXELIZE, unused by SOLID_FILL/SCRAMBLE - a deliberate
    simplification of the source, which gives BlurFilter and
    PixelizationFilter independent fields (BLUR_RADIUS=3, PIXEL_SIZE=5)
    that keep their own values independently as you switch between
    them.

    ``fill_color`` is the opaque color SOLID_FILL paints the region
    with (default black, the standard redaction convention); unused by
    every other mode.

    ``fill_text``/``text_color`` (task #60 follow-up) are SOLID_FILL's
    own optional preset label - one of a fixed set ("REDACTED",
    "CENSORED", etc., see ui/editor_window.py's own preset list) drawn
    centered over the fill, or "" (the default) for a plain box. No
    free-text entry by design - deliberate user call: anyone wanting
    custom text can already use the separate Text tool instead, so
    this doesn't need to reuse TextShape's own click-to-edit machinery.
    Unused by every other mode. Default text_color is white, legible
    against fill_color's own default black.

    ``seed`` drives Pixelize's jittered-noise RNG (filters.py's
    pixelize) and Scramble's own noise (filters.py's scramble) when
    nothing else overrides it - drawn fresh from the OS CSPRNG once, at
    shape creation (ui/render.py's render_obfuscate still honors an
    explicit rng= override for tests). Pinning it here means the same
    shape renders identical noise on every redraw instead of reshuffling
    on every unrelated repaint (moving any other shape triggers a full
    canvas redraw); it stays *between* shapes and sessions genuinely
    unpredictable, matching the real Windows PixelizationFilter's own
    security intent (a fresh CryptoRandomBuffer per Apply() call - see
    filters.py's _default_rng docstring), since each shape still gets
    an independent, never-reused random draw of its own. compare=False:
    two shapes with the same bounds/mode/amount/fill_color/fill_text/
    text_color are still the same shape as far as equality/undo-redo
    care, regardless of which random seed happens to back their noise.
    """

    bounds: Rect
    mode: ObfuscateMode = ObfuscateMode.PIXELIZE
    amount: int = 5
    fill_color: Color = (0, 0, 0, 255)
    fill_text: str = ""
    text_color: Color = (255, 255, 255, 255)
    seed: int = field(default_factory=lambda: secrets.randbits(128), compare=False)
