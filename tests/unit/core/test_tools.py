"""Pure, UI-independent logic behind interactive editing: which shape a
drag-to-create gesture produces, and how a shape moves when dragged.
Kept out of ui/editor_window.py so it's unit testable without GTK.
"""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

import numpy as np

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
from orcshot.core.tools import (
    STYLE_FIELD_CROP_MODE,
    STYLE_FIELD_FILL_COLOR,
    STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS,
    STYLE_FIELD_HIGHLIGHT_BRIGHTNESS,
    STYLE_FIELD_HIGHLIGHT_FILL_COLOR,
    STYLE_FIELD_HIGHLIGHT_MAGNIFICATION,
    STYLE_FIELD_HIGHLIGHT_MODE,
    STYLE_FIELD_LINE_COLOR,
    STYLE_FIELD_LINE_THICKNESS,
    STYLE_FIELD_OBFUSCATE_AMOUNT,
    STYLE_FIELD_OBFUSCATE_FILL_COLOR,
    STYLE_FIELD_OBFUSCATE_FILL_TEXT,
    STYLE_FIELD_OBFUSCATE_MODE,
    STYLE_FIELD_OBFUSCATE_TEXT_COLOR,
    STYLE_FIELD_SHADOW,
    Tool,
    create_freehand_shape,
    create_shape_from_drag,
    default_insert_bounds,
    default_style_for_tool,
    handle_at,
    resize_shape,
    rotate_shape_90,
    scale_shape,
    shape_handles,
    style_key_for_shape,
    translate_shape,
    visible_style_fields,
)

STYLE = ShapeStyle(line_thickness=3, line_color=(1, 2, 3, 255))


class NotARealShape:
    """A shape type core/tools.py has never heard of - used to test the
    NotImplementedError fallback without needing a real still-
    unsupported shape (there isn't one left after this module's tests)."""

    bounds = Rect(0, 0, 10, 10)


def rgba_image(w=4, h=4):
    return np.full((h, w, 4), (10, 20, 30, 255), dtype=np.uint8)


