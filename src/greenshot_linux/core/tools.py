"""Pure logic behind interactive editing: which shape a drag-to-create
gesture produces for a given tool, and how a shape moves when dragged.
Kept separate from ui/editor_window.py so it's unit testable without
GTK - the window only needs to call these and push the result through
Layer/UndoRedoStack.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

from greenshot_linux.core.geometry import Rect
from greenshot_linux.core.shapes import (
    ArrowShape,
    CursorShape,
    EllipseShape,
    FreehandShape,
    IconShape,
    ImageShape,
    LineShape,
    ObfuscateMode,
    ObfuscateShape,
    RectangleShape,
    ShapeStyle,
    SpeechBubbleShape,
    StepLabelShape,
    SvgShape,
    TextShape,
)

Point = Tuple[int, int]

# Shapes with a plain, settable `bounds` field: move/resize is just
# swapping that field out. SpeechBubbleShape and FreehandShape are
# deliberately excluded - their `.bounds` (Drawable-protocol property)
# is *computed*, not a field (bubble+tail union, and tight point-cloud
# bbox respectively), so replace(shape, bounds=...) would fail; they
# get their own branches below.
_BOUNDS_RESIZABLE = (
    RectangleShape, EllipseShape, ObfuscateShape, TextShape,
    StepLabelShape, IconShape, CursorShape, ImageShape, SvgShape,
)


class Tool(str, Enum):
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    FREEHAND = "freehand"
    PIXELIZE = "pixelize"
    BLUR = "blur"
    TEXT = "text"


def create_shape_from_drag(tool: Tool, start: Point, end: Point, style: ShapeStyle, amount: int = 5):
    """For tools defined by a single start/end drag. Freehand is built
    incrementally from a point list instead - use create_freehand_shape.
    ``amount`` (blur radius / pixel size) only applies to Pixelize/Blur
    and defaults to ObfuscateShape's own default; every other tool
    ignores it, so callers can pass it unconditionally rather than
    branching on the current tool first.
    """
    if tool is Tool.RECTANGLE:
        return RectangleShape(Rect.from_points(*start, *end), style)
    if tool is Tool.ELLIPSE:
        return EllipseShape(Rect.from_points(*start, *end), style)
    if tool is Tool.LINE:
        return LineShape(start=start, end=end, style=style)
    if tool is Tool.ARROW:
        return ArrowShape(start=start, end=end, style=style)
    if tool is Tool.PIXELIZE:
        return ObfuscateShape(Rect.from_points(*start, *end), mode=ObfuscateMode.PIXELIZE, amount=amount)
    if tool is Tool.BLUR:
        return ObfuscateShape(Rect.from_points(*start, *end), mode=ObfuscateMode.BLUR, amount=amount)
    if tool is Tool.TEXT:
        return TextShape(Rect.from_points(*start, *end), text="", style=style)
    raise ValueError(f"{tool} is not created from a single start/end drag; use create_freehand_shape")


def create_freehand_shape(points: Sequence[Point], style: ShapeStyle) -> FreehandShape:
    return FreehandShape(points=tuple(points), style=style)


def translate_shape(shape, dx: int, dy: int):
    """A moved copy of ``shape``, offset by (dx, dy). Only supports the
    shape types ui/render.py can currently draw - the rest raise
    NotImplementedError rather than silently doing nothing, same
    convention as render_shape.
    """
    if isinstance(shape, LineShape):  # also covers ArrowShape
        return replace(
            shape,
            start=(shape.start[0] + dx, shape.start[1] + dy),
            end=(shape.end[0] + dx, shape.end[1] + dy),
        )
    if isinstance(shape, FreehandShape):
        return replace(shape, points=tuple((x + dx, y + dy) for x, y in shape.points))
    if isinstance(shape, SpeechBubbleShape):
        b = shape.bubble_bounds
        return replace(
            shape,
            bubble_bounds=Rect(b.left + dx, b.top + dy, b.right + dx, b.bottom + dy),
            target=(shape.target[0] + dx, shape.target[1] + dy),
        )
    if isinstance(shape, _BOUNDS_RESIZABLE):
        b = shape.bounds
        return replace(shape, bounds=Rect(b.left + dx, b.top + dy, b.right + dx, b.bottom + dy))
    raise NotImplementedError(f"no move support yet for {type(shape).__name__}")


def _handles_for_rect(rect: Rect) -> Dict[str, Point]:
    cx, cy = (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2
    return {
        "top_left": (rect.left, rect.top), "top": (cx, rect.top), "top_right": (rect.right, rect.top),
        "right": (rect.right, cy), "bottom_right": (rect.right, rect.bottom), "bottom": (cx, rect.bottom),
        "bottom_left": (rect.left, rect.bottom), "left": (rect.left, cy),
    }


# Shapes shown 8 corner/edge-midpoint handles computed from `.bounds`
# (a real field for _BOUNDS_RESIZABLE, a computed tight-bbox property
# for FreehandShape) - broader than _BOUNDS_RESIZABLE because Freehand
# gets handles for resizing (by scaling its points, not swapping a
# bounds field - see resize_shape) even though it has no bounds field.
_HANDLES_FROM_BOUNDS = _BOUNDS_RESIZABLE + (FreehandShape,)


def shape_handles(shape) -> Dict[str, Point]:
    """The named drag handles for ``shape``, as absolute (x, y) points:
    8 corner/edge-midpoint handles for most shapes (from `.bounds`, or
    `.bubble_bounds` for SpeechBubbleShape - its own `.bounds` unions
    in the tail's extent, a wider rect than what the handles should
    track), or the 2 endpoints for a Line/Arrow. Any other shape type
    has none (empty dict).
    """
    if isinstance(shape, LineShape):  # also covers ArrowShape
        return {"start": shape.start, "end": shape.end}
    if isinstance(shape, SpeechBubbleShape):
        return _handles_for_rect(shape.bubble_bounds)
    if isinstance(shape, _HANDLES_FROM_BOUNDS):
        return _handles_for_rect(shape.bounds)
    return {}


def handle_at(shape, x: int, y: int, margin: int = 6) -> Optional[str]:
    for name, (hx, hy) in shape_handles(shape).items():
        if abs(x - hx) <= margin and abs(y - hy) <= margin:
            return name
    return None


def _resized_rect(rect: Rect, handle: str, x: int, y: int) -> Rect:
    """``rect`` with ``handle`` moved to (x, y): the handle name's
    "top"/"bottom"/"left"/"right" substrings each move the matching
    edge independently, so a corner handle (e.g. "top_left") moves
    both at once and an edge-midpoint handle (e.g. "top") moves only
    one - Rect.from_points normalizes if a corner gets dragged past
    its opposite edge.
    """
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    if "top" in handle:
        top = y
    if "bottom" in handle:
        bottom = y
    if "left" in handle:
        left = x
    if "right" in handle:
        right = x
    return Rect.from_points(left, top, right, bottom)


def _scale_points(points, old_bounds: Rect, new_bounds: Rect):
    """Each point remapped from old_bounds' coordinate space into
    new_bounds' - the natural generalization of "resize" for a point-
    cloud shape with no bounds field of its own to just swap out.
    """
    scale_x = new_bounds.width / (old_bounds.width or 1)
    scale_y = new_bounds.height / (old_bounds.height or 1)
    return tuple(
        (
            round(new_bounds.left + (x - old_bounds.left) * scale_x),
            round(new_bounds.top + (y - old_bounds.top) * scale_y),
        )
        for x, y in points
    )


def resize_shape(shape, handle: str, x: int, y: int):
    """A reshaped copy of ``shape`` with ``handle`` moved to (x, y).

    For Line/Arrow, "start"/"end" move just that endpoint. For
    SpeechBubbleShape, resizing targets bubble_bounds (target, the
    tail's aim point, is left alone - the tail just gets shorter/
    longer/re-angled to keep pointing at the same spot). For Freehand,
    which has no bounds field, the point cloud is scaled proportionally
    from its old tight bounding box into the new one. Every other
    resizable shape just gets its bounds field swapped.
    """
    if isinstance(shape, LineShape):  # also covers ArrowShape
        if handle == "start":
            return replace(shape, start=(x, y))
        if handle == "end":
            return replace(shape, end=(x, y))
        raise ValueError(f"unknown handle {handle!r} for {type(shape).__name__}")
    if isinstance(shape, SpeechBubbleShape):
        return replace(shape, bubble_bounds=_resized_rect(shape.bubble_bounds, handle, x, y))
    if isinstance(shape, FreehandShape):
        old_bounds = shape.bounds
        new_bounds = _resized_rect(old_bounds, handle, x, y)
        return replace(shape, points=_scale_points(shape.points, old_bounds, new_bounds))
    if isinstance(shape, _BOUNDS_RESIZABLE):
        return replace(shape, bounds=_resized_rect(shape.bounds, handle, x, y))
    raise NotImplementedError(f"no resize support yet for {type(shape).__name__}")
