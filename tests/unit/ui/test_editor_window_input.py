"""EditorWindow's six pointer/keyboard/draw handlers, driven with fake
Gdk events against a real Gtk.Window.

These six methods are where every edit in the app actually begins, and
until now none of them had a test: `_on_button_press`, `_on_motion`,
`_on_button_release`, `_on_key_press`, `_on_draw` and
`_draw_crop_overlay` were verified only by hand on the VMs (BACKLOG
#220). They are also the densest branching in the file - press alone
forks eleven ways on `self.tool`, the Shift modifier, an existing crop
selection, a resize-handle hit, a shape hit and a double-click - so the
branch list below *is* the test list.

Synthesising real Gdk events needs a real event queue, so each handler
gets the minimal stand-in it actually reads instead (see FakeButtonEvent
/ FakeKeyEvent). Notably none of the three pointer handlers reads
`event.button` at all, which is pinned as behaviour in
TestButtonPress.test_a_right_click_is_treated_exactly_like_a_left_click.

Constructing the window needs a display; CI already runs the suite under
xvfb-run, and a developer without one gets these skipped (module-level
skipif, the same idiom as tests/unit/ui/test_editor_window.py - not the
`x11` marker, which CI deselects).

Nothing here may open a modal: `Gtk.Dialog.run()` never returns under a
test. The three key bindings whose action is nothing but a dialog
(Ctrl+S, Ctrl+P, bare Z) are asserted as *routing* with the action
stubbed on the instance; every other binding is asserted by its real
effect on the document.
"""

import os
from dataclasses import dataclass, field

import cairo
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="EditorWindow is a real Gtk.Window - constructing one needs a display (CI: xvfb-run)",
)

from gi.repository import Gdk

from orcshot.core.geometry import Rect
from orcshot.core.history import CompositeMemento
from orcshot.core.shapes import RectangleShape, ShapeStyle, TextShape
from orcshot.core.tools import Tool
from orcshot.ui.editor_window import EditorWindow

# Handles are _HANDLE_SIZE=6 wide and crop handles sit on the selection's
# own corners/edges, so any pixel assertion has to sample well clear of
# both. 12px is two handle-widths.
_CLEAR_OF_HANDLES = 12


def _capture(width: int = 640, height: int = 400) -> np.ndarray:
    """A capture-shaped RGBA image with real variation in it, rather
    than a uniform block - the obfuscate/effect paths downstream read
    pixel values, so a zeros() array is not representative data.

    Copied from tests/unit/ui/test_editor_window.py rather than imported:
    pytest runs in importlib mode here, so test modules cannot import
    each other.
    """
    xs = np.linspace(0, 255, width, dtype=np.uint8)
    ys = np.linspace(0, 255, height, dtype=np.uint8)
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 0] = xs[None, :]
    image[:, :, 1] = ys[:, None]
    image[:, :, 2] = 128
    image[:, :, 3] = 255
    return image


@dataclass
class FakeButtonEvent:
    """Only the four attributes the three pointer handlers read.

    `button` is deliberately absent: no pointer handler in
    editor_window.py reads it (verified by reading all three). Giving the
    fake one would suggest a branch that does not exist.
    """

    x: float = 10.0
    y: float = 20.0
    state: Gdk.ModifierType = field(default_factory=lambda: Gdk.ModifierType(0))
    type: Gdk.EventType = Gdk.EventType.BUTTON_PRESS


@dataclass
class FakeKeyEvent:
    keyval: int = Gdk.KEY_Escape
    state: Gdk.ModifierType = field(default_factory=lambda: Gdk.ModifierType(0))


def _shift() -> Gdk.ModifierType:
    return Gdk.ModifierType.SHIFT_MASK


def _ctrl() -> Gdk.ModifierType:
    return Gdk.ModifierType.CONTROL_MASK


@pytest.fixture
def editor():
    window = EditorWindow(_capture())
    # Every coordinate assertion below reads as image-space only because
    # the unrealized window centres nothing and the zoom is 1:1. Asserted
    # rather than assumed, so a change to _content_offset shows up here as
    # a failure in this fixture rather than as eight confusing ones.
    assert window._content_offset() == (0, 0)
    assert float(window._zoom) == 1.0
    yield window
    window.destroy()


def _shape(left: int = 100, top: int = 100, right: int = 200, bottom: int = 160) -> RectangleShape:
    """A *filled* rectangle, deliberately: RectangleShape's clickable_at
    is a faithful port of RectangleClickableAt, so a hollow one is only
    clickable within line_thickness/2 of its outline - and every hit-test
    assertion below wants to click the middle of a shape, not thread a
    2px outline that also happens to be where the resize handles sit.
    """
    return RectangleShape(
        bounds=Rect(left, top, right, bottom),
        style=ShapeStyle(fill_color=(0, 0, 255, 255)),
    )


