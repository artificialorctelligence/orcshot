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

from orcshot.core.geometry import Rect
from orcshot.core.shapes import (
    ArrowShape,
    CursorShape,
    EllipseShape,
    FreehandShape,
    HighlightMode,
    HighlightShape,
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
    RectangleShape, EllipseShape, ObfuscateShape, HighlightShape, TextShape,
    StepLabelShape, IconShape, CursorShape, ImageShape, SvgShape,
)


class Tool(str, Enum):
    SELECT = "select"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    FREEHAND = "freehand"
    # Real Windows toolbar order (ImageEditorForm.Designer.cs's
    # toolsToolStrip.Items): ...Freehand, Text, SpeechBubble, StepLabel,
    # Emoji, [separator], Highlight, Obfuscate... - the four Highlight
    # modes go here, mirroring Obfuscate's own four-Tool-values-one-
    # shared-button pattern below (see _TOOL_TO_HIGHLIGHT_MODE in
    # ui/editor_window.py).
    TEXT = "text"
    SPEECH_BUBBLE = "speech_bubble"
    STEP_LABEL = "step_label"
    EMOJI = "emoji"
    HIGHLIGHT_TEXT = "highlight_text"
    HIGHLIGHT_AREA = "highlight_area"
    HIGHLIGHT_GRAYSCALE = "highlight_grayscale"
    HIGHLIGHT_MAGNIFY = "highlight_magnify"
    PIXELIZE = "pixelize"
    BLUR = "blur"
    SOLID_FILL = "solid_fill"
    SCRAMBLE = "scramble"
    # Task #91: real toolbar order puts Crop right after Effects, before
    # RotateCW/RotateCCW/Resize (ImageEditorForm.Designer.cs's
    # toolsToolStrip.Items). Three Tool values sharing one toolbar
    # button, mirroring Highlight/Obfuscate's own pattern - but unlike
    # those, Crop never creates a Shape at all (CropContainer isn't a
    # drawn annotation, ui/editor_window.py tracks its in-progress
    # selection as separate state, not a Layer entry - see
    # core/crop.py's own module docstring). AutoCrop isn't its own Tool
    # value here either, matching Windows: it's a one-time seed action
    # that then behaves exactly like CROP_DEFAULT (InitCropMode,
    # ImageEditorForm.cs:1674-1696), not a persistent mode.
    CROP_DEFAULT = "crop_default"
    CROP_VERTICAL = "crop_vertical"
    CROP_HORIZONTAL = "crop_horizontal"


