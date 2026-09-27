"""EditorWindow's eleven dialog-driven actions, run against real GTK
dialogs with only the blocking call taken out.

Every action here opens a modal and then reads its widgets back, so
none of them could be exercised at all while ``Gtk.Dialog.run()`` sat
in the middle blocking forever. The neutralisation below replaces
*only* ``run()`` - the dialog classes themselves are left alone on
purpose, because the widget-building code is most of what these
methods are (``_do_show_help`` is ~50 lines of grid, ``_do_resize``
~44 lines of spin buttons and an aspect-ratio lock) and swapping in a
fake dialog class would skip all of it while still reporting the lines
as untested. Leaving the real widgets in place also means a test can
poke the actual spin button the OK path reads back, which is how the
resize and settings tests below drive their values.

Both halves of each action are asserted: the Cancel path changes
nothing *and* destroys the dialog (a leaked modal is a real bug this
shape catches for free), and the OK path performs exactly the change
the action documents.

Two behaviours here are pinned as observed rather than as the plan
expected them - see TestMaybeShowQualityDialog and
TestTornEdgeSettings.

Constructing the window needs a display; CI already runs the suite
under xvfb-run, and a developer without one gets these skipped (see
the module-level skipif), the same way tests/unit/ui/
test_editor_window.py does.
"""

import os
from dataclasses import replace as dataclass_replace
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="EditorWindow is a real Gtk.Window - constructing one needs a display (CI: xvfb-run)",
)

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from orcshot.core.drawing import Layer
from orcshot.core.geometry import Rect
from orcshot.core.shapes import ImageShape, RectangleShape, ShapeStyle, SvgShape
from orcshot.settings import get_output_settings, set_output_settings
from orcshot.ui import editor_window as editor_window_module
from orcshot.ui.editor_window import EditorWindow
from orcshot.ui.file_export import save_image_to_file
from orcshot.ui.orcshot_file import (
    load_objects_file,
    load_orcshot_file,
    save_objects_file,
    save_orcshot_file,
)