def _press(editor, x, y, state=None, type=Gdk.EventType.BUTTON_PRESS):
    return editor._on_button_press(
        editor._drawing_area,
        FakeButtonEvent(x=x, y=y, state=state or Gdk.ModifierType(0), type=type),
    )


def _motion(editor, x, y):
    return editor._on_motion(editor._drawing_area, FakeButtonEvent(x=x, y=y))


def _release(editor, x, y):
    return editor._on_button_release(editor._drawing_area, FakeButtonEvent(x=x, y=y))


def _key(editor, keyval, state=None):
    return editor._on_key_press(editor, FakeKeyEvent(keyval=keyval, state=state or Gdk.ModifierType(0)))


def _undo_depth(editor) -> int:
    """How many entries are on the undo stack. The public `can_undo` only
    says "at least one", and several assertions below turn on *exactly*
    one (a two-shape move is one CompositeMemento, not two mementos).
    """
    return len(editor.undo_redo._undo)


def _surface_and_ctx(width=320, height=240):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    return surface, cairo.Context(surface)


def _alpha_at(surface: cairo.ImageSurface, x: int, y: int) -> int:
    """One pixel's alpha byte out of a FORMAT_ARGB32 surface. On a
    surface that started fully transparent, alpha > 0 means "something
    was painted here", which is what the crop-overlay geometry assertions
    need - they are about *where* the tint lands, not its colour.
    """
    surface.flush()
    data = surface.get_data()
    stride = surface.get_stride()
    # cairo's ARGB32 is a native-endian 32-bit word, so on the
    # little-endian hosts this project targets the byte order is BGRA and
    # alpha is the last byte of the pixel.
    return data[y * stride + x * 4 + 3]


class TestOnDraw:
    """_on_draw paints the base surface, then each shape (following
    whichever live preview applies), then the selection adornments, then
    the crop overlay. The three-way shape branch is asserted through
    render_shape's own arguments - which shape object reaches the
    renderer *is* the branch decision - and the crop overlay through real
    pixels, where geometry is the behaviour.
    """

    @pytest.mark.parametrize("tool", list(Tool))
    def test_every_tool_draws_against_a_real_cairo_context(self, editor, tool):
        editor.tool = tool
        if tool in (Tool.CROP_DEFAULT, Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL):
            editor._crop_selection = Rect(40, 30, 200, 150)
        shape = _shape()
        editor.layer.add(shape)
        editor.selected_shape = shape
        surface, ctx = _surface_and_ctx(640, 400)

        assert editor._on_draw(editor._drawing_area, ctx) is False
        assert surface.get_data()  # something really was painted

    def test_the_base_capture_is_painted_before_anything_else(self, editor):
        surface, ctx = _surface_and_ctx(640, 400)

        editor._on_draw(editor._drawing_area, ctx)

        # The capture is fully opaque, so every pixel of the drawn area
        # is opaque even with an empty layer.
        assert _alpha_at(surface, 5, 5) == 255
        assert _alpha_at(surface, 600, 380) == 255

    def test_a_moving_shape_is_drawn_at_its_preview_position_not_its_own(self, editor, monkeypatch):
        shape = _shape()
        editor.layer.add(shape)
        preview = _shape(140, 140, 240, 200)
        editor._move_shapes = [shape]
        editor._move_previews = [preview]
        drawn = []
        monkeypatch.setattr(
            "orcshot.ui.editor_window.render_shape",
            lambda ctx, s, **kwargs: drawn.append(s),
        )
        _, ctx = _surface_and_ctx()

        editor._on_draw(editor._drawing_area, ctx)

        assert drawn == [preview]

    def test_a_resizing_shape_is_drawn_at_its_resize_preview(self, editor, monkeypatch):
        shape = _shape()
        editor.layer.add(shape)
        preview = _shape(100, 100, 300, 260)
        editor._resize_shape = shape
        editor._resize_preview = preview
        drawn = []
        monkeypatch.setattr(
            "orcshot.ui.editor_window.render_shape",
            lambda ctx, s, **kwargs: drawn.append(s),
        )
        _, ctx = _surface_and_ctx()

        editor._on_draw(editor._drawing_area, ctx)

        assert drawn == [preview]

    def test_the_in_progress_drag_shape_is_drawn_on_top_of_the_layer(self, editor, monkeypatch):
        committed = _shape()
        editor.layer.add(committed)
        dragging = _shape(300, 300, 360, 340)
        editor._drag_shape = dragging
        drawn = []
        monkeypatch.setattr(
            "orcshot.ui.editor_window.render_shape",
            lambda ctx, s, **kwargs: drawn.append(s),
        )
        _, ctx = _surface_and_ctx()

        editor._on_draw(editor._drawing_area, ctx)

        assert drawn == [committed, dragging]

    def test_the_crop_overlay_is_drawn_in_a_crop_mode_with_a_selection(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        editor._crop_selection = Rect(100, 80, 240, 200)
        surface, ctx = _surface_and_ctx(640, 400)
        tinted = []
        original = editor._draw_crop_overlay
        editor._draw_crop_overlay = lambda ctx, rect: tinted.append(rect) or original(ctx, rect)

        editor._on_draw(editor._drawing_area, ctx)

        assert tinted == [Rect(100, 80, 240, 200)]

    def test_a_leftover_crop_selection_is_not_drawn_once_the_tool_is_not_a_crop_mode(self, editor):
        # Set directly, bypassing the tool setter that would have cleared
        # it - _on_draw's own gate is the *tool*, not the selection, and
        # this pins that rather than relying on the setter to make it
        # unreachable.
        editor.tool = Tool.RECTANGLE
        editor._crop_selection = Rect(100, 80, 240, 200)
        _, ctx = _surface_and_ctx(640, 400)
        tinted = []
        editor._draw_crop_overlay = lambda ctx, rect: tinted.append(rect)

        editor._on_draw(editor._drawing_area, ctx)

        assert tinted == []

    def test_non_primary_selected_shapes_get_an_outline_and_the_primary_gets_handles(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first, second])
        outlined, handled = [], []
        editor._draw_selection_outline = lambda ctx, s: outlined.append(s)
        editor._draw_handles = lambda ctx, s: handled.append(s)
        _, ctx = _surface_and_ctx()

        editor._on_draw(editor._drawing_area, ctx)

        assert outlined == [first]
        assert handled == [second]