# Named style-panel fields, matching Windows' own FieldType names for
# the same controls (LINE_COLOR, FILL_COLOR, LINE_THICKNESS, SHADOW)
# plus this port's own OBFUSCATE_AMOUNT (Blur Radius/Pixel Size,
# Windows' separate BLUR_RADIUS/PIXEL_SIZE collapsed into one field -
# see core/shapes.py's ObfuscateShape docstring for why) and
# OBFUSCATE_MODE (the Blur-vs-Pixelize picker - Windows' own
# obfuscateModeButton, which lives in propertiesToolStrip alongside
# blurRadiusLabel/pixelSizeLabel and shares the same visibility rule -
# ImageEditorForm.cs:1402's `obfuscateModeButton.Visible =
# props.HasFieldValue(FieldType.PREPARED_FILTER_OBFUSCATE)` sits right
# next to the BLUR_RADIUS/PIXEL_SIZE visibility checks - hence
# grouping it into the _OBFUSCATE_STYLE_FIELDS_* sets below rather than giving it
# its own always-separate visibility rule).
STYLE_FIELD_LINE_COLOR = "line_color"
STYLE_FIELD_FILL_COLOR = "fill_color"
STYLE_FIELD_LINE_THICKNESS = "line_thickness"
STYLE_FIELD_SHADOW = "shadow"
STYLE_FIELD_OBFUSCATE_AMOUNT = "obfuscate_amount"
STYLE_FIELD_OBFUSCATE_MODE = "obfuscate_mode"
# Solid Fill's own color picker (task #60) - deliberately a separate
# field/control from STYLE_FIELD_FILL_COLOR above, not reused: that one
# reads/writes a selected shape's ShapeStyle.fill_color, but
# ObfuscateShape has no ShapeStyle at all (see its own docstring) - its
# color lives directly on ObfuscateShape.fill_color instead, wired
# through its own dedicated handlers in ui/editor_window.py
# (_on_obfuscate_fill_color_changed), matching how obfuscate_amount
# already gets its own handler rather than reusing the generic style
# machinery.
STYLE_FIELD_OBFUSCATE_FILL_COLOR = "obfuscate_fill_color"
# Solid Fill's own preset-text dropdown and its color (task #60
# follow-up) - same reasoning as STYLE_FIELD_OBFUSCATE_FILL_COLOR
# above: ObfuscateShape has no ShapeStyle, so these read/write
# ObfuscateShape.fill_text/text_color directly through their own
# dedicated handlers, not the generic style machinery.
STYLE_FIELD_OBFUSCATE_FILL_TEXT = "obfuscate_fill_text"
STYLE_FIELD_OBFUSCATE_TEXT_COLOR = "obfuscate_text_color"
# Highlight (task #88) mirrors Obfuscate's own pattern exactly - four
# Tool values (Tool.HIGHLIGHT_TEXT/AREA/GRAYSCALE/MAGNIFY) sharing one
# toolbar button, a Mode dropdown, and per-mode dedicated fields, since
# HighlightShape (like ObfuscateShape) has no ShapeStyle of its own -
# see HighlightShape's own docstring in core/shapes.py.
STYLE_FIELD_HIGHLIGHT_MODE = "highlight_mode"
STYLE_FIELD_HIGHLIGHT_FILL_COLOR = "highlight_fill_color"
STYLE_FIELD_HIGHLIGHT_BRIGHTNESS = "highlight_brightness"
STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS = "highlight_blur_radius"
STYLE_FIELD_HIGHLIGHT_MAGNIFICATION = "highlight_magnification"
# Crop (task #91) mirrors Windows' own cropModeButton visibility rule
# (ImageEditorForm.cs:1402, `cropModeButton.Visible =
# props.HasFieldValue(FieldType.CROPMODE)`) - just the one field, since
# Crop has no ShapeStyle-backed fields at all (no Shape exists until
# confirm - see core/crop.py's own module docstring). Confirm/Cancel
# button visibility is handled separately in ui/editor_window.py,
# driven by whether a crop selection is in progress rather than by
# which tool is active - Windows shows those for *any* CONFIRMABLE
# selection, not specifically Crop's own field.
STYLE_FIELD_CROP_MODE = "crop_mode"

_FULL_STYLE_FIELDS = frozenset({
    STYLE_FIELD_LINE_COLOR, STYLE_FIELD_FILL_COLOR, STYLE_FIELD_LINE_THICKNESS, STYLE_FIELD_SHADOW,
})
_LINE_ONLY_STYLE_FIELDS = frozenset({STYLE_FIELD_LINE_COLOR, STYLE_FIELD_LINE_THICKNESS, STYLE_FIELD_SHADOW})
_FREEHAND_STYLE_FIELDS = frozenset({STYLE_FIELD_LINE_COLOR, STYLE_FIELD_LINE_THICKNESS})
# Three different obfuscate field sets, one per group of modes with the
# same relevant controls (task #60 added Solid Fill/Scramble alongside
# the original Blur/Pixelize, each needing different fields - Solid
# Fill's own color/text/text-color trio, nothing at all for Scramble,
# and the original amount spinner for Blur/Pixelize). All three still
# always include OBFUSCATE_MODE, since the mode dropdown itself is
# relevant regardless of which mode is currently selected.
_OBFUSCATE_STYLE_FIELDS_AMOUNT = frozenset({STYLE_FIELD_OBFUSCATE_AMOUNT, STYLE_FIELD_OBFUSCATE_MODE})
_OBFUSCATE_STYLE_FIELDS_COLOR = frozenset({
    STYLE_FIELD_OBFUSCATE_FILL_COLOR, STYLE_FIELD_OBFUSCATE_FILL_TEXT, STYLE_FIELD_OBFUSCATE_TEXT_COLOR,
    STYLE_FIELD_OBFUSCATE_MODE,
})
_OBFUSCATE_STYLE_FIELDS_MODE_ONLY = frozenset({STYLE_FIELD_OBFUSCATE_MODE})
_NO_STYLE_FIELDS = frozenset()