def _capture(width: int = 640, height: int = 400) -> np.ndarray:
    """A capture-shaped RGBA image with real variation in it, rather
    than a uniform block - the effect paths these actions run (resize,
    drop shadow, torn edge) read pixel values, and every one of them
    would look identical against a zeros() array.

    Copied from tests/unit/ui/test_editor_window.py rather than
    imported: pytest runs this suite in importlib mode, where one test
    module importing another is not available.
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


def _shape(left: int = 100, top: int = 100, right: int = 200, bottom: int = 200) -> RectangleShape:
    return RectangleShape(bounds=Rect(left, top, right, bottom), style=ShapeStyle())


def _one_shape_layer() -> Layer:
    layer = Layer()
    layer.add(_shape(5, 5, 55, 55))
    return layer


def _undo_depth(window: EditorWindow) -> int:
    return len(window.undo_redo._undo)


def _descendants(widget, kind: type) -> list:
    """Every widget of ``kind`` below ``widget``, depth-first. Gtk.Box
    hands its children back in packing order, which is why the
    torn-edge test can index the edge checkboxes positionally; a
    Gtk.Grid does not, so grid contents are reached by get_child_at
    coordinates instead.
    """
    found = []
    for child in widget.get_children() if hasattr(widget, "get_children") else []:
        if isinstance(child, kind):
            found.append(child)
        found.extend(_descendants(child, kind))
    return found


def _grid_of(dialog) -> Gtk.Grid:
    grids = _descendants(dialog.get_content_area(), Gtk.Grid)
    assert grids, "the dialog packs no Gtk.Grid into its content area"
    return grids[0]


def _check_button(dialog, label: str) -> Gtk.CheckButton:
    for check in _descendants(dialog.get_content_area(), Gtk.CheckButton):
        if check.get_label() == label:
            return check
    raise AssertionError(f"no check button labelled {label!r} in this dialog")


class _Modal:
    """Answers ``Gtk.Dialog.run()`` instead of letting it block.

    Patched on ``Gtk.Dialog`` itself, so Gtk.MessageDialog is covered
    by the same patch (it inherits ``run``) - which matters for
    ``_do_load_objects``'s error path and ``_do_open_in_external_
    editor``'s "no editor found" path, both of which would otherwise
    hang on a second modal.

    Destruction is observed through the real "destroy" signal rather
    than by patching ``destroy()``, so the assertion is that the
    widget was genuinely torn down, not merely that a method was
    called.
    """

    def __init__(self, response, on_run=None):
        self._response = response
        self._on_run = on_run
        self.ran = []
        self.destroyed = []

    def install(self, monkeypatch) -> "_Modal":
        def fake_run(dialog):
            self.ran.append(dialog)
            dialog.connect("destroy", self.destroyed.append)
            if self._on_run is not None:
                self._on_run(dialog)
            return self._response

        monkeypatch.setattr(Gtk.Dialog, "run", fake_run)
        return self

    @property
    def leaked(self) -> list:
        return [dialog for dialog in self.ran if dialog not in self.destroyed]


class _Chooser:
    """The same idea for the file pickers, which are a different class
    hierarchy: every chooser in this module is a Gtk.FileChooserNative
    (BACKLOG #210 - never an in-process Gtk.FileChooserDialog, which
    tests/unit/ui/test_no_in_process_file_chooser.py enforces), and a
    Gtk.NativeDialog is not a Gtk.Widget at all. So it has its own
    ``run()``, no "destroy" signal to watch, and ``get_filename()``
    answers None unless a real dialog really ran - all three need
    standing in for.
    """

    def __init__(self, response, filename=None, on_run=None):
        self._response = response
        self._filename = None if filename is None else str(filename)
        self._on_run = on_run
        self.ran = []
        self.destroyed = []

    def install(self, monkeypatch) -> "_Chooser":
        real_destroy = Gtk.NativeDialog.destroy

        def fake_run(dialog):
            self.ran.append(dialog)
            if self._on_run is not None:
                self._on_run(dialog)
            return self._response

        def fake_destroy(dialog):
            self.destroyed.append(dialog)
            real_destroy(dialog)

        monkeypatch.setattr(Gtk.NativeDialog, "run", fake_run)
        monkeypatch.setattr(Gtk.NativeDialog, "destroy", fake_destroy)
        monkeypatch.setattr(Gtk.FileChooserNative, "get_filename", lambda _dialog: self._filename)
        return self

    @property
    def leaked(self) -> list:
        return [dialog for dialog in self.ran if dialog not in self.destroyed]


ACCEPT = Gtk.ResponseType.ACCEPT
CANCEL = Gtk.ResponseType.CANCEL
OK = Gtk.ResponseType.OK


class TestSaveObjects:
    """Object > Save objects to file. Writes the Layer alone as JSON -
    its own "*.json" extension, deliberately not claiming to be a real
    Windows .gst file (see the docstring).
    """

    def test_accepting_writes_the_layer_to_the_chosen_file(self, editor, tmp_path, monkeypatch):
        editor.layer.add(_shape())
        target = tmp_path / "objects.json"
        chooser = _Chooser(ACCEPT, filename=target).install(monkeypatch)

        editor._do_save_objects()

        assert target.exists()
        assert len(list(load_objects_file(target))) == 1
        assert chooser.leaked == []

    def test_a_filename_without_the_extension_gets_json_appended(self, editor, tmp_path, monkeypatch):
        editor.layer.add(_shape())
        _Chooser(ACCEPT, filename=tmp_path / "objects").install(monkeypatch)

        editor._do_save_objects()

        assert (tmp_path / "objects.json").exists()

    def test_cancelling_writes_nothing_and_destroys_the_chooser(self, editor, tmp_path, monkeypatch):
        editor.layer.add(_shape())
        chooser = _Chooser(CANCEL, filename=tmp_path / "objects.json").install(monkeypatch)

        editor._do_save_objects()

        assert list(tmp_path.iterdir()) == []
        assert chooser.ran and chooser.leaked == []


class TestLoadObjects:
    """Mirrors Save objects, and *adds* to the existing layer rather
    than replacing it - real Windows' LoadElementsFromStream does the
    same, and each loaded shape gets its own undo entry because no
    bulk-load memento type exists here.
    """

    def test_loading_adds_to_the_existing_layer_rather_than_replacing_it(self, editor, tmp_path, monkeypatch):
        source = tmp_path / "objects.json"
        save_objects_file(_one_shape_layer(), source)
        editor.layer.add(_shape(10, 10, 60, 60))
        _Chooser(ACCEPT, filename=source).install(monkeypatch)

        editor._do_load_objects()

        assert len(list(editor.layer)) == 2

    def test_each_loaded_shape_is_its_own_undo_entry_and_the_last_is_selected(
        self, editor, tmp_path, monkeypatch
    ):
        scratch = EditorWindow(_capture())
        try:
            scratch.layer.add(_shape(0, 0, 40, 40))
            scratch.layer.add(_shape(50, 50, 90, 90))
            source = tmp_path / "two.json"
            save_objects_file(scratch.layer, source)
        finally:
            scratch.destroy()
        _Chooser(ACCEPT, filename=source).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_load_objects()

        assert _undo_depth(editor) == before + 2
        assert editor.selected_shape is list(editor.layer)[-1]

    def test_a_save_objects_file_round_trips_the_layer(self, editor, tmp_path, monkeypatch):
        original = _shape(12, 34, 112, 134)
        editor.layer.add(original)
        path = tmp_path / "round-trip.json"
        _Chooser(ACCEPT, filename=path).install(monkeypatch)
        editor._do_save_objects()

        reloaded = EditorWindow(_capture())
        try:
            _Chooser(ACCEPT, filename=path).install(monkeypatch)
            reloaded._do_load_objects()
            assert [s.bounds for s in reloaded.layer] == [original.bounds]
        finally:
            reloaded.destroy()

    def test_a_full_orcshot_file_loads_too_with_its_image_discarded(self, editor, tmp_path, monkeypatch):
        """load_objects_file's own documented behaviour: either a Save
        Objects file or a full .orcshot file, image thrown away.
        """
        path = tmp_path / "document.orcshot"
        save_orcshot_file(_capture(320, 240), _one_shape_layer(), path)
        _Chooser(ACCEPT, filename=path).install(monkeypatch)
        before_image = editor.base_image

        editor._do_load_objects()

        assert len(list(editor.layer)) == 1
        assert editor.base_image is before_image

    def test_cancelling_adds_nothing(self, editor, tmp_path, monkeypatch):
        source = tmp_path / "objects.json"
        save_objects_file(_one_shape_layer(), source)
        chooser = _Chooser(CANCEL, filename=source).install(monkeypatch)

        editor._do_load_objects()

        assert list(editor.layer) == []
        assert chooser.leaked == []

    def test_an_unreadable_file_reports_an_error_and_adds_nothing(self, editor, tmp_path, monkeypatch):
        broken = tmp_path / "broken.json"
        broken.write_text("this is not an orcshot objects file")
        _Chooser(ACCEPT, filename=broken).install(monkeypatch)
        modal = _Modal(OK).install(monkeypatch)

        editor._do_load_objects()

        assert list(editor.layer) == []
        assert [type(d) for d in modal.ran] == [Gtk.MessageDialog], "the failure must be reported, not swallowed"
        assert modal.leaked == []


class TestSave:
    """Save As... - always dialog-driven, with its own "Save as type"
    chooser choice rather than trusting whatever extension was typed.
    """

    def test_saving_writes_a_real_file_and_clears_is_modified(self, editor, tmp_path, monkeypatch):
        target = tmp_path / "shot.png"
        _Chooser(ACCEPT, filename=target).install(monkeypatch)

        assert editor.is_modified is True
        assert editor._do_save() is True

        assert target.exists() and target.stat().st_size > 0
        assert editor.is_modified is False

    def test_the_chosen_format_fixes_up_a_filename_with_the_wrong_extension(
        self, editor, tmp_path, monkeypatch
    ):
        _Chooser(ACCEPT, filename=tmp_path / "shot.bmp", on_run=lambda d: d.set_choice("format", "png")).install(
            monkeypatch
        )

        editor._do_save()

        assert (tmp_path / "shot.png").exists()
        assert not (tmp_path / "shot.bmp").exists()

    def test_the_orcshot_format_keeps_the_shapes_separately_re_editable(self, editor, tmp_path, monkeypatch):
        editor.layer.add(_shape(20, 30, 120, 130))
        target = tmp_path / "document.orcshot"
        _Chooser(
            ACCEPT, filename=target, on_run=lambda d: d.set_choice("format", "orcshot")
        ).install(monkeypatch)

        editor._do_save()

        image, layer = load_orcshot_file(target)
        assert image.shape == (400, 640, 4)
        assert [s.bounds for s in layer] == [Rect(20, 30, 120, 130)]

    def test_cancelling_writes_nothing_and_leaves_the_document_modified(self, editor, tmp_path, monkeypatch):
        chooser = _Chooser(CANCEL, filename=tmp_path / "shot.png").install(monkeypatch)

        assert editor._do_save() is False

        assert list(tmp_path.iterdir()) == []
        assert editor.is_modified is True
        assert chooser.ran and chooser.leaked == []


class TestMaybeShowQualityDialog:
    """The gate here is the "always show quality dialog" setting and
    *only* that setting - not the format.

    The plan for this task expected a prompt for a lossy format and
    silence for a lossless one. That is not what this does, and the
    behaviour is pinned as it stands rather than changed: the method's
    own docstring calls it a "format-independent gate matching Windows
    exactly (ImageIO.cs:422/FileDestination.cs:80 gate purely on the
    setting, not on format)". The format decides whether the slider is
    *interactive*, which is the assertion below - a deliberate port
    decision, not an oversight.
    """

    @pytest.fixture(autouse=True)
    def _restore_output_settings(self):
        before = get_output_settings()
        yield
        set_output_settings(before)

    @pytest.mark.parametrize("output_format", ["jpg", "png"])
    def test_the_setting_off_is_a_no_op_for_every_format(self, editor, monkeypatch, output_format):
        set_output_settings(dataclass_replace(get_output_settings(), always_show_quality_dialog=False))
        modal = _Modal(OK).install(monkeypatch)

        editor._maybe_show_quality_dialog(output_format)

        assert modal.ran == []

    @pytest.mark.parametrize(
        ("output_format", "slider_interactive"),
        [("jpg", True), ("png", False)],
    )
    def test_the_setting_on_prompts_for_every_format_but_only_jpg_can_move_the_slider(
        self, editor, monkeypatch, output_format, slider_interactive
    ):
        set_output_settings(dataclass_replace(get_output_settings(), always_show_quality_dialog=True))
        sensitivity = []
        modal = _Modal(
            OK, on_run=lambda d: sensitivity.append(_descendants(d.get_content_area(), Gtk.Scale)[0].get_sensitive())
        ).install(monkeypatch)

        editor._maybe_show_quality_dialog(output_format)

        assert len(modal.ran) == 1
        assert sensitivity == [slider_interactive]
        assert modal.leaked == []

    def test_the_slider_value_is_written_back_to_the_settings(self, editor, monkeypatch):
        set_output_settings(
            dataclass_replace(get_output_settings(), always_show_quality_dialog=True, jpeg_quality=80)
        )
        _Modal(OK, on_run=lambda d: _descendants(d.get_content_area(), Gtk.Scale)[0].set_value(45)).install(
            monkeypatch
        )

        editor._maybe_show_quality_dialog("jpg")

        assert get_output_settings().jpeg_quality == 45


class TestResize:
    """ResizeSettingsForm's equivalent: width/height in pixels with an
    aspect-ratio lock, applied as one undoable step that also scales
    every existing shape (_apply_background_effect's ``transform``).
    """

    def test_ok_resizes_the_image_and_pushes_exactly_one_undo_entry(self, editor, monkeypatch):
        _Modal(OK, on_run=lambda d: _grid_of(d).get_child_at(1, 0).set_value(320)).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_resize()

        # 320 wide with the aspect lock on (its default) takes the
        # 640x400 capture to 320x200, not 320x400.
        assert editor.base_image.shape == (200, 320, 4)
        assert _undo_depth(editor) == before + 1

    def test_ok_scales_the_existing_shapes_to_match(self, editor, monkeypatch):
        editor.layer.add(_shape(100, 100, 200, 200))
        _Modal(OK, on_run=lambda d: _grid_of(d).get_child_at(1, 0).set_value(320)).install(monkeypatch)

        editor._do_resize()

        assert [s.bounds for s in editor.layer] == [Rect(50, 50, 100, 100)]

    def test_unlocking_the_aspect_ratio_leaves_the_height_alone(self, editor, monkeypatch):
        def set_width_only(dialog):
            _check_button(dialog, "Maintain aspect ratio").set_active(False)
            _grid_of(dialog).get_child_at(1, 0).set_value(320)

        _Modal(OK, on_run=set_width_only).install(monkeypatch)

        editor._do_resize()

        assert editor.base_image.shape == (400, 320, 4)

    def test_cancelling_leaves_the_image_identical_and_pushes_no_undo_entry(self, editor, monkeypatch):
        before_image = editor.base_image
        before = _undo_depth(editor)
        modal = _Modal(CANCEL, on_run=lambda d: _grid_of(d).get_child_at(1, 0).set_value(320)).install(monkeypatch)

        editor._do_resize()

        assert editor.base_image is before_image
        assert editor.base_image.shape == (400, 640, 4)
        assert _undo_depth(editor) == before
        assert modal.ran and modal.leaked == []


class TestDropShadowSettings:
    """The right-click half of the drop shadow button: the same effect,
    with the spin buttons shown first. Settings are session-only (a
    deliberate scope reduction against Windows' ini persistence), so
    the assertion is on the live dict the next left-click will reuse.
    """

    def test_ok_remembers_the_new_settings_and_applies_the_effect(self, editor, monkeypatch):
        def fill_in(dialog):
            grid = _grid_of(dialog)
            grid.get_child_at(1, 0).set_value(0.25)  # darkness
            grid.get_child_at(1, 1).set_value(12)  # size
            grid.get_child_at(1, 2).set_value(4)  # offset x
            grid.get_child_at(1, 3).set_value(-3)  # offset y

        _Modal(OK, on_run=fill_in).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_drop_shadow_settings()

        assert editor._drop_shadow_settings == {"darkness": 0.25, "size": 12, "offset": (4, -3)}
        assert editor.base_image.shape[:2] != (400, 640), "the shadow was never actually drawn"
        assert _undo_depth(editor) == before + 1

    def test_the_spin_buttons_open_on_the_current_settings(self, editor, monkeypatch):
        editor._drop_shadow_settings = {"darkness": 0.4, "size": 9, "offset": (2, 5)}
        shown = []
        _Modal(
            CANCEL,
            on_run=lambda d: shown.append(
                tuple(_grid_of(d).get_child_at(1, row).get_value() for row in range(4))
            ),
        ).install(monkeypatch)

        editor._do_drop_shadow_settings()

        assert shown == [(0.4, 9.0, 2.0, 5.0)]

    def test_cancelling_changes_neither_the_settings_nor_the_image(self, editor, monkeypatch):
        before_settings = dict(editor._drop_shadow_settings)
        before_image = editor.base_image
        before = _undo_depth(editor)
        modal = _Modal(CANCEL, on_run=lambda d: _grid_of(d).get_child_at(1, 1).set_value(40)).install(monkeypatch)

        editor._do_drop_shadow_settings()

        assert editor._drop_shadow_settings == before_settings
        assert editor.base_image is before_image
        assert _undo_depth(editor) == before
        assert modal.ran and modal.leaked == []


class TestTornEdgeSettings:
    """The right-click half of the torn edge button.

    The shape translation pinned below is BACKLOG #220's second
    ui/effects.py finding, observed rather than corrected: with
    "Generate shadow" *off*, the canvas still grows by shadow_size on
    every side - a transparent margin sized by a shadow that was never
    drawn - and _do_torn_edge only doubles its own shape offset when
    the shadow is on. direflail's call whether that is a bug; it is a
    live-verified visual effect, so this test records what it does.
    """

    def test_ok_remembers_every_field_including_the_edge_checkboxes(self, editor, monkeypatch):
        def fill_in(dialog):
            grid = _grid_of(dialog)
            grid.get_child_at(1, 0).set_value(18)  # tooth height
            grid.get_child_at(1, 1).set_value(30)  # horizontal tooth range
            grid.get_child_at(1, 2).set_value(25)  # vertical tooth range
            # The four edge checks sit in their own Gtk.Box, packed
            # Top, Right, Bottom, Left - drop the bottom one.
            _check_button(dialog, "Bottom").set_active(False)
            _check_button(dialog, "Generate shadow").set_active(False)

        _Modal(OK, on_run=fill_in).install(monkeypatch)

        editor._do_torn_edge_settings()

        assert editor._torn_edge_settings["tooth_height"] == 18
        assert editor._torn_edge_settings["horizontal_tooth_range"] == 30
        assert editor._torn_edge_settings["vertical_tooth_range"] == 25
        assert editor._torn_edge_settings["edges"] == (True, True, False, True)
        assert editor._torn_edge_settings["generate_shadow"] is False

    def test_ok_applies_the_effect_as_one_undoable_step(self, editor, monkeypatch):
        _Modal(OK).install(monkeypatch)
        before_image = editor.base_image
        before = _undo_depth(editor)

        editor._do_torn_edge_settings()

        assert editor.base_image is not before_image
        assert _undo_depth(editor) == before + 1

    @pytest.mark.parametrize(
        ("generate_shadow", "offset"),
        # shadow_size is 7 by default; the shadow doubles the offset
        # because torn_edge_image pads once for the tear and again for
        # the shadow it chains into.
        [(True, 14), (False, 7)],
    )
    def test_the_shape_offset_follows_the_shadow_toggle(self, editor, monkeypatch, generate_shadow, offset):
        editor.layer.add(_shape(100, 100, 200, 200))
        _Modal(
            OK, on_run=lambda d: _check_button(d, "Generate shadow").set_active(generate_shadow)
        ).install(monkeypatch)

        editor._do_torn_edge_settings()

        assert [s.bounds for s in editor.layer] == [Rect(100 + offset, 100 + offset, 200 + offset, 200 + offset)]

    def test_cancelling_changes_neither_the_settings_nor_the_image(self, editor, monkeypatch):
        before_settings = dict(editor._torn_edge_settings)
        before_image = editor.base_image
        modal = _Modal(CANCEL, on_run=lambda d: _grid_of(d).get_child_at(1, 0).set_value(40)).install(monkeypatch)

        editor._do_torn_edge_settings()

        assert editor._torn_edge_settings == before_settings
        assert editor.base_image is before_image
        assert modal.ran and modal.leaked == []


class TestInsertImage:
    def _png(self, tmp_path, width=80, height=60):
        path = tmp_path / "insert.png"
        save_image_to_file(_capture(width, height), path)
        return path

    def test_accepting_appends_one_image_shape_centered_at_its_natural_size(
        self, editor, tmp_path, monkeypatch
    ):
        _Chooser(ACCEPT, filename=self._png(tmp_path)).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_insert_image()

        shapes = list(editor.layer)
        assert len(shapes) == 1
        assert isinstance(shapes[0], ImageShape)
        # Natural 80x60 - under 0.8 of the 640x400 canvas, so never
        # scaled up - centred: (640-80)/2, (400-60)/2.
        assert shapes[0].bounds == Rect(280, 170, 360, 230)
        assert editor.selected_shape is shapes[0]
        assert _undo_depth(editor) == before + 1

    def test_an_image_larger_than_the_canvas_is_scaled_down_to_fit(self, editor, tmp_path, monkeypatch):
        _Chooser(ACCEPT, filename=self._png(tmp_path, 1280, 800)).install(monkeypatch)

        editor._do_insert_image()

        bounds = list(editor.layer)[0].bounds
        assert (bounds.width, bounds.height) == (512, 320)  # 0.8 of 640x400

    def test_cancelling_appends_nothing(self, editor, tmp_path, monkeypatch):
        chooser = _Chooser(CANCEL, filename=self._png(tmp_path)).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_insert_image()

        assert list(editor.layer) == []
        assert _undo_depth(editor) == before
        assert chooser.ran and chooser.leaked == []


_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
    '<rect x="5" y="5" width="90" height="40" fill="#3366cc"/>'
    "</svg>"
)


class TestInsertSvg:
    def _svg(self, tmp_path):
        path = tmp_path / "insert.svg"
        path.write_text(_SVG)
        return path

    def test_accepting_appends_one_svg_shape_holding_the_files_markup(self, editor, tmp_path, monkeypatch):
        _Chooser(ACCEPT, filename=self._svg(tmp_path)).install(monkeypatch)
        before = _undo_depth(editor)

        editor._do_insert_svg()

        shapes = list(editor.layer)
        assert len(shapes) == 1
        assert isinstance(shapes[0], SvgShape)
        assert shapes[0].svg_data == _SVG
        # Sized from the SVG's own declared 100x50, centred.
        assert shapes[0].bounds == Rect(270, 175, 370, 225)
        assert editor.selected_shape is shapes[0]
        assert _undo_depth(editor) == before + 1

    def test_cancelling_appends_nothing(self, editor, tmp_path, monkeypatch):
        chooser = _Chooser(CANCEL, filename=self._svg(tmp_path)).install(monkeypatch)

        editor._do_insert_svg()

        assert list(editor.layer) == []
        assert chooser.ran and chooser.leaked == []


class TestOpenInExternalEditor:
    """Exports a PNG to $XDG_CACHE_HOME/orcshot (never /tmp - a
    Flatpak target's /tmp is its own private tmpfs, confirmed live)
    and hands it to whichever candidate editor is installed.

    Nothing here runs a real process: shutil.which, subprocess.run
    (the `flatpak list` probe) and subprocess.Popen are all faked, and
    the assertions are on the argv the action *would* have used.
    """

    @pytest.fixture
    def cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        return tmp_path / "cache" / "orcshot"

    @pytest.fixture
    def launched(self, monkeypatch):
        calls = []
        monkeypatch.setattr(editor_window_module.subprocess, "Popen", lambda argv: calls.append(argv))
        return calls

    def _no_processes(self, monkeypatch, on_path=(), flatpak_apps=None):
        """PATH holds only ``on_path``; `flatpak list` answers with
        ``flatpak_apps`` (None meaning flatpak itself is not
        installed).
        """
        available = set(on_path) | ({"flatpak"} if flatpak_apps is not None else set())
        monkeypatch.setattr(
            editor_window_module.shutil, "which", lambda name: f"/usr/bin/{name}" if name in available else None
        )
        monkeypatch.setattr(
            editor_window_module.subprocess,
            "run",
            lambda *_a, **_kw: SimpleNamespace(stdout="\n".join(flatpak_apps or [])),
        )

    def test_a_path_installed_editor_is_launched_on_the_exported_png(
        self, editor, cache_dir, launched, monkeypatch
    ):
        self._no_processes(monkeypatch, on_path=["krita"])

        editor._do_open_in_external_editor()

        exported = editor._external_editor_temp_path
        assert launched == [["krita", str(exported)]]
        assert exported.parent == cache_dir
        assert exported.suffix == ".png" and exported.stat().st_size > 0

    def test_a_flatpak_only_editor_is_launched_through_flatpak_run(
        self, editor, cache_dir, launched, monkeypatch
    ):
        """The reason the Flatpak branch exists at all: this dev
        machine has Krita only via Flatpak, so a plain which() check
        would have missed it.
        """
        self._no_processes(monkeypatch, flatpak_apps=["org.kde.krita", "org.gnome.Loupe"])

        editor._do_open_in_external_editor()

        assert launched == [["flatpak", "run", "org.kde.krita", str(editor._external_editor_temp_path)]]

    def test_gimp_is_the_fallback_when_krita_is_absent(self, editor, cache_dir, launched, monkeypatch):
        self._no_processes(monkeypatch, on_path=["gimp"])

        editor._do_open_in_external_editor()

        assert launched[0][0] == "gimp"

    def test_no_editor_installed_explains_itself_and_launches_nothing(
        self, editor, cache_dir, launched, monkeypatch
    ):
        self._no_processes(monkeypatch)
        modal = _Modal(OK).install(monkeypatch)

        editor._do_open_in_external_editor()

        assert launched == []
        assert [type(d) for d in modal.ran] == [Gtk.MessageDialog]
        assert modal.leaked == []

    def test_a_second_export_deletes_the_first_rather_than_piling_up(
        self, editor, cache_dir, launched, monkeypatch
    ):
        self._no_processes(monkeypatch, on_path=["krita"])

        editor._do_open_in_external_editor()
        first = editor._external_editor_temp_path
        editor._do_open_in_external_editor()
        second = editor._external_editor_temp_path

        assert first != second
        assert not first.exists()
        assert second.exists()
        assert sorted(p.name for p in cache_dir.iterdir()) == [second.name]


class TestShowHelp:
    """The Help dialog is ~50 lines of Gtk.Grid, and two of its
    properties were live-reported bugs on a 1366x768 VM (task
    #127/#128): content running off the screen with the Close button
    out of reach, and the dialog opening already scrolled down because
    GTK focused one of the later selectable labels. Both fixes are
    asserted here, since neither is visible from reading the grid.
    """

    def test_every_help_section_and_every_key_reaches_the_grid(self, editor, monkeypatch):
        texts = []

        def collect(dialog):
            grid = _descendants(dialog.get_content_area(), Gtk.Grid)[0]
            texts.extend(label.get_text() for label in _descendants(grid, Gtk.Label))

        _Modal(Gtk.ResponseType.CLOSE, on_run=collect).install(monkeypatch)

        editor._do_show_help()

        for title, entries in EditorWindow._HELP_SECTIONS:
            assert title in texts, f"the {title!r} help section never reached the grid"
            for entry in entries:
                assert entry[0] in texts, f"help key {entry[0]!r} never reached the grid"
        # The Tray Icon section is appended after _HELP_SECTIONS, not
        # part of it - a separate append that a loop over the constant
        # alone would not notice going missing.
        assert "Tray Icon" in texts
        for key, _function in EditorWindow._tray_icon_help_rows():
            assert key in texts

    def test_the_dialog_cannot_grow_past_a_low_res_screen_and_scrolls_instead(self, editor, monkeypatch):
        observed = {}

        def inspect(dialog):
            scroller = _descendants(dialog.get_content_area(), Gtk.ScrolledWindow)[0]
            observed["size"] = tuple(dialog.get_default_size())
            observed["policy"] = scroller.get_policy()
            observed["scrolled_to"] = scroller.get_vadjustment().get_value()

        modal = _Modal(Gtk.ResponseType.CLOSE, on_run=inspect).install(monkeypatch)

        editor._do_show_help()

        assert observed["size"] == (520, 480)
        # Vertical scrolling only: this dialog's long rows wrap rather
        # than needing an hscrollbar.
        assert observed["policy"] == (Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        assert observed["scrolled_to"] == 0, "the help dialog opened already scrolled down (task #127/#128)"
        assert modal.leaked == []

    def test_the_dialog_is_destroyed_and_the_document_is_untouched(self, editor, monkeypatch):
        editor.layer.add(_shape())
        before_image = editor.base_image
        before = _undo_depth(editor)
        modal = _Modal(Gtk.ResponseType.CLOSE).install(monkeypatch)

        editor._do_show_help()

        assert len(modal.ran) == 1 and modal.leaked == []
        assert editor.base_image is before_image
        assert _undo_depth(editor) == before