class TestCreateShapeFromDrag:
    def test_rectangle(self):
        shape = create_shape_from_drag(Tool.RECTANGLE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, RectangleShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.style is STYLE

    def test_ellipse(self):
        shape = create_shape_from_drag(Tool.ELLIPSE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, EllipseShape)
        assert shape.bounds == Rect(10, 10, 60, 40)

    def test_line_preserves_true_endpoints_not_just_bounds(self):
        shape = create_shape_from_drag(Tool.LINE, (60, 10), (10, 40), STYLE)
        assert isinstance(shape, LineShape)
        assert not isinstance(shape, ArrowShape)
        assert shape.start == (60, 10)
        assert shape.end == (10, 40)

    def test_arrow_preserves_true_endpoints(self):
        shape = create_shape_from_drag(Tool.ARROW, (60, 10), (10, 40), STYLE)
        assert isinstance(shape, ArrowShape)
        assert shape.start == (60, 10)
        assert shape.end == (10, 40)

    def test_freehand_is_rejected_since_it_needs_a_point_list_not_two_points(self):
        with pytest.raises(ValueError):
            create_shape_from_drag(Tool.FREEHAND, (0, 0), (10, 10), STYLE)

    def test_pixelize(self):
        shape = create_shape_from_drag(Tool.PIXELIZE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, ObfuscateShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is ObfuscateMode.PIXELIZE
        assert shape.amount == 5  # ObfuscateShape's own default, unspecified here

    def test_blur(self):
        shape = create_shape_from_drag(Tool.BLUR, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, ObfuscateShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is ObfuscateMode.BLUR
        assert shape.amount == 5

    def test_pixelize_with_an_explicit_amount(self):
        shape = create_shape_from_drag(Tool.PIXELIZE, (10, 40), (60, 10), STYLE, amount=12)
        assert shape.amount == 12

    def test_blur_with_an_explicit_amount(self):
        shape = create_shape_from_drag(Tool.BLUR, (10, 40), (60, 10), STYLE, amount=9)
        assert shape.amount == 9

    def test_solid_fill(self):
        shape = create_shape_from_drag(Tool.SOLID_FILL, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, ObfuscateShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is ObfuscateMode.SOLID_FILL
        assert shape.fill_color == (0, 0, 0, 255)  # ObfuscateShape's own default

    def test_solid_fill_with_an_explicit_fill_color(self):
        shape = create_shape_from_drag(
            Tool.SOLID_FILL, (10, 40), (60, 10), STYLE, fill_color=(200, 100, 50, 255),
        )
        assert shape.fill_color == (200, 100, 50, 255)

    def test_solid_fill_defaults_to_no_text(self):
        shape = create_shape_from_drag(Tool.SOLID_FILL, (10, 40), (60, 10), STYLE)
        assert shape.fill_text == ""
        assert shape.text_color == (255, 255, 255, 255)  # ObfuscateShape's own default

    def test_solid_fill_with_explicit_text_and_text_color(self):
        shape = create_shape_from_drag(
            Tool.SOLID_FILL, (10, 40), (60, 10), STYLE,
            fill_text="REDACTED", text_color=(255, 0, 0, 255),
        )
        assert shape.fill_text == "REDACTED"
        assert shape.text_color == (255, 0, 0, 255)

    def test_scramble(self):
        shape = create_shape_from_drag(Tool.SCRAMBLE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, ObfuscateShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is ObfuscateMode.SCRAMBLE

    def test_highlight_text(self):
        shape = create_shape_from_drag(Tool.HIGHLIGHT_TEXT, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, HighlightShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is HighlightMode.TEXT_HIGHLIGHT
        assert shape.fill_color == (255, 255, 0, 255)  # HighlightShape's own default

    def test_highlight_text_with_an_explicit_fill_color(self):
        shape = create_shape_from_drag(
            Tool.HIGHLIGHT_TEXT, (10, 40), (60, 10), STYLE, highlight_color=(0, 255, 0, 255),
        )
        assert shape.fill_color == (0, 255, 0, 255)

    def test_highlight_area(self):
        shape = create_shape_from_drag(Tool.HIGHLIGHT_AREA, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, HighlightShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is HighlightMode.AREA_HIGHLIGHT
        assert shape.brightness == 0.9  # HighlightShape's own default
        assert shape.blur_radius == 3

    def test_highlight_area_with_explicit_brightness_and_blur_radius(self):
        shape = create_shape_from_drag(
            Tool.HIGHLIGHT_AREA, (10, 40), (60, 10), STYLE,
            highlight_brightness=0.5, highlight_blur_radius=8,
        )
        assert shape.brightness == 0.5
        assert shape.blur_radius == 8

    def test_highlight_grayscale(self):
        shape = create_shape_from_drag(Tool.HIGHLIGHT_GRAYSCALE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, HighlightShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is HighlightMode.GRAYSCALE

    def test_highlight_magnify(self):
        shape = create_shape_from_drag(Tool.HIGHLIGHT_MAGNIFY, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, HighlightShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.mode is HighlightMode.MAGNIFICATION
        assert shape.magnification_factor == 2  # HighlightShape's own default

    def test_highlight_magnify_with_an_explicit_factor(self):
        shape = create_shape_from_drag(
            Tool.HIGHLIGHT_MAGNIFY, (10, 40), (60, 10), STYLE, highlight_magnification=4,
        )
        assert shape.magnification_factor == 4

    def test_fill_color_is_ignored_for_tools_that_do_not_use_it(self):
        shape = create_shape_from_drag(
            Tool.RECTANGLE, (10, 40), (60, 10), STYLE, fill_color=(9, 9, 9, 9),
        )
        assert isinstance(shape, RectangleShape)

    def test_amount_is_ignored_for_tools_that_do_not_use_it(self):
        # every other tool must accept (and ignore) the amount kwarg
        # without erroring, so callers don't need to branch by tool
        # just to decide whether to pass it.
        shape = create_shape_from_drag(Tool.RECTANGLE, (10, 40), (60, 10), STYLE, amount=99)
        assert isinstance(shape, RectangleShape)

    def test_text_starts_empty(self):
        shape = create_shape_from_drag(Tool.TEXT, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, TextShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.text == ""
        assert shape.style is STYLE

    def test_emoji_is_a_text_shape_prefilled_with_a_default_emoji(self):
        # No dedicated shape type - Pango already renders emoji glyphs
        # fine as text, and this reuses the exact same edit-in-place
        # machinery Text/SpeechBubble already have (retype to pick a
        # different emoji), rather than a whole separate picker UI.
        shape = create_shape_from_drag(Tool.EMOJI, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, TextShape)
        assert shape.bounds == Rect(10, 10, 60, 40)
        assert shape.text == "\U0001F642"  # slightly smiling face
        assert shape.style is STYLE

    def test_select_tool_is_rejected_since_it_never_creates_a_shape(self):
        # The Selection tool (Windows' "Cursor" button) only
        # selects/moves/resizes existing shapes - ui/editor_window.py
        # never calls create_shape_from_drag for it, but this guards
        # against a caller trying to anyway.
        with pytest.raises(ValueError):
            create_shape_from_drag(Tool.SELECT, (10, 40), (60, 10), STYLE)

    def test_speech_bubble_starts_empty(self):
        shape = create_shape_from_drag(Tool.SPEECH_BUBBLE, (10, 40), (60, 10), STYLE)
        assert isinstance(shape, SpeechBubbleShape)
        assert shape.bubble_bounds == Rect(10, 10, 60, 40)
        assert shape.text == ""
        assert shape.style is STYLE

    def test_speech_bubble_tail_is_anchored_to_the_drag_start_point_not_a_bounds_corner(self):
        # Faithful port of SpeechbubbleContainer's own BUG-1682 fix: the
        # tail sits a fixed 20px outside the drag's own start point,
        # never on a corner of the final (post-normalization) bounds -
        # which is what the pre-fix version did, and which flips
        # depending on drag direction since Rect.from_points always
        # normalizes start/end regardless of which way you dragged.
        start = (100, 100)
        for end in [(150, 150), (50, 150), (150, 50), (50, 50)]:
            shape = create_shape_from_drag(Tool.SPEECH_BUBBLE, start, end, STYLE)
            assert abs(shape.target[0] - start[0]) == 20
            assert abs(shape.target[1] - start[1]) == 20

    def test_speech_bubble_tail_points_away_from_the_direction_the_bubble_grows(self):
        # Dragging down-and-right (bubble grows toward positive x/y from
        # the start point) - the tail should sit up-and-left of start,
        # outside the bubble's own growth direction, not inside it.
        shape = create_shape_from_drag(Tool.SPEECH_BUBBLE, (100, 100), (200, 200), STYLE)
        assert shape.target == (80, 80)

        # Dragging up-and-left (bubble grows toward negative x/y) - the
        # tail flips to sit down-and-right of the same start point.
        shape = create_shape_from_drag(Tool.SPEECH_BUBBLE, (100, 100), (0, 0), STYLE)
        assert shape.target == (120, 120)

    def test_speech_bubble_tail_stays_put_if_the_drag_reverses_past_the_start_point(self):
        # A drag that starts moving one way then crosses back over the
        # start point in the opposite direction shouldn't leave the
        # tail stranded somewhere in the middle - it's still just
        # "outside the start point, opposite the current drag
        # direction" at every step, recomputed fresh each call (this
        # function has no memory of earlier calls in the same drag).
        start = (100, 100)
        first = create_shape_from_drag(Tool.SPEECH_BUBBLE, start, (150, 150), STYLE)
        reversed_ = create_shape_from_drag(Tool.SPEECH_BUBBLE, start, (50, 50), STYLE)
        assert first.target == (80, 80)
        assert reversed_.target == (120, 120)

    def test_step_label_is_a_fixed_size_circle_at_the_start_point_ignoring_drag_end(self):
        shape = create_shape_from_drag(Tool.STEP_LABEL, (100, 100), (999, 999), STYLE, next_step_number=3)
        assert isinstance(shape, StepLabelShape)
        assert shape.number == 3
        cx = (shape.bounds.left + shape.bounds.right) / 2
        cy = (shape.bounds.top + shape.bounds.bottom) / 2
        assert (cx, cy) == (100, 100)
        assert shape.bounds.width == shape.bounds.height  # a circle, not an ellipse

    def test_step_label_defaults_to_number_1(self):
        shape = create_shape_from_drag(Tool.STEP_LABEL, (0, 0), (0, 0), STYLE)
        assert shape.number == 1


def test_create_freehand_shape():
    points = ((0, 0), (5, 5), (10, 0))
    shape = create_freehand_shape(points, STYLE)
    assert isinstance(shape, FreehandShape)
    assert shape.points == points
    assert shape.style is STYLE


_FULL_FIELDS = frozenset({
    STYLE_FIELD_LINE_COLOR, STYLE_FIELD_FILL_COLOR, STYLE_FIELD_LINE_THICKNESS, STYLE_FIELD_SHADOW,
})
_LINE_ONLY_FIELDS = frozenset({STYLE_FIELD_LINE_COLOR, STYLE_FIELD_LINE_THICKNESS, STYLE_FIELD_SHADOW})
_FREEHAND_FIELDS = frozenset({STYLE_FIELD_LINE_COLOR, STYLE_FIELD_LINE_THICKNESS})
_OBFUSCATE_FIELDS = frozenset({STYLE_FIELD_OBFUSCATE_AMOUNT, STYLE_FIELD_OBFUSCATE_MODE})
_OBFUSCATE_COLOR_FIELDS = frozenset({
    STYLE_FIELD_OBFUSCATE_FILL_COLOR, STYLE_FIELD_OBFUSCATE_FILL_TEXT, STYLE_FIELD_OBFUSCATE_TEXT_COLOR,
    STYLE_FIELD_OBFUSCATE_MODE,
})
_OBFUSCATE_MODE_ONLY_FIELDS = frozenset({STYLE_FIELD_OBFUSCATE_MODE})
_HIGHLIGHT_COLOR_FIELDS = frozenset({STYLE_FIELD_HIGHLIGHT_FILL_COLOR, STYLE_FIELD_HIGHLIGHT_MODE})
_HIGHLIGHT_AREA_FIELDS = frozenset({
    STYLE_FIELD_HIGHLIGHT_BRIGHTNESS, STYLE_FIELD_HIGHLIGHT_BLUR_RADIUS, STYLE_FIELD_HIGHLIGHT_MODE,
})
_HIGHLIGHT_MODE_ONLY_FIELDS = frozenset({STYLE_FIELD_HIGHLIGHT_MODE})
_HIGHLIGHT_MAGNIFY_FIELDS = frozenset({STYLE_FIELD_HIGHLIGHT_MAGNIFICATION, STYLE_FIELD_HIGHLIGHT_MODE})
_CROP_FIELDS = frozenset({STYLE_FIELD_CROP_MODE})


class TestVisibleStyleFields:
    @pytest.mark.parametrize("tool,expected", [
        (Tool.RECTANGLE, _FULL_FIELDS),
        (Tool.ELLIPSE, _FULL_FIELDS),
        (Tool.TEXT, _FULL_FIELDS),
        (Tool.SPEECH_BUBBLE, _FULL_FIELDS),
        (Tool.STEP_LABEL, _FULL_FIELDS),
        (Tool.EMOJI, _FULL_FIELDS),
        (Tool.LINE, _LINE_ONLY_FIELDS),
        (Tool.ARROW, _LINE_ONLY_FIELDS),
        (Tool.FREEHAND, _FREEHAND_FIELDS),
        (Tool.PIXELIZE, _OBFUSCATE_FIELDS),
        (Tool.BLUR, _OBFUSCATE_FIELDS),
        (Tool.SOLID_FILL, _OBFUSCATE_COLOR_FIELDS),
        (Tool.SCRAMBLE, _OBFUSCATE_MODE_ONLY_FIELDS),
        (Tool.HIGHLIGHT_TEXT, _HIGHLIGHT_COLOR_FIELDS),
        (Tool.HIGHLIGHT_AREA, _HIGHLIGHT_AREA_FIELDS),
        (Tool.HIGHLIGHT_GRAYSCALE, _HIGHLIGHT_MODE_ONLY_FIELDS),
        (Tool.HIGHLIGHT_MAGNIFY, _HIGHLIGHT_MAGNIFY_FIELDS),
        (Tool.CROP_DEFAULT, _CROP_FIELDS),
        (Tool.CROP_VERTICAL, _CROP_FIELDS),
        (Tool.CROP_HORIZONTAL, _CROP_FIELDS),
    ])
    def test_tool_without_a_selection(self, tool, expected):
        assert visible_style_fields(tool) == expected

    def test_select_tool_with_nothing_selected_shows_nothing(self):
        # Matches Windows' RefreshFieldControls: no selection and no
        # active drawing mode means HideToolstripItems(), not "every
        # control visible" (this port's own previous behavior).
        assert visible_style_fields(Tool.SELECT) == frozenset()
        assert visible_style_fields(Tool.SELECT, selected_shape=None) == frozenset()

    @pytest.mark.parametrize("shape,expected", [
        (RectangleShape(Rect(0, 0, 10, 10), STYLE), _FULL_FIELDS),
        (EllipseShape(Rect(0, 0, 10, 10), STYLE), _FULL_FIELDS),
        (TextShape(Rect(0, 0, 10, 10), text="hi", style=STYLE), _FULL_FIELDS),
        (StepLabelShape(bounds=Rect(0, 0, 10, 10), number=1, style=STYLE), _FULL_FIELDS),
        (LineShape(start=(0, 0), end=(5, 5), style=STYLE), _LINE_ONLY_FIELDS),
        (ArrowShape(start=(0, 0), end=(5, 5), style=STYLE), _LINE_ONLY_FIELDS),
        (FreehandShape(points=((0, 0), (5, 5)), style=STYLE), _FREEHAND_FIELDS),
        (ObfuscateShape(Rect(0, 0, 10, 10), mode=ObfuscateMode.BLUR), _OBFUSCATE_FIELDS),
        (ObfuscateShape(Rect(0, 0, 10, 10), mode=ObfuscateMode.PIXELIZE), _OBFUSCATE_FIELDS),
        (ObfuscateShape(Rect(0, 0, 10, 10), mode=ObfuscateMode.SOLID_FILL), _OBFUSCATE_COLOR_FIELDS),
        (ObfuscateShape(Rect(0, 0, 10, 10), mode=ObfuscateMode.SCRAMBLE), _OBFUSCATE_MODE_ONLY_FIELDS),
        (HighlightShape(Rect(0, 0, 10, 10), mode=HighlightMode.TEXT_HIGHLIGHT), _HIGHLIGHT_COLOR_FIELDS),
        (HighlightShape(Rect(0, 0, 10, 10), mode=HighlightMode.AREA_HIGHLIGHT), _HIGHLIGHT_AREA_FIELDS),
        (HighlightShape(Rect(0, 0, 10, 10), mode=HighlightMode.GRAYSCALE), _HIGHLIGHT_MODE_ONLY_FIELDS),
        (HighlightShape(Rect(0, 0, 10, 10), mode=HighlightMode.MAGNIFICATION), _HIGHLIGHT_MAGNIFY_FIELDS),
        (IconShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()), frozenset()),
        (CursorShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()), frozenset()),
        (ImageShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()), frozenset()),
        (SvgShape(bounds=Rect(0, 0, 10, 10), svg_data="<svg/>"), frozenset()),
    ])
    def test_selected_shape_fields(self, shape, expected):
        # A selected shape's own fields, regardless of what tool
        # happens to be active - selecting an existing Line while
        # Rectangle is the active tool still shows Line's fields.
        assert visible_style_fields(Tool.RECTANGLE, selected_shape=shape) == expected

    def test_selection_overrides_the_active_tool(self):
        line = LineShape(start=(0, 0), end=(5, 5), style=STYLE)
        assert visible_style_fields(Tool.PIXELIZE, selected_shape=line) == _LINE_ONLY_FIELDS


class TestDefaultStyleForTool:
    @pytest.mark.parametrize("tool", [
        Tool.RECTANGLE, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.TEXT, Tool.EMOJI,
    ])
    def test_matches_shape_style_plain_default(self, tool):
        # RectangleContainer/EllipseContainer/LineContainer/
        # ArrowContainer/TextContainer's own InitializeFields all use
        # the same values ShapeStyle()'s own dataclass default already
        # has (thickness 2, Red, Transparent, shadow on).
        assert default_style_for_tool(tool) == ShapeStyle()

    def test_freehand_uses_thicker_default_line(self):
        # FreehandContainer.cs:67 - 3, not the usual 2.
        style = default_style_for_tool(Tool.FREEHAND)
        assert style.line_thickness == 3
        assert style.line_color == ShapeStyle().line_color

    def test_speech_bubble_uses_its_own_defaults(self):
        # SpeechbubbleContainer.cs:80-84 - White fill, no shadow,
        # unlike every other tool's Transparent/shadow-on - but Black
        # line, not the source's own Blue (a direct user request);
        # matches SpeechBubbleShape's own dataclass default (shapes.py).
        style = default_style_for_tool(Tool.SPEECH_BUBBLE)
        assert style.line_color == (0, 0, 0, 255)
        assert style.fill_color == (255, 255, 255, 255)
        assert style.shadow is False

    def test_step_label_matches_its_own_shape_default(self):
        # StepLabelContainer.cs:161-167 - DarkRed fill, White line,
        # thickness 0, no shadow; also matches StepLabelShape's own
        # dataclass default (shapes.py).
        assert default_style_for_tool(Tool.STEP_LABEL) == StepLabelShape(Rect(0, 0, 1, 1), number=1).style

    def test_unlisted_tool_falls_back_to_the_plain_default(self):
        assert default_style_for_tool(Tool.SELECT) == ShapeStyle()


class TestStyleKeyForShape:
    @pytest.mark.parametrize("shape,expected_tool", [
        (RectangleShape(Rect(0, 0, 10, 10), STYLE), Tool.RECTANGLE),
        (EllipseShape(Rect(0, 0, 10, 10), STYLE), Tool.ELLIPSE),
        (LineShape(start=(0, 0), end=(5, 5), style=STYLE), Tool.LINE),
        (ArrowShape(start=(0, 0), end=(5, 5), style=STYLE), Tool.ARROW),
        (FreehandShape(points=((0, 0), (5, 5)), style=STYLE), Tool.FREEHAND),
        (TextShape(Rect(0, 0, 10, 10), text="hi", style=STYLE), Tool.TEXT),
        (StepLabelShape(bounds=Rect(0, 0, 10, 10), number=1, style=STYLE), Tool.STEP_LABEL),
    ])
    def test_maps_shape_class_to_its_own_tool(self, shape, expected_tool):
        assert style_key_for_shape(shape) is expected_tool

    def test_speech_bubble(self):
        shape = SpeechBubbleShape(bubble_bounds=Rect(0, 0, 10, 10), target=(0, 20), text="hi", style=STYLE)
        assert style_key_for_shape(shape) is Tool.SPEECH_BUBBLE

    @pytest.mark.parametrize("shape", [
        ObfuscateShape(Rect(0, 0, 10, 10), mode=ObfuscateMode.BLUR),
        IconShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()),
        CursorShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()),
        ImageShape(bounds=Rect(0, 0, 10, 10), image=rgba_image()),
        SvgShape(bounds=Rect(0, 0, 10, 10), svg_data="<svg/>"),
    ])
    def test_shapes_with_no_style_field_have_no_key(self, shape):
        assert style_key_for_shape(shape) is None


class TestTranslateShape:
    def test_rectangle_bounds_shift(self):
        shape = RectangleShape(Rect(10, 10, 50, 50), STYLE)
        moved = translate_shape(shape, 5, -3)
        assert moved.bounds == Rect(15, 7, 55, 47)
        assert moved.style is STYLE

    def test_ellipse_bounds_shift(self):
        shape = EllipseShape(Rect(10, 10, 50, 50), STYLE)
        moved = translate_shape(shape, -2, 4)
        assert moved.bounds == Rect(8, 14, 48, 54)

    def test_line_endpoints_shift(self):
        shape = LineShape(start=(10, 10), end=(20, 30), style=STYLE)
        moved = translate_shape(shape, 3, 3)
        assert moved.start == (13, 13)
        assert moved.end == (23, 33)

    def test_arrow_endpoints_shift_and_stays_an_arrow(self):
        shape = ArrowShape(start=(10, 10), end=(20, 30), style=STYLE)
        moved = translate_shape(shape, 1, 1)
        assert isinstance(moved, ArrowShape)
        assert moved.start == (11, 11)
        assert moved.end == (21, 31)

    def test_freehand_points_shift(self):
        shape = FreehandShape(points=((0, 0), (5, 5)), style=STYLE)
        moved = translate_shape(shape, 2, 2)
        assert moved.points == ((2, 2), (7, 7))

    def test_obfuscate_bounds_shift(self):
        shape = ObfuscateShape(bounds=Rect(10, 10, 50, 50), mode=ObfuscateMode.BLUR, amount=9)
        moved = translate_shape(shape, 5, -3)
        assert moved.bounds == Rect(15, 7, 55, 47)
        assert moved.mode is ObfuscateMode.BLUR
        assert moved.amount == 9

    def test_text_bounds_shift(self):
        shape = TextShape(Rect(10, 10, 50, 50), text="hi", style=STYLE)
        moved = translate_shape(shape, 5, -3)
        assert moved.bounds == Rect(15, 7, 55, 47)
        assert moved.text == "hi"

    def test_step_label_icon_cursor_image_svg_bounds_shift(self):
        step_label = StepLabelShape(Rect(10, 10, 50, 50), number=3)
        assert translate_shape(step_label, 5, -3).bounds == Rect(15, 7, 55, 47)

        icon = IconShape(Rect(10, 10, 50, 50), image=rgba_image())
        assert translate_shape(icon, 5, -3).bounds == Rect(15, 7, 55, 47)

        cursor = CursorShape(Rect(10, 10, 50, 50), image=rgba_image())
        assert translate_shape(cursor, 5, -3).bounds == Rect(15, 7, 55, 47)

        image_shape = ImageShape(Rect(10, 10, 50, 50), image=rgba_image(), shadow=True)
        moved_image = translate_shape(image_shape, 5, -3)
        assert moved_image.bounds == Rect(15, 7, 55, 47)
        assert moved_image.shadow is True

        svg = SvgShape(Rect(10, 10, 50, 50), svg_data="<svg></svg>")
        assert translate_shape(svg, 5, -3).bounds == Rect(15, 7, 55, 47)

    def test_speech_bubble_bubble_bounds_shift_and_target_moves_too(self):
        # target moves with the bubble, same as a normal translate -
        # the tail keeps pointing the same *relative* direction.
        shape = SpeechBubbleShape(Rect(10, 10, 50, 50), target=(100, 100), text="hi")
        moved = translate_shape(shape, 5, -3)
        assert moved.bubble_bounds == Rect(15, 7, 55, 47)
        assert moved.target == (105, 97)

    def test_unsupported_shape_type_raises(self):
        with pytest.raises(NotImplementedError):
            translate_shape(NotARealShape(), 1, 1)

    def test_original_shape_is_unchanged(self):
        shape = RectangleShape(Rect(10, 10, 50, 50), STYLE)
        translate_shape(shape, 5, 5)
        assert shape.bounds == Rect(10, 10, 50, 50)


class TestScaleShape:
    def test_rectangle_bounds_scale_around_origin(self):
        shape = RectangleShape(Rect(10, 10, 50, 50), STYLE)
        scaled = scale_shape(shape, 2, 2)
        assert scaled.bounds == Rect(20, 20, 100, 100)

    def test_non_uniform_scale(self):
        shape = RectangleShape(Rect(10, 20, 50, 60), STYLE)
        scaled = scale_shape(shape, 0.5, 2)
        assert scaled.bounds == Rect(5, 40, 25, 120)

    def test_line_endpoints_scale(self):
        shape = LineShape(start=(10, 10), end=(20, 30), style=STYLE)
        scaled = scale_shape(shape, 2, 3)
        assert scaled.start == (20, 30)
        assert scaled.end == (40, 90)

    def test_freehand_points_scale(self):
        shape = FreehandShape(points=((10, 10), (20, 20)), style=STYLE)
        scaled = scale_shape(shape, 2, 2)
        assert scaled.points == ((20, 20), (40, 40))

    def test_speech_bubble_bubble_bounds_and_target_scale(self):
        shape = SpeechBubbleShape(Rect(10, 10, 50, 50), target=(100, 100), text="hi")
        scaled = scale_shape(shape, 2, 2)
        assert scaled.bubble_bounds == Rect(20, 20, 100, 100)
        assert scaled.target == (200, 200)

    def test_unsupported_shape_type_raises(self):
        with pytest.raises(NotImplementedError):
            scale_shape(NotARealShape(), 2, 2)

    def test_original_shape_is_unchanged(self):
        shape = RectangleShape(Rect(10, 10, 50, 50), STYLE)
        scale_shape(shape, 2, 2)
        assert shape.bounds == Rect(10, 10, 50, 50)


class TestRotateShape90:
    def test_clockwise_top_left_corner_moves_to_top_right(self):
        # a 1x1 shape at the old canvas's top-left corner ends up at
        # the new (rotated) canvas's top-right corner.
        shape = RectangleShape(Rect(0, 0, 1, 1), STYLE)
        rotated = rotate_shape_90(shape, old_width=100, old_height=60, clockwise=True)
        assert rotated.bounds == Rect(59, 0, 60, 1)

    def test_counterclockwise_top_left_corner_moves_to_bottom_left(self):
        shape = RectangleShape(Rect(0, 0, 1, 1), STYLE)
        rotated = rotate_shape_90(shape, old_width=100, old_height=60, clockwise=False)
        assert rotated.bounds == Rect(0, 99, 1, 100)

    def test_rotating_the_full_canvas_rect_fills_the_new_canvas(self):
        shape = RectangleShape(Rect(0, 0, 100, 60), STYLE)
        rotated = rotate_shape_90(shape, old_width=100, old_height=60, clockwise=True)
        assert rotated.bounds == Rect(0, 0, 60, 100)

    def test_line_endpoints_rotate(self):
        shape = LineShape(start=(0, 0), end=(100, 60), style=STYLE)
        rotated = rotate_shape_90(shape, old_width=100, old_height=60, clockwise=True)
        assert rotated.start == (60, 0)
        assert rotated.end == (0, 100)

    def test_four_clockwise_rotations_return_to_the_original_bounds(self):
        shape = RectangleShape(Rect(10, 5, 40, 25), STYLE)
        w, h = 100, 60
        for _ in range(4):
            shape = rotate_shape_90(shape, old_width=w, old_height=h, clockwise=True)
            w, h = h, w
        assert shape.bounds == Rect(10, 5, 40, 25)
        assert (w, h) == (100, 60)

    def test_unsupported_shape_type_raises(self):
        with pytest.raises(NotImplementedError):
            rotate_shape_90(NotARealShape(), old_width=100, old_height=60, clockwise=True)


_offset = st.integers(min_value=-500, max_value=500)


@given(_offset, _offset, _offset, _offset)
def test_translating_twice_composes_additively(dx1, dy1, dx2, dy2):
    shape = RectangleShape(Rect(100, 100, 200, 200), STYLE)
    twice = translate_shape(translate_shape(shape, dx1, dy1), dx2, dy2)
    once = translate_shape(shape, dx1 + dx2, dy1 + dy2)
    assert twice == once


class TestShapeHandles:
    def test_bounds_shape_has_eight_handles_at_corners_and_edge_midpoints(self):
        shape = RectangleShape(Rect(0, 0, 100, 40), STYLE)
        handles = shape_handles(shape)
        assert handles == {
            "top_left": (0, 0), "top": (50, 0), "top_right": (100, 0),
            "right": (100, 20), "bottom_right": (100, 40), "bottom": (50, 40),
            "bottom_left": (0, 40), "left": (0, 20),
        }

    def test_ellipse_obfuscate_and_text_shapes_use_the_same_bounds_handles(self):
        ellipse = EllipseShape(Rect(0, 0, 100, 40), STYLE)
        obfuscate = ObfuscateShape(Rect(0, 0, 100, 40))
        text = TextShape(Rect(0, 0, 100, 40), text="hi", style=STYLE)
        rect = RectangleShape(Rect(0, 0, 100, 40), STYLE)
        assert shape_handles(ellipse) == shape_handles(rect)
        assert shape_handles(obfuscate) == shape_handles(rect)
        assert shape_handles(text) == shape_handles(rect)

    def test_line_and_arrow_shapes_have_just_start_and_end_handles(self):
        line = LineShape(start=(10, 20), end=(90, 70), style=STYLE)
        assert shape_handles(line) == {"start": (10, 20), "end": (90, 70)}

        arrow = ArrowShape(start=(10, 20), end=(90, 70), style=STYLE)
        assert shape_handles(arrow) == {"start": (10, 20), "end": (90, 70)}

    def test_step_label_icon_cursor_image_svg_use_the_same_bounds_handles(self):
        rect = RectangleShape(Rect(0, 0, 100, 40), STYLE)
        expected = shape_handles(rect)

        assert shape_handles(StepLabelShape(Rect(0, 0, 100, 40), number=1)) == expected
        assert shape_handles(IconShape(Rect(0, 0, 100, 40), image=rgba_image())) == expected
        assert shape_handles(CursorShape(Rect(0, 0, 100, 40), image=rgba_image())) == expected
        assert shape_handles(ImageShape(Rect(0, 0, 100, 40), image=rgba_image())) == expected
        assert shape_handles(SvgShape(Rect(0, 0, 100, 40), svg_data="<svg></svg>")) == expected

    def test_freehand_handles_come_from_its_tight_bounding_box(self):
        shape = FreehandShape(points=((0, 0), (100, 40)), style=STYLE)
        assert shape_handles(shape) == shape_handles(RectangleShape(Rect(0, 0, 100, 40), STYLE))

    def test_speech_bubble_handles_come_from_bubble_bounds_not_bounds(self):
        # .bounds (the Drawable-protocol property) unions bubble_bounds
        # with the tail's own extent - a wider rect than bubble_bounds.
        # Handles must track the bubble box itself, not that union.
        shape = SpeechBubbleShape(Rect(0, 0, 100, 40), target=(500, 500), text="hi")
        assert shape.bounds != shape.bubble_bounds  # sanity: tail really does widen .bounds
        assert shape_handles(shape) == shape_handles(RectangleShape(shape.bubble_bounds, STYLE))

    def test_unsupported_shape_type_has_no_handles(self):
        assert shape_handles(NotARealShape()) == {}


class TestHandleAt:
    def test_finds_the_handle_within_margin(self):
        shape = RectangleShape(Rect(0, 0, 100, 40), STYLE)
        assert handle_at(shape, 2, 1, margin=6) == "top_left"
        assert handle_at(shape, 98, 39, margin=6) == "bottom_right"

    def test_returns_none_when_not_near_any_handle(self):
        shape = RectangleShape(Rect(0, 0, 100, 40), STYLE)
        assert handle_at(shape, 50, 20, margin=6) is None  # dead center

    def test_returns_none_for_a_shape_with_no_handles(self):
        assert handle_at(NotARealShape(), 0, 0) is None


class TestResizeShape:
    def test_dragging_a_corner_moves_both_edges(self):
        shape = RectangleShape(Rect(10, 10, 100, 100), STYLE)
        resized = resize_shape(shape, "top_left", 20, 30)
        assert resized.bounds == Rect(20, 30, 100, 100)

    def test_dragging_an_edge_midpoint_moves_only_that_edge(self):
        shape = RectangleShape(Rect(10, 10, 100, 100), STYLE)
        resized = resize_shape(shape, "top", 999, 30)  # x ignored for a top-only handle
        assert resized.bounds == Rect(10, 30, 100, 100)

    def test_dragging_past_the_opposite_edge_normalizes(self):
        shape = RectangleShape(Rect(10, 10, 100, 100), STYLE)
        resized = resize_shape(shape, "bottom_right", 5, 5)  # now above/left of top_left
        assert resized.bounds == Rect(5, 5, 10, 10)

    def test_ellipse_obfuscate_and_text_resize_the_same_way(self):
        ellipse = EllipseShape(Rect(10, 10, 100, 100), STYLE)
        assert resize_shape(ellipse, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        obfuscate = ObfuscateShape(Rect(10, 10, 100, 100))
        assert resize_shape(obfuscate, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        text = TextShape(Rect(10, 10, 100, 100), text="hi", style=STYLE)
        resized_text = resize_shape(text, "bottom_right", 150, 120)
        assert resized_text.bounds == Rect(10, 10, 150, 120)
        assert resized_text.text == "hi"

    def test_line_start_handle_moves_only_the_start_point(self):
        shape = LineShape(start=(10, 10), end=(90, 90), style=STYLE)
        resized = resize_shape(shape, "start", 5, 6)
        assert resized.start == (5, 6)
        assert resized.end == (90, 90)

    def test_arrow_end_handle_moves_only_the_end_point_and_stays_an_arrow(self):
        shape = ArrowShape(start=(10, 10), end=(90, 90), style=STYLE)
        resized = resize_shape(shape, "end", 200, 210)
        assert isinstance(resized, ArrowShape)
        assert resized.start == (10, 10)
        assert resized.end == (200, 210)

    def test_unknown_handle_for_a_line_raises(self):
        shape = LineShape(start=(10, 10), end=(90, 90), style=STYLE)
        with pytest.raises(ValueError):
            resize_shape(shape, "top_left", 5, 6)

    def test_step_label_icon_cursor_image_svg_resize_the_same_way(self):
        step_label = StepLabelShape(Rect(10, 10, 100, 100), number=1)
        assert resize_shape(step_label, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        icon = IconShape(Rect(10, 10, 100, 100), image=rgba_image())
        assert resize_shape(icon, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        cursor = CursorShape(Rect(10, 10, 100, 100), image=rgba_image())
        assert resize_shape(cursor, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        image_shape = ImageShape(Rect(10, 10, 100, 100), image=rgba_image())
        assert resize_shape(image_shape, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

        svg = SvgShape(Rect(10, 10, 100, 100), svg_data="<svg></svg>")
        assert resize_shape(svg, "bottom_right", 150, 120).bounds == Rect(10, 10, 150, 120)

    def test_speech_bubble_resizes_bubble_bounds_and_keeps_the_target(self):
        shape = SpeechBubbleShape(Rect(10, 10, 100, 100), target=(500, 500), text="hi")
        resized = resize_shape(shape, "bottom_right", 150, 120)
        assert resized.bubble_bounds == Rect(10, 10, 150, 120)
        assert resized.target == (500, 500)  # tail still points at the same spot
        assert resized.text == "hi"

    def test_freehand_resize_scales_the_points_proportionally(self):
        # bounds (0,0)-(100,40); dragging bottom_right to (200,80) is a
        # 2x scale on both axes, so every point doubles from the origin.
        shape = FreehandShape(points=((0, 0), (100, 40), (50, 20)), style=STYLE)
        resized = resize_shape(shape, "bottom_right", 200, 80)
        assert resized.points == ((0, 0), (200, 80), (100, 40))
        assert resized.style is STYLE

    def test_freehand_resize_via_top_left_scales_from_the_opposite_corner(self):
        shape = FreehandShape(points=((0, 0), (100, 40)), style=STYLE)
        resized = resize_shape(shape, "top_left", -100, -40)
        # new bounds (-100,-40)-(100,40): double width/height, anchored
        # so the original bottom-right point (100,40) stays put.
        assert resized.points == ((-100, -40), (100, 40))

    def test_unsupported_shape_type_raises(self):
        with pytest.raises(NotImplementedError):
            resize_shape(NotARealShape(), "top_left", 5, 6)

    def test_original_shape_is_unchanged(self):
        shape = RectangleShape(Rect(10, 10, 100, 100), STYLE)
        resize_shape(shape, "top_left", 20, 30)
        assert shape.bounds == Rect(10, 10, 100, 100)


class TestDefaultInsertBounds:
    """Where an Insert Image/SVG default lands - there's no drag
    gesture to size these from (unlike every other shape here), so
    inserted content needs a sensible one-shot placement: centered,
    scaled down only if it wouldn't otherwise fit.
    """

    def test_small_content_is_centered_at_its_natural_size(self):
        bounds = default_insert_bounds(content_w=100, content_h=50, canvas_w=800, canvas_h=600)
        assert bounds.width == 100
        assert bounds.height == 50
        cx = (bounds.left + bounds.right) / 2
        cy = (bounds.top + bounds.bottom) / 2
        assert (cx, cy) == (400, 300)

    def test_oversized_content_is_scaled_down_to_fit(self):
        bounds = default_insert_bounds(content_w=2000, content_h=1000, canvas_w=800, canvas_h=600)
        assert bounds.width <= 800
        assert bounds.height <= 600

    def test_scaling_preserves_aspect_ratio(self):
        bounds = default_insert_bounds(content_w=2000, content_h=1000, canvas_w=800, canvas_h=600)
        assert bounds.width / bounds.height == pytest.approx(2000 / 1000, rel=0.01)

    def test_result_is_still_centered_after_scaling_down(self):
        bounds = default_insert_bounds(content_w=2000, content_h=1000, canvas_w=800, canvas_h=600)
        cx = (bounds.left + bounds.right) / 2
        cy = (bounds.top + bounds.bottom) / 2
        assert cx == pytest.approx(400, abs=1)
        assert cy == pytest.approx(300, abs=1)

    def test_never_scales_up_content_smaller_than_the_canvas(self):
        bounds = default_insert_bounds(content_w=10, content_h=10, canvas_w=800, canvas_h=600)
        assert bounds.width == 10
        assert bounds.height == 10