# Same idea as the three _OBFUSCATE_STYLE_FIELDS_* sets above, one per
# group of Highlight modes with the same relevant controls - real
# Windows exposes all of these as actual style-panel controls
# (blurRadiusUpDown/brightnessUpDown/magnificationFactorUpDown/
# highlightModeButton, ImageEditorForm.Designer.cs), not just internal
# filter parameters. All four still always include HIGHLIGHT_MODE.
_HIGHLIGHT_STYLE_FIELDS_COLOR = frozenset({STYLE_FIELD_HIGHLIGHT_FILL_COLOR, STYLE_FIELD_HIGHLIGHT_MODE})
_HIGHLIGHT_STYLE_FIELDS_AREA = frozenset({
    STYLE_FIELD_HIGHLIGHT_BRIGHTNESS, STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS, STYLE_FIELD_HIGHLIGHT_MODE,
})
_HIGHLIGHT_STYLE_FIELDS_MODE_ONLY = frozenset({STYLE_FIELD_HIGHLIGHT_MODE})
_HIGHLIGHT_STYLE_FIELDS_MAGNIFY = frozenset({STYLE_FIELD_HIGHLIGHT_MAGNIFICATION, STYLE_FIELD_HIGHLIGHT_MODE})
_CROP_STYLE_FIELDS = frozenset({STYLE_FIELD_CROP_MODE})

# Which style-panel fields each tool's shape actually has, cross-
# checked against the real Windows source's own per-container AddField
# calls (RectangleContainer.cs/EllipseContainer.cs/LineContainer.cs/
# ArrowContainer.cs/FreehandContainer.cs/TextContainer.cs/
# StepLabelContainer.cs/ImageContainer.cs) and, since this port has
# already made some deliberate rendering simplifications versus those,
# against what ui/render.py's own renderers actually use per shape -
# e.g. Line/Arrow have no FILL_COLOR in the real source and this port's
# render_arrow fills the arrowhead with line_color rather than a
# separate fill_color the way it might look like it should; Freehand
# has neither fill nor shadow in either the source or this port
# (render_freehand, FreehandContainer.cs). An explicit table rather
# than deriving it from shape construction, so it stays one easy-to-
# audit place to revisit against a future Windows source update.
_TOOL_STYLE_FIELDS = {
    Tool.SELECT: _NO_STYLE_FIELDS,  # no fields of its own - see visible_style_fields
    Tool.RECTANGLE: _FULL_STYLE_FIELDS,
    Tool.ELLIPSE: _FULL_STYLE_FIELDS,
    Tool.LINE: _LINE_ONLY_STYLE_FIELDS,
    Tool.ARROW: _LINE_ONLY_STYLE_FIELDS,
    Tool.FREEHAND: _FREEHAND_STYLE_FIELDS,
    Tool.PIXELIZE: _OBFUSCATE_STYLE_FIELDS_AMOUNT,
    Tool.BLUR: _OBFUSCATE_STYLE_FIELDS_AMOUNT,
    Tool.SOLID_FILL: _OBFUSCATE_STYLE_FIELDS_COLOR,
    Tool.SCRAMBLE: _OBFUSCATE_STYLE_FIELDS_MODE_ONLY,
    Tool.HIGHLIGHT_TEXT: _HIGHLIGHT_STYLE_FIELDS_COLOR,
    Tool.HIGHLIGHT_AREA: _HIGHLIGHT_STYLE_FIELDS_AREA,
    Tool.HIGHLIGHT_GRAYSCALE: _HIGHLIGHT_STYLE_FIELDS_MODE_ONLY,
    Tool.HIGHLIGHT_MAGNIFY: _HIGHLIGHT_STYLE_FIELDS_MAGNIFY,
    Tool.CROP_DEFAULT: _CROP_STYLE_FIELDS,
    Tool.CROP_VERTICAL: _CROP_STYLE_FIELDS,
    Tool.CROP_HORIZONTAL: _CROP_STYLE_FIELDS,
    Tool.TEXT: _FULL_STYLE_FIELDS,
    Tool.SPEECH_BUBBLE: _FULL_STYLE_FIELDS,
    Tool.STEP_LABEL: _FULL_STYLE_FIELDS,
    Tool.EMOJI: _FULL_STYLE_FIELDS,  # reuses TextShape - see create_shape_from_drag
}