class TestDrawCropOverlay:
    """Which side of the selection gets tinted is the whole point of the
    three crop modes: Default tints what confirming would *throw away*
    (outside), Vertical/Horizontal tint the band they remove (inside).
    Asserted on real pixels of a transparent surface, so the overlay's
    own paint is the only thing there.
    """

    def test_default_mode_tints_outside_the_selection_and_leaves_it_clear(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        rect = Rect(100, 80, 240, 200)
        surface, ctx = _surface_and_ctx(640, 400)

        editor._draw_crop_overlay(ctx, rect)

        inside_x = (rect.left + rect.right) // 2
        inside_y = (rect.top + rect.bottom) // 2
        assert _alpha_at(surface, inside_x, inside_y) == 0
        assert _alpha_at(surface, rect.left - _CLEAR_OF_HANDLES, inside_y) > 0
        assert _alpha_at(surface, inside_x, rect.top - _CLEAR_OF_HANDLES) > 0

    @pytest.mark.parametrize("mode", [Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL])
    def test_the_crop_out_modes_tint_inside_the_selection_instead(self, editor, mode):
        editor.tool = mode
        rect = Rect(100, 80, 240, 200)
        surface, ctx = _surface_and_ctx(640, 400)

        editor._draw_crop_overlay(ctx, rect)

        inside_x = (rect.left + rect.right) // 2
        inside_y = (rect.top + rect.bottom) // 2
        assert _alpha_at(surface, inside_x, inside_y) > 0
        assert _alpha_at(surface, rect.left - _CLEAR_OF_HANDLES, inside_y) == 0

    def test_default_mode_paints_an_opaque_handle_on_each_corner(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        rect = Rect(100, 80, 240, 200)
        surface, ctx = _surface_and_ctx(640, 400)

        editor._draw_crop_overlay(ctx, rect)

        for hx, hy in ((rect.left, rect.top), (rect.right, rect.top),
                       (rect.left, rect.bottom), (rect.right, rect.bottom)):
            assert _alpha_at(surface, hx, hy) == 255, f"no corner handle at {(hx, hy)}"

    def test_vertical_mode_paints_two_edge_handles_and_no_corner_ones(self, editor):
        # CreateLeftRightAdorners: only the axis this mode's drag varies
        # gets a handle, so the corners must stay bare.
        editor.tool = Tool.CROP_VERTICAL
        rect = Rect(100, 0, 240, 400)
        surface, ctx = _surface_and_ctx(640, 400)

        editor._draw_crop_overlay(ctx, rect)

        mid_y = (rect.top + rect.bottom) // 2
        assert _alpha_at(surface, rect.left, mid_y) == 255
        assert _alpha_at(surface, rect.right, mid_y) == 255
        assert _alpha_at(surface, rect.left, rect.top + _CLEAR_OF_HANDLES) < 255

    def test_horizontal_mode_paints_its_handles_on_the_top_and_bottom_edges(self, editor):
        editor.tool = Tool.CROP_HORIZONTAL
        rect = Rect(0, 80, 640, 200)
        surface, ctx = _surface_and_ctx(640, 400)

        editor._draw_crop_overlay(ctx, rect)

        mid_x = (rect.left + rect.right) // 2
        assert _alpha_at(surface, mid_x, rect.top) == 255
        assert _alpha_at(surface, mid_x, rect.bottom) == 255
        assert _alpha_at(surface, rect.left + _CLEAR_OF_HANDLES, rect.top) < 255


class TestButtonPress:
    def test_a_crop_press_on_empty_space_starts_a_degenerate_selection(self, editor):
        editor.tool = Tool.CROP_DEFAULT

        assert _press(editor, 40, 30) is True

        assert editor._crop_selection == Rect(40, 30, 40, 30)
        assert editor._drag_origin == (40, 30)
        assert len(editor.layer) == 0

    def test_a_crop_press_on_a_handle_starts_a_resize_and_keeps_the_selection(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        selection = Rect(100, 80, 240, 200)
        editor._crop_selection = selection

        assert _press(editor, 240, 200) is True

        assert editor._crop_resize_handle == "bottom_right"
        assert editor._crop_selection is selection
        assert editor._drag_origin is None

    def test_a_crop_press_clear_of_every_handle_restarts_the_selection(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        editor._crop_selection = Rect(100, 80, 240, 200)

        _press(editor, 400, 300)

        assert editor._crop_selection == Rect(400, 300, 400, 300)
        assert editor._crop_resize_handle is None

    def test_a_crop_press_never_creates_a_shape_even_over_one(self, editor):
        existing = _shape()
        editor.layer.add(existing)
        editor.tool = Tool.CROP_VERTICAL

        _press(editor, 150, 130)

        assert list(editor.layer) == [existing]
        assert editor.selected_shapes == []
        assert editor._drag_shape is None

    def test_pressing_a_selected_shapes_handle_starts_a_resize(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor.selected_shape = shape

        assert _press(editor, 200, 160) is True

        assert editor._resize_shape is shape
        assert editor._resize_handle == "bottom_right"
        assert editor._move_shapes == []

    def test_a_double_click_on_a_text_shape_opens_the_text_editor(self, editor):
        text = TextShape(bounds=Rect(100, 100, 200, 140), text="hello")
        editor.layer.add(text)
        editor._move_shapes = [text]
        editor._move_origin = (150, 120)

        assert _press(editor, 150, 120, type=Gdk.EventType._2BUTTON_PRESS) is True

        # Equal, not identical: _show_text_editor's own buffer.set_text
        # fires "changed", and _update_editing_text answers that by
        # swapping in a dataclasses.replace copy - so the object being
        # edited is a fresh equal shape by the time the press returns,
        # while _editing_original_shape still holds the pre-edit one that
        # a cancel has to restore. Pinned as observed, not changed.
        assert editor._editing_text_shape == text
        assert editor._editing_text_shape is list(editor.layer)[0]
        assert editor._editing_original_shape is text
        # The single press that preceded this one had already started a
        # move; a double-click means edit, so that move is cancelled.
        assert editor._move_shapes == []
        assert editor._move_origin is None

    def test_a_shift_click_toggles_an_already_selected_shape_out_of_the_selection(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first, second])

        assert _press(editor, 150, 130, state=_shift()) is True

        assert editor.selected_shapes == [second]
        # No move started for a shape that is no longer selected.
        assert editor._move_shapes == []

    def test_a_shift_click_adds_an_unselected_shape_to_the_selection(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first])

        _press(editor, 350, 330, state=_shift())

        assert editor.selected_shapes == [first, second]
        assert editor._move_shapes == [first, second]

    def test_a_plain_click_on_an_unselected_shape_replaces_the_whole_selection(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first])

        _press(editor, 350, 330)

        assert editor.selected_shapes == [second]

    def test_a_plain_click_on_a_member_of_a_multi_selection_keeps_the_group(self, editor):
        # Surface.cs:1611-1630 - so dragging any member moves them all.
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first, second])

        _press(editor, 150, 130)

        assert editor.selected_shapes == [first, second]
        assert editor._move_shapes == [first, second]
        assert editor._move_origin == (150, 130)

    def test_select_on_empty_space_clears_the_selection_and_starts_a_rubber_band(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor._set_selected_shapes([shape])
        editor.tool = Tool.SELECT

        _press(editor, 500, 350)

        assert editor.selected_shapes == []
        assert editor._rubber_band_origin == (500, 350)
        assert editor._rubber_band_rect == Rect(500, 350, 500, 350)
        assert editor._rubber_band_additive is False

    def test_a_shift_drag_on_empty_space_starts_an_additive_rubber_band(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor._set_selected_shapes([shape])
        editor.tool = Tool.SELECT

        _press(editor, 500, 350, state=_shift())

        assert editor.selected_shapes == [shape]
        assert editor._rubber_band_additive is True

    def test_a_drawing_tool_on_empty_space_starts_a_preview_and_adds_nothing_yet(self, editor):
        editor.tool = Tool.RECTANGLE

        assert _press(editor, 50, 60) is True

        assert editor._drag_origin == (50, 60)
        assert isinstance(editor._drag_shape, RectangleShape)
        assert editor._drag_shape.bounds == Rect(50, 60, 50, 60)
        assert len(editor.layer) == 0
        assert _undo_depth(editor) == 0

    def test_freehand_seeds_its_point_list_with_the_press_point(self, editor):
        editor.tool = Tool.FREEHAND

        _press(editor, 50, 60)

        assert editor._drag_points == [(50, 60)]
        assert editor._drag_shape is not None

    def test_a_press_commits_an_in_progress_text_edit_first(self, editor):
        text = TextShape(bounds=Rect(100, 100, 200, 140), text="typed")
        editor.layer.add(text)
        committed = []
        editor._commit_text_editing = lambda: committed.append(True)
        editor._editing_text_shape = text
        editor.tool = Tool.RECTANGLE

        _press(editor, 400, 300)

        assert committed == [True]

    def test_widget_pixels_are_converted_back_to_image_space_at_any_zoom(self, editor):
        # InverseZoomMouseCoordinates (Surface.cs:1469-1470): at 2x, a
        # press 100 widget-pixels across is 50 image-pixels across, and
        # hit-testing/drawing must use the latter.
        editor._zoom = 2.0
        editor.tool = Tool.RECTANGLE

        _press(editor, 100, 60)

        assert editor._drag_origin == (50, 30)

    def test_a_right_click_is_treated_exactly_like_a_left_click(self, editor):
        """Pinned as observed behaviour, not endorsed: none of the three
        pointer handlers reads `event.button`, so button 3 starts a draw
        drag exactly as button 1 does, and there is no context menu on
        the canvas. Reported with BACKLOG #220 rather than changed here -
        a test does not get to decide the app's mouse semantics.
        """
        editor.tool = Tool.RECTANGLE
        event = FakeButtonEvent(x=50, y=60)
        # A real button-3 press carries BUTTON3_MASK in its state; the
        # handler only ever masks for SHIFT, so it changes nothing.
        event.state = Gdk.ModifierType.BUTTON3_MASK

        assert editor._on_button_press(editor._drawing_area, event) is True

        assert editor._drag_origin == (50, 60)


class TestMotion:
    def test_motion_with_no_drag_in_progress_mutates_nothing(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor._set_selected_shapes([shape])

        assert _motion(editor, 300, 300) is False

        assert list(editor.layer) == [shape]
        assert editor.selected_shapes == [shape]
        assert editor._drag_shape is None
        assert editor._move_previews == []
        assert _undo_depth(editor) == 0

    def test_dragging_grows_the_preview_shape_without_touching_the_layer(self, editor):
        editor.tool = Tool.RECTANGLE
        _press(editor, 50, 60)

        assert _motion(editor, 150, 200) is True

        assert editor._drag_shape.bounds == Rect(50, 60, 150, 200)
        assert len(editor.layer) == 0

    def test_freehand_motion_appends_each_point(self, editor):
        editor.tool = Tool.FREEHAND
        _press(editor, 10, 10)

        _motion(editor, 20, 30)
        _motion(editor, 40, 50)

        assert editor._drag_points == [(10, 10), (20, 30), (40, 50)]

    def test_a_move_in_progress_previews_the_translation_and_leaves_the_layer_alone(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor._set_selected_shapes([shape])
        _press(editor, 150, 130)

        assert _motion(editor, 170, 160) is True

        assert [s.bounds for s in editor._move_previews] == [Rect(120, 130, 220, 190)]
        assert list(editor.layer)[0].bounds == Rect(100, 100, 200, 160)

    def test_a_rubber_band_follows_the_pointer(self, editor):
        editor.tool = Tool.SELECT
        _press(editor, 500, 350)

        assert _motion(editor, 300, 200) is True

        assert editor._rubber_band_rect == Rect(300, 200, 500, 350)

    def test_a_resize_in_progress_previews_the_new_bounds(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor.selected_shape = shape
        _press(editor, 200, 160)

        assert _motion(editor, 300, 260) is True

        assert editor._resize_preview.bounds == Rect(100, 100, 300, 260)
        assert list(editor.layer)[0] is shape

    def test_a_crop_resize_follows_the_dragged_handle(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        editor._crop_selection = Rect(100, 80, 240, 200)
        _press(editor, 240, 200)

        _motion(editor, 300, 260)

        assert editor._crop_selection == Rect(100, 80, 300, 260)

    def test_a_crop_drag_follows_the_pointer_from_its_origin(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        _press(editor, 40, 30)

        assert _motion(editor, 300, 260) is True

        assert editor._crop_selection == Rect(40, 30, 300, 260)

    def test_a_vertical_crop_drag_always_spans_the_full_image_height(self, editor):
        # CropContainer.HandleMouseMove forces Top=0/Height=image.Height
        # for this mode - only the x axis the drag varies is free.
        editor.tool = Tool.CROP_VERTICAL
        _press(editor, 100, 200)

        _motion(editor, 260, 210)

        assert editor._crop_selection == Rect(100, 0, 260, 400)


class TestButtonRelease:
    def test_a_rectangle_gesture_appends_exactly_one_selected_shape(self, editor):
        editor.tool = Tool.RECTANGLE
        _press(editor, 50, 60)
        _motion(editor, 150, 200)

        assert _release(editor, 150, 200) is True

        shapes = list(editor.layer)
        assert len(shapes) == 1
        assert shapes[0].bounds == Rect(50, 60, 150, 200)
        assert editor.selected_shape is shapes[0]
        assert _undo_depth(editor) == 1
        assert editor._drag_shape is None
        assert editor._drag_origin is None

    def test_a_freehand_gesture_commits_the_whole_collected_stroke(self, editor):
        # The committed shape is built from the accumulated point list,
        # not from the release coordinate the other tools use - so the
        # intermediate motion points have to survive into the layer.
        editor.tool = Tool.FREEHAND
        _press(editor, 10, 10)
        _motion(editor, 20, 30)
        _motion(editor, 40, 50)

        assert _release(editor, 40, 50) is True

        shapes = list(editor.layer)
        assert len(shapes) == 1
        assert list(shapes[0].points) == [(10, 10), (20, 30), (40, 50)]
        assert editor.selected_shape is shapes[0]
        assert _undo_depth(editor) == 1
        assert editor._drag_points is None

    def test_a_crop_gesture_sets_the_selection_and_creates_no_shape(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        _press(editor, 40, 30)
        _motion(editor, 300, 260)

        assert _release(editor, 300, 260) is True

        assert editor._crop_selection == Rect(40, 30, 300, 260)
        assert len(editor.layer) == 0
        assert _undo_depth(editor) == 0
        assert editor._drag_origin is None

    def test_releasing_a_crop_handle_finishes_the_resize_and_clears_the_handle(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        editor._crop_selection = Rect(100, 80, 240, 200)
        _press(editor, 100, 80)

        _release(editor, 60, 40)

        assert editor._crop_selection == Rect(60, 40, 240, 200)
        assert editor._crop_resize_handle is None

    def test_releasing_a_resize_commits_it_as_one_undo_step(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor.selected_shape = shape
        _press(editor, 200, 160)

        assert _release(editor, 300, 260) is True

        committed = list(editor.layer)
        assert len(committed) == 1
        assert committed[0].bounds == Rect(100, 100, 300, 260)
        assert editor.selected_shape is committed[0]
        assert _undo_depth(editor) == 1
        assert editor._resize_shape is None
        assert editor._resize_handle is None
        assert editor._resize_preview is None

    def test_moving_two_shapes_commits_both_as_a_single_composite_undo(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first, second])
        _press(editor, 150, 130)
        _motion(editor, 170, 160)

        assert _release(editor, 170, 160) is True

        assert [s.bounds for s in editor.layer] == [Rect(120, 130, 220, 190), Rect(320, 330, 420, 390)]
        assert _undo_depth(editor) == 1
        assert isinstance(editor.undo_redo._undo[0], CompositeMemento)
        assert [s.bounds for s in editor.selected_shapes] == [Rect(120, 130, 220, 190), Rect(320, 330, 420, 390)]
        assert editor._move_shapes == []
        assert editor._move_previews == []

    def test_a_click_that_never_moved_pushes_no_undo_and_keeps_the_selection(self, editor):
        first, second = _shape(), _shape(300, 300, 400, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([first, second])
        _press(editor, 150, 130)

        _release(editor, 150, 130)

        assert _undo_depth(editor) == 0
        assert editor.selected_shapes == [first, second]
        assert list(editor.layer) == [first, second]
        assert editor._move_shapes == []

    def test_a_rubber_band_selects_only_the_fully_enclosed_shapes(self, editor):
        inside, outside = _shape(), _shape(500, 300, 600, 360)
        editor.layer.add(inside)
        editor.layer.add(outside)
        editor.tool = Tool.SELECT
        _press(editor, 20, 20)
        _motion(editor, 400, 300)

        assert _release(editor, 400, 300) is True

        assert editor.selected_shapes == [inside]
        assert editor._rubber_band_origin is None
        assert editor._rubber_band_rect is None

    def test_an_additive_rubber_band_unions_with_the_existing_selection(self, editor):
        first, second = _shape(), _shape(500, 300, 600, 360)
        editor.layer.add(first)
        editor.layer.add(second)
        editor._set_selected_shapes([second])
        editor.tool = Tool.SELECT
        _press(editor, 20, 20, state=_shift())
        _motion(editor, 400, 300)

        _release(editor, 400, 300)

        assert editor.selected_shapes == [second, first]

    def test_a_text_gesture_opens_the_editor_and_defers_the_undo_entry(self, editor):
        editor.tool = Tool.TEXT
        _press(editor, 50, 60)
        _motion(editor, 200, 100)

        _release(editor, 200, 100)

        assert len(editor.layer) == 1
        assert editor._editing_text_shape is list(editor.layer)[0]
        assert editor._editing_original_shape is None  # brand new, not a re-edit
        assert editor._text_editor.get_visible() is True
        # AddElementMemento waits for _commit_text_editing.
        assert _undo_depth(editor) == 0

    def test_a_release_with_nothing_in_progress_is_not_handled(self, editor):
        assert _release(editor, 100, 100) is False


class TestKeyPress:
    def test_keys_are_left_to_the_focused_text_editor_while_one_is_open(self, editor):
        editor._editing_text_shape = TextShape(bounds=Rect(10, 10, 100, 40), text="x")
        editor.tool = Tool.RECTANGLE

        assert _key(editor, Gdk.KEY_r) is False

        assert editor.tool is Tool.RECTANGLE  # no shortcut ran

    def test_escape_with_an_unconfirmed_crop_discards_the_crop_and_does_not_close(self, editor):
        # Entered through the real Crop button (the C shortcut), not by
        # assigning .tool: Escape's own route is
        # _tool_buttons[SELECT].set_active(True), which only reaches the
        # tool setter by firing "toggled" - and it only fires if the
        # toolbar's radio group really moved off Select.
        _key(editor, Gdk.KEY_c)
        assert editor.tool in (Tool.CROP_DEFAULT, Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL)
        editor._crop_selection = Rect(100, 80, 240, 200)

        # True = handled here, so the key never propagates on to become a
        # window close - Escape means "back to the Select tool"
        # (Windows' own `case Keys.Escape: BtnCursorClick`).
        assert _key(editor, Gdk.KEY_Escape) is True

        assert editor.tool is Tool.SELECT
        assert editor._crop_selection is None
        assert editor._crop_resize_handle is None

    @pytest.mark.parametrize(
        "keyval,expected",
        [
            (Gdk.KEY_r, Tool.RECTANGLE),
            (Gdk.KEY_R, Tool.RECTANGLE),
            (Gdk.KEY_e, Tool.ELLIPSE),
            (Gdk.KEY_l, Tool.LINE),
            (Gdk.KEY_f, Tool.FREEHAND),
            (Gdk.KEY_a, Tool.ARROW),
            (Gdk.KEY_t, Tool.TEXT),
            (Gdk.KEY_s, Tool.SPEECH_BUBBLE),
            (Gdk.KEY_i, Tool.STEP_LABEL),
            (Gdk.KEY_m, Tool.EMOJI),
        ],
    )
    def test_each_letter_mnemonic_activates_its_tool_and_its_toolbar_button(self, editor, keyval, expected):
        assert _key(editor, keyval) is True

        assert editor.tool is expected
        assert editor._tool_buttons[expected].get_active() is True

    def test_h_o_and_c_activate_the_three_multi_mode_toolbar_buttons(self, editor):
        # Each stands in for several Tool values, so the assertion is on
        # which family became active, not on one specific mode.
        assert _key(editor, Gdk.KEY_h) is True
        assert editor.tool in (Tool.HIGHLIGHT_TEXT, Tool.HIGHLIGHT_AREA,
                               Tool.HIGHLIGHT_GRAYSCALE, Tool.HIGHLIGHT_MAGNIFY)

        assert _key(editor, Gdk.KEY_o) is True
        assert editor.tool in (Tool.PIXELIZE, Tool.BLUR, Tool.SOLID_FILL, Tool.SCRAMBLE)

        assert _key(editor, Gdk.KEY_c) is True
        assert editor.tool in (Tool.CROP_DEFAULT, Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL)

    @pytest.mark.parametrize("keyval", [Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add])
    def test_ctrl_plus_zooms_in(self, editor, keyval):
        before = float(editor._zoom)

        assert _key(editor, keyval, state=_ctrl()) is True

        assert float(editor._zoom) > before

    @pytest.mark.parametrize("keyval", [Gdk.KEY_minus, Gdk.KEY_KP_Subtract])
    def test_ctrl_minus_zooms_out(self, editor, keyval):
        editor._do_zoom_in()
        before = float(editor._zoom)

        assert _key(editor, keyval, state=_ctrl()) is True

        assert float(editor._zoom) < before

    def test_ctrl_shift_plus_enlarges_the_canvas_instead_of_zooming(self, editor):
        # The same physical key: GDK reports the already-shifted
        # character, so Shift state is the only thing telling these two
        # bindings apart.
        zoom_before = float(editor._zoom)

        assert _key(editor, Gdk.KEY_plus, state=_ctrl() | _shift()) is True

        assert editor.base_image.shape[:2] == (400 + 50, 640 + 50)
        assert float(editor._zoom) == zoom_before

    def test_ctrl_shift_minus_shrinks_the_canvas_instead_of_zooming(self, editor):
        editor._do_enlarge_canvas()  # a transparent margin for autocrop to find
        zoom_before = float(editor._zoom)

        assert _key(editor, Gdk.KEY_minus, state=_ctrl() | _shift()) is True

        assert editor.base_image.shape[:2] == (400, 640)
        assert float(editor._zoom) == zoom_before

    def test_ctrl_0_returns_to_actual_size(self, editor):
        editor._zoom = 3.0

        assert _key(editor, Gdk.KEY_0, state=_ctrl()) is True

        assert float(editor._zoom) == 1.0

    def test_ctrl_9_switches_to_best_fit(self, editor):
        editor._zoom = 3.0

        assert _key(editor, Gdk.KEY_9, state=_ctrl()) is True

        assert float(editor._zoom) != 3.0

    def test_delete_removes_the_selection_and_ctrl_delete_clears_the_image(self, editor):
        shape = _shape()
        editor.layer.add(shape)
        editor._set_selected_shapes([shape])

        assert _key(editor, Gdk.KEY_Delete) is True
        assert len(editor.layer) == 0

        before = editor.base_image.copy()
        assert _key(editor, Gdk.KEY_Delete, state=_ctrl()) is True
        assert not np.array_equal(editor.base_image, before)

    def test_ctrl_z_undoes_and_ctrl_y_redoes(self, editor):
        editor.tool = Tool.RECTANGLE
        _press(editor, 50, 60)
        _motion(editor, 150, 200)
        _release(editor, 150, 200)

        assert _key(editor, Gdk.KEY_z, state=_ctrl()) is True
        assert len(editor.layer) == 0

        assert _key(editor, Gdk.KEY_y, state=_ctrl()) is True
        assert len(editor.layer) == 1

    def test_bare_z_opens_resize_while_ctrl_z_undoes(self, editor):
        # Resize is modal (ImageEditorForm.cs:1104's BtnResizeClick), so
        # only its routing can be asserted - run() would never return.
        calls = []
        editor._do_resize = lambda: calls.append("resize")

        assert _key(editor, Gdk.KEY_z) is True

        assert calls == ["resize"]

    @pytest.mark.parametrize("keyval,action", [(Gdk.KEY_s, "_do_save"), (Gdk.KEY_p, "_do_print")])
    def test_the_two_modal_ctrl_shortcuts_route_to_their_own_action(self, editor, keyval, action):
        calls = []
        setattr(editor, action, lambda *a, **k: calls.append(action))

        assert _key(editor, keyval, state=_ctrl()) is True

        assert calls == [action]

    def test_ctrl_g_grayscales_the_image(self, editor):
        assert _key(editor, Gdk.KEY_g, state=_ctrl()) is True

        image = editor.base_image
        assert np.array_equal(image[:, :, 0], image[:, :, 1])
        assert np.array_equal(image[:, :, 1], image[:, :, 2])

    def test_ctrl_i_inverts_the_image(self, editor):
        original = editor.base_image.copy()

        assert _key(editor, Gdk.KEY_i, state=_ctrl()) is True

        assert np.array_equal(editor.base_image[:, :, 0], 255 - original[:, :, 0])

    def test_ctrl_b_adds_a_border_that_grows_the_image(self, editor):
        assert _key(editor, Gdk.KEY_b, state=_ctrl()) is True

        assert editor.base_image.shape[:2] == (400 + 4, 640 + 4)

    def test_ctrl_q_applies_a_drop_shadow_and_ctrl_t_a_torn_edge(self, editor):
        assert _key(editor, Gdk.KEY_q, state=_ctrl()) is True
        after_shadow = editor.base_image.shape[:2]
        assert after_shadow != (400, 640)

        assert _key(editor, Gdk.KEY_t, state=_ctrl()) is True
        assert editor.base_image.shape[:2] != after_shadow

    def test_ctrl_c_copies_rather_than_activating_the_crop_tool(self, editor):
        # Bare C is the Crop button; the Ctrl branch must win.
        copied = []
        editor._do_copy = lambda: copied.append(True)

        assert _key(editor, Gdk.KEY_c, state=_ctrl()) is True

        assert copied == [True]
        assert editor.tool is Tool.SELECT

    def test_ctrl_comma_and_ctrl_period_rotate_the_image_each_way(self, editor):
        # Both sit past `if not ctrl_held: return False`, so the bare keys
        # are not bound at all - the rotate shortcuts are Ctrl+, / Ctrl+.
        assert _key(editor, Gdk.KEY_comma) is False

        assert _key(editor, Gdk.KEY_comma, state=_ctrl()) is True
        assert editor.base_image.shape[:2] == (640, 400)

        assert _key(editor, Gdk.KEY_period, state=_ctrl()) is True
        assert editor.base_image.shape[:2] == (400, 640)

    def test_an_unbound_key_is_left_for_the_rest_of_gtk(self, editor):
        assert _key(editor, Gdk.KEY_F5) is False
        assert _key(editor, Gdk.KEY_F5, state=_ctrl()) is False
