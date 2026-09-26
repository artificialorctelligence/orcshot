"""EditorWindow's document-state contracts, asserted against a real
Gtk.Window.

Every other EditorWindow behaviour tested so far has been logic split
*out* of this class precisely so it could be tested without one (see
ui/destination_picker.py's _should_reuse_editor and its docstring). That
left editor_window.py itself - 2678 executable lines, the largest file
in the app - at 0% coverage, verified only by hand on the VMs. The
contracts below are the ones its own docstrings state in full, so they
are worth pinning: is_modified's "not yet exported" semantics, the two
property setters that exist specifically to centralise a side effect
every call site would otherwise have to remember, and
reset_for_capture's document/window split.

Constructing the window needs a display; CI already runs the suite
under xvfb-run, and a developer without one gets these skipped the same
way the x11-marked capture tests skip (see the module-level skipif).
"""

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="EditorWindow is a real Gtk.Window - constructing one needs a display (CI: xvfb-run)",
)

from orcshot.core.geometry import Rect
from orcshot.core.shapes import RectangleShape, ShapeStyle
from orcshot.core.tools import Tool
from orcshot.ui.editor_window import EditorWindow


def _capture(width: int = 640, height: int = 400) -> np.ndarray:
    """A capture-shaped RGBA image with real variation in it, rather
    than a uniform block - the obfuscate/effect paths downstream read
    pixel values, so a zeros() array is not representative data.
    """
    xs = np.linspace(0, 255, width, dtype=np.uint8)
    ys = np.linspace(0, 255, height, dtype=np.uint8)
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[:, :, 0] = xs[None, :]
    image[:, :, 1] = ys[:, None]
    image[:, :, 2] = 128
    image[:, :, 3] = 255
    return image


@pytest.fixture
def editor():
    window = EditorWindow(_capture())
    yield window
    window.destroy()


def _shape(x: int = 12, y: int = 34) -> RectangleShape:
    return RectangleShape(bounds=Rect(x, y, 120, 80), style=ShapeStyle())


class TestIsModified:
    """is_modified is "not yet exported", not "the user touched
    something" - its docstring's own words, ported from Surface.cs.
    """

    def test_a_fresh_never_saved_capture_is_modified_with_zero_edits(self):
        window = EditorWindow(_capture())
        try:
            assert window.is_modified is True
        finally:
            window.destroy()

    def test_a_capture_already_written_to_disk_is_not_modified(self):
        window = EditorWindow(_capture(), already_saved=True)
        try:
            assert window.is_modified is False
        finally:
            window.destroy()


class TestSelection:
    def test_setting_selected_shape_replaces_the_whole_selection(self, editor):
        first, second = _shape(), _shape(200, 210)
        editor._set_selected_shapes([first, second])

        editor.selected_shape = second

        assert editor.selected_shapes == [second]

    def test_setting_selected_shape_to_none_clears_the_selection(self, editor):
        editor._set_selected_shapes([_shape(), _shape(200, 210)])

        editor.selected_shape = None

        assert editor.selected_shapes == []
        assert editor.selected_shape is None

    def test_selected_shape_is_the_most_recently_selected_of_several(self, editor):
        first, last = _shape(), _shape(300, 300)

        editor._set_selected_shapes([first, last])

        assert editor.selected_shape is last

    def test_selected_shapes_is_a_copy_so_callers_cannot_mutate_the_selection(self, editor):
        editor._set_selected_shapes([_shape()])

        editor.selected_shapes.append(_shape(400, 400))

        assert len(editor.selected_shapes) == 1


class TestToolSwitchDiscardsCrop:
    """The tool setter is the one choke point every tool switch passes
    through, so it is where an unconfirmed crop is abandoned - see its
    docstring.
    """

    def test_switching_to_a_drawing_tool_discards_an_unconfirmed_crop(self, editor):
        editor.tool = Tool.CROP_DEFAULT
        editor._crop_selection = Rect(10, 10, 100, 60)

        editor.tool = Tool.RECTANGLE

        assert editor._crop_selection is None
        assert editor._crop_resize_handle is None

    @pytest.mark.parametrize("mode", [Tool.CROP_DEFAULT, Tool.CROP_VERTICAL, Tool.CROP_HORIZONTAL])
    def test_switching_between_crop_modes_keeps_the_unconfirmed_crop(self, editor, mode):
        editor.tool = Tool.CROP_DEFAULT
        selection = Rect(10, 10, 100, 60)
        editor._crop_selection = selection

        editor.tool = mode

        assert editor._crop_selection is selection


class TestBaseImageAssignment:
    def test_assigning_a_new_base_image_updates_the_dimensions_label(self, editor):
        editor.base_image = _capture(1280, 720)

        assert editor._dimensions_label.get_text() == "1280 x 720"

    def test_assigning_a_new_base_image_drops_stale_ocr_bounds(self, editor):
        editor._ocr_result = object()

        editor.base_image = _capture(800, 600)

        assert editor._ocr_result is None

    def test_assigning_a_new_base_image_is_readable_back(self, editor):
        replacement = _capture(320, 240)

        editor.base_image = replacement

        assert editor.base_image is replacement


class TestResetForCapture:
    """Resets the document, deliberately keeps the window's own
    remembered preferences - see reset_for_capture's docstring.
    """

    def test_a_reused_editor_reports_the_new_capture_as_unsaved(self, editor):
        editor._saved_generation = editor.undo_redo.generation

        editor.reset_for_capture(_capture(320, 240), title="Mozilla Firefox")

        assert editor.is_modified is True

    def test_a_reused_editor_starts_with_an_empty_undo_history(self, editor):
        before = editor.undo_redo

        editor.reset_for_capture(_capture(320, 240))

        assert editor.undo_redo is not before
        assert editor.undo_redo.can_undo is False

    def test_a_reused_editor_clears_the_previous_selection_and_crop(self, editor):
        editor._set_selected_shapes([_shape()])
        editor._crop_selection = Rect(5, 5, 50, 50)

        editor.reset_for_capture(_capture(320, 240))

        assert editor.selected_shapes == []
        assert editor._crop_selection is None

    def test_a_reused_editor_remembers_the_new_capture_title(self, editor):
        editor.reset_for_capture(_capture(320, 240), title="Nautilus - Downloads")

        assert editor._window_title == "Nautilus - Downloads"

    def test_a_reused_editor_keeps_the_window_zoom_level(self, editor):
        editor._zoom = 2.0

        editor.reset_for_capture(_capture(320, 240))

        assert editor._zoom == 2.0

    def test_a_reused_editor_keeps_the_per_tool_style_memory(self, editor):
        editor.tool = Tool.RECTANGLE
        remembered = editor._style_for_tool(Tool.RECTANGLE)

        editor.reset_for_capture(_capture(320, 240))

        assert editor._style_for_tool(Tool.RECTANGLE) is remembered