# Which obfuscate-specific field set a given ObfuscateShape's own mode
# needs - the _shape_style_fields counterpart to _TOOL_STYLE_FIELDS
# above, since a *selected* ObfuscateShape's fields depend on its own
# mode, not whichever tool happens to be active (see visible_style_
# fields' own docstring on selection taking priority over the tool).
_OBFUSCATE_MODE_STYLE_FIELDS = {
    ObfuscateMode.BLUR: _OBFUSCATE_STYLE_FIELDS_AMOUNT,
    ObfuscateMode.PIXELIZE: _OBFUSCATE_STYLE_FIELDS_AMOUNT,
    ObfuscateMode.SOLID_FILL: _OBFUSCATE_STYLE_FIELDS_COLOR,
    ObfuscateMode.SCRAMBLE: _OBFUSCATE_STYLE_FIELDS_MODE_ONLY,
}

# The _shape_style_fields counterpart to _TOOL_STYLE_FIELDS's four
# Highlight entries above, same reasoning as _OBFUSCATE_MODE_STYLE_
# FIELDS - a *selected* HighlightShape's fields depend on its own
# mode, not whichever tool happens to be active.
_HIGHLIGHT_MODE_STYLE_FIELDS = {
    HighlightMode.TEXT_HIGHLIGHT: _HIGHLIGHT_STYLE_FIELDS_COLOR,
    HighlightMode.AREA_HIGHLIGHT: _HIGHLIGHT_STYLE_FIELDS_AREA,
    HighlightMode.GRAYSCALE: _HIGHLIGHT_STYLE_FIELDS_MODE_ONLY,
    HighlightMode.MAGNIFICATION: _HIGHLIGHT_STYLE_FIELDS_MAGNIFY,
}


def _shape_style_fields(shape) -> frozenset:
    if isinstance(shape, ObfuscateShape):
        return _OBFUSCATE_MODE_STYLE_FIELDS[shape.mode]
    if isinstance(shape, HighlightShape):
        return _HIGHLIGHT_MODE_STYLE_FIELDS[shape.mode]
    if isinstance(shape, FreehandShape):
        return _FREEHAND_STYLE_FIELDS
    if isinstance(shape, LineShape):  # also covers ArrowShape, a subclass
        return _LINE_ONLY_STYLE_FIELDS
    if isinstance(shape, (RectangleShape, EllipseShape, TextShape, SpeechBubbleShape, StepLabelShape)):
        return _FULL_STYLE_FIELDS
    return _NO_STYLE_FIELDS  # IconShape/CursorShape/ImageShape/SvgShape have no style fields


# Per-tool "last used" style defaults - the preferredDefaultValue each
# container's own InitializeFields passes to EditorConfigurationHelper.
# CreateField, which caches last-used values keyed by *requesting
# type name*, not one shared value (EditorConfigurationHelper.cs:48-76:
# `requestedField = requestingTypeName + "." + fieldType.Name`) - so in
# the real editor, changing Rectangle's line color never affects Speech
# Bubble's. Cross-checked against each container's own field defaults:
# RectangleContainer.cs:61-67, EllipseContainer.cs:57-63, LineContainer.
# cs:45-50, ArrowContainer.cs:56-64, TextContainer.cs:98-110 (all four
# identical to ShapeStyle()'s own plain default - line thickness 2, Red,
# Transparent, shadow on), FreehandContainer.cs:65-69 (thickness 3
# instead of 2, otherwise the same), SpeechbubbleContainer.cs:79-89
# (White fill, no shadow - but Black line, not the source's own Blue,
# a direct user request; matches SpeechBubbleShape's own dataclass
# default, shapes.py), StepLabelContainer.cs:161-167 (DarkRed fill,
# White line, thickness 0, no shadow - matches StepLabelShape's own
# dataclass default too). Only tools whose shape has a style field are
# listed - see _TOOL_STYLE_FIELDS above for which don't.
_DEFAULT_STYLE = ShapeStyle()
_TOOL_STYLE_DEFAULTS: Dict[Tool, ShapeStyle] = {
    Tool.RECTANGLE: _DEFAULT_STYLE,
    Tool.ELLIPSE: _DEFAULT_STYLE,
    Tool.LINE: _DEFAULT_STYLE,
    Tool.ARROW: _DEFAULT_STYLE,
    Tool.FREEHAND: replace(_DEFAULT_STYLE, line_thickness=3),
    Tool.TEXT: _DEFAULT_STYLE,
    # No Windows Emoji container to cite (this port's own addition -
    # see create_shape_from_drag) - reuses TextContainer's own default,
    # same as it reuses TextShape's class.
    Tool.EMOJI: _DEFAULT_STYLE,
    Tool.SPEECH_BUBBLE: ShapeStyle(line_color=(0, 0, 0, 255), fill_color=(255, 255, 255, 255), shadow=False),
    Tool.STEP_LABEL: ShapeStyle(fill_color=(139, 0, 0, 255), line_color=(255, 255, 255, 255), line_thickness=0, shadow=False),
}


def default_style_for_tool(tool: Tool) -> ShapeStyle:
    return _TOOL_STYLE_DEFAULTS.get(tool, _DEFAULT_STYLE)


def style_key_for_shape(shape) -> Optional[Tool]:
    """Which tool's per-type style memory a shape's own class belongs
    to - the inverse of create_shape_from_drag. Used so restyling an
    existing *selected* shape (not just drawing a new one) updates the
    same per-type memory a freshly drawn shape of that type would read
    next, matching EditorConfigurationHelper.UpdateLastFieldValue
    (keyed by the changed field's own Scope/owning container type, not
    by whichever tool happens to be active - typically Select - when
    the edit happens).
    """
    if isinstance(shape, ArrowShape):  # checked first - ArrowShape subclasses LineShape
        return Tool.ARROW
    if isinstance(shape, LineShape):
        return Tool.LINE
    if isinstance(shape, RectangleShape):
        return Tool.RECTANGLE
    if isinstance(shape, EllipseShape):
        return Tool.ELLIPSE
    if isinstance(shape, FreehandShape):
        return Tool.FREEHAND
    if isinstance(shape, SpeechBubbleShape):
        return Tool.SPEECH_BUBBLE
    if isinstance(shape, TextShape):
        return Tool.TEXT  # also covers Emoji-created shapes - see _TOOL_STYLE_DEFAULTS
    if isinstance(shape, StepLabelShape):
        return Tool.STEP_LABEL
    return None


def visible_style_fields(tool: Tool, selected_shape=None) -> frozenset:
    """Which style-panel controls (line/fill color, thickness, shadow,
    obfuscate amount) are relevant right now.

    Faithful port of the real editor's RefreshFieldControls
    (ImageEditorForm.cs:1375), which drives each control's .Visible
    from FieldAggregator.HasFieldValue against whichever's actually
    selected or active - not, as this port previously did, always
    showing every control regardless of relevance.

    A selected shape's own fields take priority over the active tool's
    (so selecting an existing Line while Rectangle is the active tool
    still shows Line's fields, matching Windows' FieldAggregator
    aggregating the *selection's* fields when there is one). Tool.SELECT
    with nothing selected shows nothing at all, also matching Windows
    (RefreshFieldControls' `HasSelectedElements || DrawingMode !=
    None` check, else HideToolstripItems()).
    """
    if selected_shape is not None:
        return _shape_style_fields(selected_shape)
    return _TOOL_STYLE_FIELDS.get(tool, _NO_STYLE_FIELDS)


# The default emoji Emoji-tool shapes start with (a slightly smiling
# face) - retype to pick a different one, same as backspacing and
# typing new text on any other TextShape.
_DEFAULT_EMOJI = "\U0001F642"

# How far outside the drag's own start corner the tail sits, in
# pixels - faithful port of SpeechbubbleContainer.HandleMouseMove's
# own offset (a fix for the real Windows source's own BUG-1682: the
# tail used to be computed from the *final* bounding box's corner,
# which - after Rect.from_points below normalizes start/end into a
# rect - can land on any of the four actual dragged corners depending
# on drag direction, making the tail visibly jump around depending on
# which way you dragged from the same start point. The real fix
# anchors the tail to the drag's own fixed start point instead (never
# moves once you've pressed down) and only flips which side of it the
# tail sits on, so it always points away from wherever the bubble is
# growing rather than tracking the bubble's own final shape.
_SPEECH_BUBBLE_TAIL_OFFSET = 20

# StepLabelShape is click-to-place in the source, not drag-to-size -
# always this fixed radius regardless of where a drag ends.
_STEP_LABEL_RADIUS = 15


def create_shape_from_drag(
    tool: Tool, start: Point, end: Point, style: ShapeStyle, amount: int = 5, next_step_number: int = 1,
    fill_color=(0, 0, 0, 255), fill_text: str = "", text_color=(255, 255, 255, 255),
    highlight_color=(255, 255, 0, 255), highlight_brightness: float = 0.9,
    highlight_blur_radius: int = 3, highlight_magnification: int = 2,
):
    """For tools defined by a single start/end drag. Freehand is built
    incrementally from a point list instead - use create_freehand_shape.
    ``amount`` (blur radius / pixel size) only applies to Pixelize/Blur;
    ``fill_color``/``fill_text``/``text_color`` only apply to Solid Fill
    (task #60); ``highlight_color``/``highlight_brightness``/
    ``highlight_blur_radius``/``highlight_magnification`` only apply to
    the four Highlight modes (task #88) - deliberately separate
    parameters from Obfuscate's own fill_color rather than reused, so
    each tool keeps its own independent last-used value, matching every
    other tool's own per-type style memory; all default to
    HighlightShape's own defaults; ``next_step_number`` only applies to
    StepLabel; every other tool ignores whichever of these doesn't
    apply to it, so callers can pass all of them unconditionally rather
    than branching on the current tool first.
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
    if tool is Tool.SOLID_FILL:
        return ObfuscateShape(
            Rect.from_points(*start, *end), mode=ObfuscateMode.SOLID_FILL,
            fill_color=fill_color, fill_text=fill_text, text_color=text_color,
        )
    if tool is Tool.SCRAMBLE:
        return ObfuscateShape(Rect.from_points(*start, *end), mode=ObfuscateMode.SCRAMBLE)
    if tool is Tool.HIGHLIGHT_TEXT:
        return HighlightShape(
            Rect.from_points(*start, *end), mode=HighlightMode.TEXT_HIGHLIGHT, fill_color=highlight_color,
        )
    if tool is Tool.HIGHLIGHT_AREA:
        return HighlightShape(
            Rect.from_points(*start, *end), mode=HighlightMode.AREA_HIGHLIGHT,
            brightness=highlight_brightness, blur_radius=highlight_blur_radius,
        )
    if tool is Tool.HIGHLIGHT_GRAYSCALE:
        return HighlightShape(Rect.from_points(*start, *end), mode=HighlightMode.GRAYSCALE)
    if tool is Tool.HIGHLIGHT_MAGNIFY:
        return HighlightShape(
            Rect.from_points(*start, *end), mode=HighlightMode.MAGNIFICATION,
            magnification_factor=highlight_magnification,
        )
    if tool is Tool.TEXT:
        return TextShape(Rect.from_points(*start, *end), text="", style=style)
    if tool is Tool.EMOJI:
        # No dedicated shape type - Pango already renders emoji glyphs
        # fine as text, so this reuses TextShape (and, in
        # ui/editor_window.py, the exact same edit-in-place machinery
        # Text/SpeechBubble already have) rather than a whole separate
        # picker UI. Retyping the glyph picks a different emoji.
        return TextShape(Rect.from_points(*start, *end), text=_DEFAULT_EMOJI, style=style)
    if tool is Tool.SPEECH_BUBBLE:
        bubble_bounds = Rect.from_points(*start, *end)
        # leftAligned/topAligned in the real source: whether the drag
        # is still growing in its original direction (end past start)
        # or has crossed back over the start point - determines which
        # side of the fixed start point the tail sits on, so it always
        # points away from the bubble rather than into it.
        x_offset = -_SPEECH_BUBBLE_TAIL_OFFSET if end[0] >= start[0] else _SPEECH_BUBBLE_TAIL_OFFSET
        y_offset = -_SPEECH_BUBBLE_TAIL_OFFSET if end[1] >= start[1] else _SPEECH_BUBBLE_TAIL_OFFSET
        target = (start[0] + x_offset, start[1] + y_offset)
        return SpeechBubbleShape(bubble_bounds=bubble_bounds, target=target, text="", style=style)
    if tool is Tool.STEP_LABEL:
        cx, cy = start
        r = _STEP_LABEL_RADIUS
        bounds = Rect(cx - r, cy - r, cx + r, cy + r)
        return StepLabelShape(bounds=bounds, number=next_step_number, style=style)
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


def scale_shape(shape, scale_x: float, scale_y: float):
    """A copy of ``shape`` with every coordinate scaled around the
    canvas origin (0, 0) - not around the shape's own center. Used by
    whole-image Resize (core/effects.py) to keep annotations aligned
    with a resampled canvas, the same role Windows' Matrix-based
    element transform plays in Surface.ApplyBitmapEffect
    (Surface.cs:1106). Same per-type dispatch as translate_shape.
    """
    def sx(x):
        return round(x * scale_x)

    def sy(y):
        return round(y * scale_y)

    if isinstance(shape, LineShape):  # also covers ArrowShape
        return replace(
            shape,
            start=(sx(shape.start[0]), sy(shape.start[1])),
            end=(sx(shape.end[0]), sy(shape.end[1])),
        )
    if isinstance(shape, FreehandShape):
        return replace(shape, points=tuple((sx(x), sy(y)) for x, y in shape.points))
    if isinstance(shape, SpeechBubbleShape):
        b = shape.bubble_bounds
        return replace(
            shape,
            bubble_bounds=Rect(sx(b.left), sy(b.top), sx(b.right), sy(b.bottom)),
            target=(sx(shape.target[0]), sy(shape.target[1])),
        )
    if isinstance(shape, _BOUNDS_RESIZABLE):
        b = shape.bounds
        return replace(shape, bounds=Rect(sx(b.left), sy(b.top), sx(b.right), sy(b.bottom)))
    raise NotImplementedError(f"no scale support yet for {type(shape).__name__}")


def rotate_shape_90(shape, old_width: int, old_height: int, clockwise: bool):
    """A copy of ``shape`` rotated the same 90 degrees as a whole-image
    Rotate effect (core/effects.py), so annotations stay aligned with
    the rotated canvas - Windows does the same via a Matrix rotate+
    translate (WindowCapture... actually RotateEffect,
    Greenshot.Base/Effects/RotateEffect.cs:32-68). ``old_width``/
    ``old_height`` are the canvas size *before* rotation (the new
    canvas is old_height x old_width). Same per-type dispatch as
    translate_shape/scale_shape.
    """
    def rotate_point(x, y):
        if clockwise:
            return old_height - y, x
        return y, old_width - x

    if isinstance(shape, LineShape):  # also covers ArrowShape
        return replace(shape, start=rotate_point(*shape.start), end=rotate_point(*shape.end))
    if isinstance(shape, FreehandShape):
        return replace(shape, points=tuple(rotate_point(x, y) for x, y in shape.points))
    if isinstance(shape, SpeechBubbleShape):
        b = shape.bubble_bounds
        x1, y1 = rotate_point(b.left, b.top)
        x2, y2 = rotate_point(b.right, b.bottom)
        return replace(
            shape,
            bubble_bounds=Rect.from_points(x1, y1, x2, y2),
            target=rotate_point(*shape.target),
        )
    if isinstance(shape, _BOUNDS_RESIZABLE):
        b = shape.bounds
        x1, y1 = rotate_point(b.left, b.top)
        x2, y2 = rotate_point(b.right, b.bottom)
        return replace(shape, bounds=Rect.from_points(x1, y1, x2, y2))
    raise NotImplementedError(f"no rotate support yet for {type(shape).__name__}")


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


_INSERT_MAX_FRACTION = 0.8


def default_insert_bounds(content_w: int, content_h: int, canvas_w: int, canvas_h: int) -> Rect:
    """Where an inserted Image/SVG shape (ui/editor_window.py's Insert
    Image/Insert SVG, from the File menu) starts out: centered in the
    canvas, at its natural size unless that's bigger than
    _INSERT_MAX_FRACTION of the canvas in either dimension, in which
    case it's scaled down (preserving aspect ratio) to fit - never
    scaled *up*, so a small image doesn't get blown up past its real
    size just because the canvas is large. Unlike every other shape
    here, there's no drag gesture to size these from (Insert Image/SVG
    is a file picker, not a click-and-drag tool), so this is the
    one-shot placement logic that stands in for one.
    """
    scale = min(
        1.0,
        (canvas_w * _INSERT_MAX_FRACTION) / content_w if content_w else 1.0,
        (canvas_h * _INSERT_MAX_FRACTION) / content_h if content_h else 1.0,
    )
    w, h = round(content_w * scale), round(content_h * scale)
    left = round((canvas_w - w) / 2)
    top = round((canvas_h - h) / 2)
    return Rect(left, top, left + w, top + h)
